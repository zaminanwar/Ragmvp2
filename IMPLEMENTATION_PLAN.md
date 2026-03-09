# Bleeding-Edge Enterprise RAG System — Implementation Plan

## Guiding Principle

Take the enterprise system's production skeleton (FastAPI, PostgreSQL, Docker, auth, multi-tenancy, streaming) and fill it with the demo's agentic intelligence — then push beyond both with techniques neither currently has. Every change must be measurable via automated evaluation.

---

## Phase 0: Evaluation Framework (Do This First)

**Why first**: You cannot improve what you cannot measure. Every subsequent phase needs before/after metrics.

### 0.1 — RAGAS Evaluation Pipeline

**New files:**
- `backend/app/evaluation/__init__.py`
- `backend/app/evaluation/metrics.py`
- `backend/app/evaluation/runner.py`
- `backend/app/evaluation/datasets.py`

**Implementation:**

```
evaluation/metrics.py
├── faithfulness(answer, contexts) -> float        # Is the answer grounded in retrieved context?
├── answer_relevancy(answer, question) -> float    # Does the answer address the question?
├── context_precision(contexts, ground_truth) -> float  # Are relevant chunks ranked higher?
├── context_recall(contexts, ground_truth) -> float     # Were all relevant chunks retrieved?
└── answer_correctness(answer, ground_truth) -> float   # Is the answer factually correct?
```

- Use the LLM providers already in `rag/llm/` to compute LLM-as-judge metrics
- Each metric returns a float 0.0-1.0
- Runner takes a dataset of (question, ground_truth_answer, ground_truth_contexts) tuples
- Store evaluation results in a new `evaluation_runs` table for tracking over time

```
evaluation/datasets.py
├── EvalSample(question, ground_truth_answer, ground_truth_contexts)
├── load_dataset(path: str) -> list[EvalSample]      # Load from JSON/JSONL
└── generate_synthetic_dataset(documents, llm) -> list[EvalSample]  # LLM-generated QA pairs
```

**New API route:** `backend/app/api/routes/evaluation.py`
- `POST /api/eval/run` — Run evaluation on a workspace with a dataset
- `GET /api/eval/results/{run_id}` — Get detailed results
- `GET /api/eval/compare` — Compare two evaluation runs

**New dependency:** `ragas>=0.2.0` (or implement core metrics directly to avoid heavy dependency)

**New DB model:** `backend/app/models/evaluation.py`
```python
class EvaluationRun(UUIDMixin, TimestampMixin, Base):
    workspace_id: UUID
    dataset_name: str
    config_snapshot: dict  # JSON of RAG config at time of run
    metrics: dict          # JSON of aggregate metric scores
    sample_count: int
    status: str            # pending, running, completed, failed

class EvaluationSample(UUIDMixin, Base):
    run_id: UUID
    question: str
    ground_truth: str
    generated_answer: str
    contexts_used: list[str]  # JSON
    metric_scores: dict       # JSON per-sample scores
```

**Estimated touch points:** 6 new files, 1 new API route, 1 new model, 1 alembic migration

---

## Phase 1: Agentic RAG Orchestration

**Goal**: Replace the linear pipeline in `RAGEngine` with a LangGraph-based state machine that implements Adaptive, Corrective, and Self-Reflective RAG patterns.

### 1.1 — Install LangGraph

**File:** `backend/requirements.txt` (or pyproject.toml)
- Add: `langgraph>=0.2.0`, `langchain-core>=0.3.0`

### 1.2 — Define Agent State

**New file:** `backend/app/rag/agent/state.py`

```python
from typing import TypedDict, Annotated
import operator

class RAGAgentState(TypedDict):
    question: str
    query_type: str                                    # vector, fulltext, hybrid
    documents: list[dict]                              # retrieved chunks
    retrieval_attempts: int
    generation: str
    documents_relevant: bool
    answer_grounded: bool
    rewritten_question: str
    sources: list[dict]                                # citation metadata
    search_mode_used: str
    agent_trace: Annotated[list[str], operator.add]    # accumulates across nodes
    # Enterprise additions:
    workspace_id: str
    chat_history: list[dict]                           # prior messages
    system_prompt: str
    enable_reranking: bool
    enable_hyde: bool
    top_k: int
    model_config: dict                                 # llm_provider, llm_model, temperature
```

