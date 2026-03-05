"""Prompt templates for agentic RAG nodes.

All prompts are provider-agnostic (no Ollama-specific hacks).
LLM-as-judge prompts use JSON output format for reliable parsing.
"""

ROUTER_PROMPT = """You are a query routing expert. Classify the user's question to determine the best retrieval strategy.

Choose ONE mode:
- "vector": For simple factual lookups where semantic similarity is sufficient (e.g., "What is X?", "Define Y")
- "fulltext": For exact keyword/phrase searches (e.g., specific names, codes, identifiers, error messages)
- "hybrid": For complex questions requiring both semantic and keyword matching (DEFAULT for most questions)

Question: {question}

Respond with ONLY a JSON object:
{{"search_mode": "<vector|fulltext|hybrid>", "reasoning": "<brief explanation>"}}"""


GRADER_PROMPT = """You are a relevance grading expert. Evaluate whether the following document chunk is relevant to answering the question.

Be INCLUSIVE in your assessment — mark as relevant if the chunk contains ANY information that could help answer the question, even indirectly. A chunk that provides background, context, or partial information is still relevant.

Question: {question}

Document chunk:
{document}

Respond with ONLY a JSON object:
{{"relevant": true, "reasoning": "<brief explanation>"}}"""


GENERATOR_PROMPT = """You are a knowledgeable assistant that answers questions based on provided context.

RULES:
1. Base your answer ONLY on the provided context chunks
2. Cite sources using [Source N] notation where N matches the source number
3. If the context doesn't contain enough information, say so clearly
4. Be precise and factual — never fabricate information not present in the sources
5. Synthesize information across multiple sources when relevant
6. If sources contain conflicting information, acknowledge the discrepancy

## Retrieved Context
{context}

## Conversation History
{chat_history}

## Question
{question}"""


HALLUCINATION_PROMPT = """You are a fact-checking expert. Determine whether the following answer is fully grounded in (supported by) the provided source documents.

An answer is "grounded" if every factual claim in it can be traced back to information in the sources. Minor rephrasing is acceptable, but new facts, statistics, or claims not in the sources make it NOT grounded.

Sources:
{sources}

Answer to evaluate:
{answer}

Respond with ONLY a JSON object:
{{"grounded": true, "reasoning": "<brief explanation>"}}"""


REWRITE_PROMPT = """You are a search query optimization expert. The original query did not retrieve sufficiently relevant documents. Rewrite it to improve retrieval.

Strategies:
- Use different terminology or synonyms
- Be more specific about what information is needed
- Break down compound concepts
- Add relevant technical terms

Original question: {question}

Respond with ONLY the rewritten query text, nothing else."""


HYDE_PROMPT = """Write a detailed, factual passage that would directly answer the following question. Write as if this passage exists in a reference document.

Do NOT say "I don't know" or hedge — write a confident, informative passage even if hypothetical. This passage will be used for semantic search, not shown to the user.

Question: {question}

Passage:"""


DECOMPOSE_PROMPT = """You are a query analysis expert. Determine if this question should be broken into simpler sub-questions for better retrieval.

If the question is already simple and focused, return it as-is in a single-element array.
If the question is complex or multi-part, decompose it into 2-4 independent sub-questions.

Question: {question}

Respond with ONLY a JSON array of strings:
["sub-question 1", "sub-question 2", ...]"""


ENTITY_EXTRACTION_PROMPT = """Extract entities and relationships from the following text. Focus on key concepts, people, organizations, technologies, and their connections.

Text:
{text}

Respond with ONLY a JSON object:
{{
  "entities": [
    {{"name": "entity name", "type": "PERSON|ORG|CONCEPT|TECH|LOCATION|EVENT", "description": "brief description"}}
  ],
  "relationships": [
    {{"source": "entity1 name", "target": "entity2 name", "type": "USES|PART_OF|RELATES_TO|CREATED_BY|LOCATED_IN", "description": "brief description"}}
  ]
}}"""