### 1.3 — Implement Agent Nodes

**New file:** `backend/app/rag/agent/nodes.py`

Each node is an async function: `async def node_name(state: RAGAgentState, **deps) -> dict`

| Node | Purpose | Dependencies |
|------|---------|-------------|
| `route_query` | Classify query → vector/fulltext/hybrid | LLM provider |
| `retrieve` | Fetch docs via HybridRetriever or VectorRetriever based on route | Retriever, embedding provider, DB session |
| `rerank` | Apply Cohere/LLM reranker to retrieved docs | Reranker |
| `grade_documents` | LLM evaluates relevance of each chunk | LLM provider |
| `rewrite_question` | LLM rewrites query for better retrieval | LLM provider |
| `generate` | Synthesize answer from graded context + chat history | LLM provider |
| `check_hallucination` | Verify answer is grounded in source chunks | LLM provider |

**Key difference from demo**: All nodes are async, use the enterprise's multi-provider LLM system, and operate on workspace-scoped data.

**Port from demo with these adaptations:**
- Replace Ollama-specific logic (`_prep_prompt`, `_clean_llm_output`) with provider-agnostic calls via `BaseLLM.generate()`
- Replace ChromaDB retrieval with `HybridRetriever.retrieve(query, workspace_id, top_k)`
- Add reranking as a separate node (demo doesn't have this)
- Use enterprise's chat history format instead of demo's stateless approach

### 1.4 — Implement Agent Edges

**New file:** `backend/app/rag/agent/edges.py`

```python
async def should_generate_or_rewrite(state: RAGAgentState) -> str:
    if state["documents_relevant"] or state["retrieval_attempts"] >= 3:
        return "generate"
    return "rewrite"

async def should_return_or_regenerate(state: RAGAgentState) -> str:
    if state["answer_grounded"]:
        return "end"
    gen_count = sum(1 for t in state.get("agent_trace", []) if t == "generate")
    if gen_count >= 2:
        return "end"
    return "regenerate"

def should_rerank(state: RAGAgentState) -> str:
    if state["enable_reranking"]:
        return "rerank"
    return "grade_documents"
```

### 1.5 — Build the Graph

**New file:** `backend/app/rag/agent/graph.py`

```
Graph Flow:

  route_query ──→ retrieve ──→ [rerank?] ──→ grade_documents
                      ↑                           │
                      │                    ┌──────┴──────┐
                      │                    │             │
                 rewrite_question    documents_ok    docs_not_ok
                                         │             │
                                    generate    (loop if attempts < 3)
                                         │
                                  check_hallucination
                                         │
                                   ┌─────┴─────┐
                                   │           │
                                 grounded   not_grounded
                                   │           │
                                  END    regenerate (max 2)
```

Compile with LangGraph:
```python
from langgraph.graph import StateGraph, END

def build_rag_graph(llm, retriever, reranker, workspace_config):
    graph = StateGraph(RAGAgentState)
    # Add nodes (bind dependencies via functools.partial)
    graph.add_node("route_query", partial(route_query, llm=llm))
    graph.add_node("retrieve", partial(retrieve, retriever=retriever))
    graph.add_node("rerank", partial(rerank, reranker=reranker))
    graph.add_node("grade_documents", partial(grade_documents, llm=llm))
    graph.add_node("rewrite_question", partial(rewrite_question, llm=llm))
    graph.add_node("generate", partial(generate, llm=llm))
    graph.add_node("check_hallucination", partial(check_hallucination, llm=llm))

    # Set entry point
    graph.set_entry_point("route_query")

    # Add edges
    graph.add_edge("route_query", "retrieve")
    graph.add_conditional_edges("retrieve", should_rerank, {
        "rerank": "rerank", "grade_documents": "grade_documents"
    })
    graph.add_edge("rerank", "grade_documents")
    graph.add_conditional_edges("grade_documents", should_generate_or_rewrite, {
        "generate": "generate", "rewrite": "rewrite_question"
    })
    graph.add_edge("rewrite_question", "retrieve")
    graph.add_edge("generate", "check_hallucination")
    graph.add_conditional_edges("check_hallucination", should_return_or_regenerate, {
        "end": END, "regenerate": "generate"
    })

    return graph.compile()
```

### 1.6 — Integrate into RAGEngine

**Modify:** `backend/app/rag/engine.py`

Replace the linear `query()` and `query_stream()` methods to use the compiled graph:

```python
class RAGEngine:
    def __init__(self, ...):
        # existing params
        self.graph = build_rag_graph(self.llm, self.retriever, self.reranker, ...)

    async def query(self, query, workspace_id, ...):
        initial_state = {
            "question": query,
            "workspace_id": str(workspace_id),
            "chat_history": chat_history or [],
            "system_prompt": system_prompt or "",
            "enable_reranking": self.reranker is not None,
            "enable_hyde": False,  # Phase 2
            "top_k": top_k,
            "model_config": {...},
            # Zero-value defaults:
            "query_type": "hybrid",
            "documents": [],
            "retrieval_attempts": 0,
            "generation": "",
            "documents_relevant": False,
            "answer_grounded": False,
            "rewritten_question": "",
            "sources": [],
            "search_mode_used": "",
            "agent_trace": [],
        }
        result = await self.graph.ainvoke(initial_state)
        return RAGResponse(
            content=result["generation"],
            citations=result["sources"],
            context=RAGContext(
                chunks=result["documents"],
                was_corrective=result["retrieval_attempts"] > 1,
                original_query=query,
                rewritten_query=result.get("rewritten_question"),
            ),
            # ... token counts from generation
        )
```

For streaming: Use `graph.astream()` and yield tokens from the "generate" node.

### 1.7 — Prompts

**New file:** `backend/app/rag/agent/prompts.py`

Port and improve the demo's prompts. Key prompts needed:

| Prompt | Purpose |
|--------|---------|
| `ROUTER_PROMPT` | Classify query complexity → route to retrieval strategy |
| `GRADER_PROMPT` | Judge relevance of each retrieved chunk (JSON output) |
| `GENERATOR_PROMPT` | Synthesize answer from context with citation instructions |
| `HALLUCINATION_PROMPT` | Check if answer is grounded in sources (JSON output) |
| `REWRITE_PROMPT` | Rewrite query for better retrieval |
| `HYDE_PROMPT` | Generate hypothetical document (Phase 2) |
| `DECOMPOSE_PROMPT` | Break complex query into sub-queries (Phase 2) |

**Improvement over demo**: Make prompts provider-agnostic (no Ollama-specific `/no_think` hacks). Use structured output format that works across OpenAI, Anthropic, and Ollama.

### 1.8 — Update ChatService

**Modify:** `backend/app/services/chat_service.py`

In `_build_engine()`: No changes needed if RAGEngine interface stays the same.

Add agent trace to message metadata:
```python
# In send_message():
assistant_msg.metadata_json = {
    "agent_trace": rag_response.context.agent_trace,
    "search_mode_used": rag_response.context.search_mode_used,
    ...
}
```

### 1.9 — Update Message Model

**Modify:** `backend/app/models/chat.py`

Add field to Message:
```python
agent_trace: dict = Column(JSONB, default={})  # Store execution path
```

Run alembic migration.

**Estimated touch points:** 5 new files, 3 modified files, 1 migration

---

## Phase 2: Advanced Retrieval Techniques

### 2.1 — HyDE (Hypothetical Document Embeddings)

**Goal**: For abstract/conceptual queries, generate a hypothetical answer, embed it, and use that embedding for retrieval. This bridges the query-document semantic gap.

**New file:** `backend/app/rag/retrieval/hyde.py`

```python
class HyDERetriever:
    def __init__(self, llm: BaseLLM, embedding: BaseEmbedding, vector_retriever: VectorRetriever):
        self.llm = llm
        self.embedding = embedding
        self.vector_retriever = vector_retriever

    async def retrieve(self, query: str, workspace_id: UUID, top_k: int = 5) -> list[RetrievalResult]:
        # 1. Generate hypothetical document
        hypothetical = await self.llm.generate(
            prompt=f"Write a detailed passage that would answer this question:\n{query}",
            system="Write a factual, detailed passage. Do not say you are generating a hypothetical answer.",
        )
        # 2. Embed the hypothetical document
        hyde_embedding = await self.embedding.embed_text(hypothetical.content)
        # 3. Retrieve using hypothetical embedding instead of query embedding
        results = await self.vector_retriever.retrieve_by_embedding(
            embedding=hyde_embedding, workspace_id=workspace_id, top_k=top_k
        )
        for r in results:
            r.metadata["hyde_used"] = True
        return results
```

**Modify:** `backend/app/rag/retrieval/vector_search.py`
- Add `retrieve_by_embedding(embedding, workspace_id, top_k)` method that accepts a pre-computed embedding vector

**Integration**: Add as option in `route_query` node — router decides whether to use HyDE based on query type (abstract/conceptual → HyDE, factual/specific → standard).

**Workspace config addition:** `enable_hyde: bool = False` in Workspace model.

### 2.2 — Query Decomposition

**Goal**: For multi-part questions, decompose into sub-queries, retrieve independently, and merge results before generation.

**New file:** `backend/app/rag/agent/decomposition.py`

```python
async def decompose_query(question: str, llm: BaseLLM) -> list[str]:
    """Break a complex question into independent sub-questions."""
    response = await llm.generate(
        prompt=f"Question: {question}",
        system=DECOMPOSE_PROMPT,  # Returns JSON array of sub-questions
    )
    sub_questions = parse_json_array(response.content)
    if len(sub_questions) <= 1:
        return [question]  # Not worth decomposing
    return sub_questions

async def retrieve_decomposed(
    sub_questions: list[str], retriever, workspace_id, top_k
) -> list[RetrievalResult]:
    """Retrieve for each sub-question in parallel, merge with RRF."""
    all_results = await asyncio.gather(*[
        retriever.retrieve(q, workspace_id, top_k) for q in sub_questions
    ])
    # Merge using RRF across sub-query result sets
    return reciprocal_rank_fusion(
        {f"subq_{i}": results for i, results in enumerate(all_results)},
        weights={f"subq_{i}": 1.0 for i in range(len(all_results))},
        top_k=top_k
    )
```

**Integration**: Add as a new node in the graph between `route_query` and `retrieve`. Router classifies: simple → direct retrieve, complex multi-part → decompose first.

### 2.3 — Contextual Chunk Embeddings (Anthropic-Style)

**Goal**: Prepend document-level context to each chunk before embedding, so the embedding captures both local and global meaning. This is one of the highest-impact retrieval improvements available today.

**Reference**: Anthropic's "Contextual Retrieval" technique.

**Modify:** `backend/app/services/document_service.py`

In `upload_and_process()`, after chunking but before embedding:

```python
async def _add_contextual_headers(self, chunks: list[Chunk], full_text: str, llm: BaseLLM) -> list[Chunk]:
    """Prepend document context to each chunk for better embeddings."""
    # Generate document summary once
    doc_summary = await llm.generate(
        prompt=f"Summarize this document in 2-3 sentences:\n{full_text[:3000]}",
        system="Provide a brief factual summary.",
    )

    # For each chunk, generate a contextual header
    contextualized_chunks = []
    for chunk in chunks:
        context_response = await llm.generate(
            prompt=(
                f"Document summary: {doc_summary.content}\n\n"
                f"Chunk content: {chunk.content}\n\n"
                "In 1-2 sentences, describe what this chunk is about in the context of the whole document."
            ),
            system="Write a brief contextual description. Be factual and specific.",
        )
        # Prepend context to chunk content for embedding
        contextualized_content = f"{context_response.content}\n\n{chunk.content}"
        new_chunk = Chunk(
            content=chunk.content,  # Keep original for display
            chunk_index=chunk.chunk_index,
            metadata={**chunk.metadata, "contextual_header": context_response.content},
            token_count=chunk.token_count,
        )
        new_chunk._embedding_content = contextualized_content  # Embed this version
        contextualized_chunks.append(new_chunk)

    return contextualized_chunks
```

**Trade-off**: This adds LLM calls during ingestion (one per chunk + one for summary). For large documents, batch the context generation. Make this optional via workspace config: `enable_contextual_embeddings: bool = False`.

**Modify:** `backend/app/rag/chunking/base.py`
- Add optional `_embedding_content` field to `Chunk` dataclass (defaults to `content`)

### 2.4 — Parent-Child Hierarchical Chunking

**Goal**: Index small chunks (256 tokens) for precise matching, but return parent chunks (1024 tokens) for richer context in generation.

**New file:** `backend/app/rag/chunking/hierarchical.py`

```python
class HierarchicalChunker(BaseChunker):
    def __init__(self, parent_size=1024, child_size=256, overlap=50):
        self.parent_chunker = RecursiveChunker(chunk_size=parent_size, chunk_overlap=overlap)
        self.child_chunker = RecursiveChunker(chunk_size=child_size, chunk_overlap=overlap // 2)

    def chunk(self, text: str, metadata: dict) -> tuple[list[Chunk], list[Chunk]]:
        parents = self.parent_chunker.chunk(text, metadata)
        children = []
        for parent_idx, parent in enumerate(parents):
            child_chunks = self.child_chunker.chunk(parent.content, {
                **metadata,
                "parent_chunk_index": parent_idx,
                "chunk_strategy": "hierarchical_child",
            })
            children.extend(child_chunks)
        return parents, children
```

**DB changes:** Add `parent_chunk_id: UUID | None` to `DocumentChunk` model.

**Retrieval change:** In `VectorRetriever.retrieve()`, after finding matching child chunks, look up their parents:
```python
# After getting child results:
parent_ids = [r.metadata.get("parent_chunk_id") for r in results if r.metadata.get("parent_chunk_id")]
if parent_ids:
    parents = await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(parent_ids)))
    # Replace child content with parent content for generation
```

**Workspace config:** `chunk_strategy: str = "recursive"` — options: "recursive", "semantic", "hierarchical"

### 2.5 — Source-Diversity-Aware RRF

**Modify:** `backend/app/rag/retrieval/hybrid_search.py`

Port the demo's two-pass RRF algorithm that ensures results span multiple source documents:

```python
def _reciprocal_rank_fusion(self, vector_results, fulltext_results, top_k):
    # ... existing RRF scoring ...

    # Pass 1: Best result per source document
    seen_sources = set()
    diverse_results = []
    for result in sorted_by_rrf:
        source = result.metadata.get("original_filename", "unknown")
        if source not in seen_sources:
            seen_sources.add(source)
            diverse_results.append(result)
            if len(diverse_results) >= top_k:
                break

    # Pass 2: Fill remaining slots by score
    used_ids = {r.chunk_id for r in diverse_results}
    for result in sorted_by_rrf:
        if result.chunk_id not in used_ids:
            diverse_results.append(result)
            if len(diverse_results) >= top_k:
                break

    return diverse_results
```

---

## Phase 3: Knowledge Graph Integration

### 3.1 — Lightweight Knowledge Graph (No GraphRAG Dependency)

**Why not port GraphRAG directly**: GraphRAG is heavy, designed for batch processing, and uses LanceDB. Instead, build a lightweight KG that integrates with the existing PostgreSQL infrastructure.

**New files:**
- `backend/app/rag/knowledge_graph/__init__.py`
- `backend/app/rag/knowledge_graph/extractor.py`
- `backend/app/rag/knowledge_graph/store.py`
- `backend/app/rag/knowledge_graph/retriever.py`

**New DB models:** `backend/app/models/knowledge_graph.py`

```python
class Entity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    workspace_id: UUID          # FK → Workspace
    name: str                   # Entity name (normalized)
    entity_type: str            # PERSON, ORG, CONCEPT, TECH, etc.
    description: str | None     # LLM-generated description
    embedding: list             # Vector(1536) for entity search
    source_chunks: list[UUID]   # JSON array of chunk IDs that mention this entity
    metadata_json: dict

class Relationship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "relationships"
    workspace_id: UUID
    source_entity_id: UUID      # FK → Entity
    target_entity_id: UUID      # FK → Entity
    relationship_type: str      # e.g., "USES", "PART_OF", "RELATES_TO"
    description: str | None
    weight: float = 1.0         # Strength of relationship
    source_chunks: list[UUID]   # JSON array of chunk IDs

class Community(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "communities"
    workspace_id: UUID
    name: str
    summary: str                # LLM-generated community summary
    entity_ids: list[UUID]      # JSON array
    level: int                  # Hierarchy level (0 = leaf)
```

### 3.2 — Entity/Relationship Extraction

**File:** `backend/app/rag/knowledge_graph/extractor.py`

```python
class KnowledgeGraphExtractor:
    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def extract_from_chunk(self, chunk_content: str, chunk_id: UUID) -> tuple[list[Entity], list[Relationship]]:
        """Extract entities and relationships from a single chunk."""
        response = await self.llm.generate(
            prompt=f"Text:\n{chunk_content}",
            system=ENTITY_EXTRACTION_PROMPT,  # Returns JSON with entities and relationships
        )
        parsed = parse_json(response.content)
        entities = [Entity(name=e["name"], entity_type=e["type"], ...) for e in parsed["entities"]]
        relationships = [Relationship(...) for r in parsed["relationships"]]
        return entities, relationships

    async def extract_from_document(self, chunks: list[Chunk]) -> tuple[list[Entity], list[Relationship]]:
        """Extract and deduplicate across all chunks in a document."""
        all_entities, all_rels = [], []
        # Process chunks in parallel batches of 5
        for batch in batched(chunks, 5):
            results = await asyncio.gather(*[
                self.extract_from_chunk(c.content, c.id) for c in batch
            ])
            for entities, rels in results:
                all_entities.extend(entities)
                all_rels.extend(rels)

        # Deduplicate entities by normalized name
        return self._deduplicate(all_entities, all_rels)

    async def build_communities(self, entities, relationships) -> list[Community]:
        """Use LLM to group related entities into communities and generate summaries."""
        # Build adjacency from relationships
        # Use simple connected components or LLM-based clustering
        # Generate community summaries
        ...
```

### 3.3 — Graph-Enhanced Retrieval

**File:** `backend/app/rag/knowledge_graph/retriever.py`

```python
class GraphRetriever:
    def __init__(self, db: AsyncSession, embedding: BaseEmbedding):
        self.db = db
        self.embedding = embedding

    async def retrieve(self, query: str, workspace_id: UUID, top_k: int = 5) -> list[RetrievalResult]:
        # 1. Find relevant entities by embedding similarity
        query_embedding = await self.embedding.embed_text(query)
        entities = await self._find_similar_entities(query_embedding, workspace_id, top_k=10)

        # 2. Expand to related entities via relationships (1-hop)
        expanded_entities = await self._expand_neighbors(entities, workspace_id)

        # 3. Collect all source chunks referenced by these entities
        chunk_ids = set()
        for entity in expanded_entities:
            chunk_ids.update(entity.source_chunks)

        # 4. Fetch and return chunks
        chunks = await self._fetch_chunks(chunk_ids, workspace_id)

        # 5. Also include community summaries for high-level questions
        communities = await self._find_relevant_communities(query_embedding, workspace_id)

        return self._merge_results(chunks, communities, top_k)
```

### 3.4 — Integration into Ingestion Pipeline

**Modify:** `backend/app/services/document_service.py`

After chunking and embedding, add KG extraction:
```python
# In upload_and_process(), after embedding and indexing:
if workspace.enable_knowledge_graph:
    extractor = KnowledgeGraphExtractor(llm)
    entities, relationships = await extractor.extract_from_document(chunks)
    await self._store_kg_data(entities, relationships, workspace_id)
```

### 3.5 — Integration into Retrieval

**Modify:** `backend/app/rag/retrieval/hybrid_search.py`

Add graph retrieval as a third signal in the hybrid search:
```python
class HybridRetriever:
    def __init__(self, ..., graph_retriever: GraphRetriever | None = None, graph_weight: float = 0.3):
        self.graph_retriever = graph_retriever
        self.graph_weight = graph_weight

    async def retrieve(self, ...):
        tasks = [vector_task, fulltext_task]
        if self.graph_retriever:
            tasks.append(self.graph_retriever.retrieve(query, workspace_id, top_k))
        results = await asyncio.gather(*tasks)
        # RRF with 3 signals: vector (0.5) + fulltext (0.3) + graph (0.2)
```

**Workspace config:** `enable_knowledge_graph: bool = False`

---

## Phase 4: Semantic Caching

### 4.1 — Query-Level Semantic Cache

**Goal**: Cache RAG responses for semantically similar queries. If a new query is >0.95 cosine similar to a cached query, return the cached response.

**New file:** `backend/app/rag/cache.py`

```python
class SemanticCache:
    def __init__(self, redis_client, embedding: BaseEmbedding, threshold: float = 0.95):
        self.redis = redis_client
        self.embedding = embedding
        self.threshold = threshold

    async def get(self, query: str, workspace_id: str) -> RAGResponse | None:
        query_embedding = await self.embedding.embed_text(query)
        # Check against cached query embeddings in Redis
        cached_keys = await self.redis.keys(f"rag_cache:{workspace_id}:*")
        for key in cached_keys:
            cached_data = await self.redis.hgetall(key)
            cached_embedding = json.loads(cached_data["embedding"])
            similarity = cosine_similarity(query_embedding, cached_embedding)
            if similarity >= self.threshold:
                return RAGResponse(**json.loads(cached_data["response"]))
        return None

    async def set(self, query: str, workspace_id: str, response: RAGResponse, ttl: int = 3600):
        query_embedding = await self.embedding.embed_text(query)
        cache_key = f"rag_cache:{workspace_id}:{hash(query)}"
        await self.redis.hset(cache_key, mapping={
            "embedding": json.dumps(query_embedding),
            "response": response.json(),
            "query": query,
        })
        await self.redis.expire(cache_key, ttl)
```

**Integration**: Check cache at the start of `RAGEngine.query()`, set cache after successful generation.

**Cache invalidation**: Invalidate workspace cache when documents are added/removed.

**Note**: For production scale, use a proper vector similarity index in Redis (Redis Stack with vector search) rather than brute-force scanning.

---

## Phase 5: Production Hardening

### 5.1 — Structured Output Parsing

**New file:** `backend/app/rag/agent/output_parser.py`

Robust JSON extraction that works across all LLM providers:
```python
def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown blocks, extra text, etc."""
    # Try 1: Direct JSON parse
    # Try 2: Extract from ```json ... ``` blocks
    # Try 3: Find first { ... } or [ ... ] in text
    # Try 4: Return safe default
```

### 5.2 — Circuit Breaker for LLM Calls

**New file:** `backend/app/rag/agent/resilience.py`

Wrap LLM calls with circuit breaker pattern (use `tenacity` already in deps):
```python
@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
async def safe_llm_call(llm, prompt, system, fallback=None):
    try:
        return await llm.generate(prompt=prompt, system=system)
    except Exception:
        if fallback:
            return LLMResponse(content=fallback, model="fallback", ...)
        raise
```

### 5.3 — Token Budget Management

**Modify:** `backend/app/rag/agent/nodes.py`

In the `generate` node, enforce token budget:
```python
# Before calling LLM, trim context to fit model's context window
max_context_tokens = 4000  # configurable
current_tokens = 0
trimmed_docs = []
for doc in state["documents"]:
    doc_tokens = count_tokens(doc["content"])
    if current_tokens + doc_tokens > max_context_tokens:
        break
    trimmed_docs.append(doc)
    current_tokens += doc_tokens
```

### 5.4 — Observability & Tracing

**Modify:** `backend/app/rag/agent/nodes.py`

Add timing and metrics to each node:
```python
import time
import structlog

logger = structlog.get_logger()

async def retrieve(state, retriever):
    start = time.monotonic()
    results = await retriever.retrieve(...)
    duration = time.monotonic() - start
    logger.info("rag.retrieve", duration_ms=duration*1000, result_count=len(results),
                mode=state["search_mode_used"], workspace_id=state["workspace_id"])
    ...
```

### 5.5 — Frontend: Agent Trace Visualization

**Modify:** Frontend chat component to display agent execution path:
- Show which nodes executed (route → retrieve → grade → generate → hallucination check)
- Show retrieval mode used
- Show if corrective RAG triggered (query rewrite)
- Show if regeneration occurred
- Collapsible "How this answer was generated" section

---

## Phase 6: Cutting-Edge Additions (Future)

These are lower-priority but would push to true bleeding edge:

| Technique | What It Does | Complexity |
|-----------|-------------|-----------|
| **ColBERT** | Token-level late interaction retrieval — far more precise than single-vector | High (needs custom model serving) |
| **RAPTOR** | Build summarization tree over documents, retrieve at multiple granularities | Medium |
| **Multi-Modal RAG** | Extract and reason over images, tables, charts in documents | High |
| **Fine-tuned Embeddings** | Train domain-specific embeddings on your corpus | Medium |
| **Speculative RAG** | Generate multiple candidate answers, select best via self-consistency | Low (just parallel LLM calls) |
| **Agentic Chunking** | LLM decides chunk boundaries based on semantic coherence | Medium |

---

## Implementation Order & Dependencies

```
Phase 0: Evaluation Framework
  └── No dependencies. Do this first.
      Estimated: 6 new files, 1 migration

Phase 1: Agentic RAG Orchestration
  └── Depends on: Nothing (can parallelize with Phase 0)
      Estimated: 6 new files, 3 modified files, 1 migration
      KEY FILES:
        NEW:  backend/app/rag/agent/state.py
        NEW:  backend/app/rag/agent/nodes.py
        NEW:  backend/app/rag/agent/edges.py
        NEW:  backend/app/rag/agent/graph.py
        NEW:  backend/app/rag/agent/prompts.py
        NEW:  backend/app/rag/agent/__init__.py
        MOD:  backend/app/rag/engine.py
        MOD:  backend/app/services/chat_service.py
        MOD:  backend/app/models/chat.py

Phase 2: Advanced Retrieval
  └── Depends on: Phase 1 (graph nodes need to support new retrieval modes)
      Can be done incrementally — each technique is independent:
      2.1 HyDE:                1 new file, 1 modified file
      2.2 Query Decomposition: 1 new file, 1 modified node
      2.3 Contextual Chunks:   2 modified files (ingestion + chunk model)
      2.4 Hierarchical Chunks: 1 new file, 2 modified files, 1 migration
      2.5 Source-Diverse RRF:  1 modified file

Phase 3: Knowledge Graph
  └── Depends on: Phase 1 (needs graph node for KG retrieval)
      Estimated: 4 new files, 2 modified files, 1 migration
      KEY FILES:
        NEW:  backend/app/rag/knowledge_graph/extractor.py
        NEW:  backend/app/rag/knowledge_graph/store.py
        NEW:  backend/app/rag/knowledge_graph/retriever.py
        NEW:  backend/app/models/knowledge_graph.py
        MOD:  backend/app/services/document_service.py
        MOD:  backend/app/rag/retrieval/hybrid_search.py

Phase 4: Semantic Caching
  └── Depends on: Phase 1 (caches RAGResponse objects)
      Estimated: 1 new file, 1 modified file

Phase 5: Production Hardening
  └── Depends on: Phase 1 (hardens the agent nodes)
      Estimated: 2 new files, 3 modified files, frontend changes
```

---

## Config Changes Summary

**New Workspace model fields** (single migration):
```python
# Phase 1
enable_adaptive_routing: bool = True
enable_self_reflection: bool = True
max_retrieval_attempts: int = 3
max_generation_attempts: int = 2

# Phase 2
enable_hyde: bool = False
enable_query_decomposition: bool = False
enable_contextual_embeddings: bool = False
chunk_strategy: str = "recursive"  # recursive | semantic | hierarchical

# Phase 3
enable_knowledge_graph: bool = False

# Phase 4
enable_semantic_cache: bool = False
cache_ttl_seconds: int = 3600
cache_similarity_threshold: float = 0.95
```

---

## New Dependencies

```
# Phase 1
langgraph>=0.2.0
langchain-core>=0.3.0

# Phase 0 (optional, can implement metrics directly)
ragas>=0.2.0  # or implement core metrics without this

# Phase 3 (optional, for community detection)
networkx>=3.0  # likely already available
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| LangGraph adds latency (multiple LLM calls per query) | Make agentic features toggleable per workspace. Simple queries can skip grading/hallucination checks via router. |
| Contextual embeddings are expensive at ingestion time | Make optional. Batch process. Use cheaper/faster model for context generation. |
| Knowledge graph extraction quality varies | Start with simple entity extraction. Validate with evaluation framework before expanding. |
| Breaking existing API contracts | RAGEngine.query() and RAGResponse keep same interface. Changes are internal. |
| LangGraph streaming complexity | Use graph.astream_events() for node-level streaming. Fall back to buffered streaming if needed. |

---

## Success Criteria

After all phases, the system should demonstrate measurable improvements on RAGAS metrics:

| Metric | Naive RAG Baseline | Target |
|--------|-------------------|--------|
| Faithfulness | ~0.65 | >0.90 |
| Answer Relevancy | ~0.70 | >0.85 |
| Context Precision | ~0.55 | >0.80 |
| Context Recall | ~0.60 | >0.85 |
| Answer Correctness | ~0.60 | >0.80 |

The evaluation framework (Phase 0) provides the measurement. Each subsequent phase should show improvement on at least one metric without regression on others.
