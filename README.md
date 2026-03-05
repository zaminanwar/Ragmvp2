# Enterprise RAG System

A state-of-the-art Retrieval-Augmented Generation platform combining the best patterns from RAGFlow, Open WebUI, AnythingLLM, Pathway, and awesome-llm-apps.

## Architecture

```
                    ┌─────────────┐
                    │   Nginx     │ (Reverse Proxy)
                    │   :80       │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼────────┐     ┌─────────▼─────────┐
     │   Frontend       │     │   Backend API      │
     │   React + Vite   │     │   FastAPI :8000     │
     │   :3000          │     │                     │
     └──────────────────┘     └──────────┬──────────┘
                                         │
           ┌─────────────────────────────┼─────────────────────────┐
           │                             │                         │
  ┌────────▼────────┐         ┌──────────▼──────────┐   ┌─────────▼─────────┐
  │  PostgreSQL      │         │  Elasticsearch       │   │  Redis             │
  │  + pgvector      │         │  (Full-text/BM25)    │   │  (Cache/Queue)     │
  │  :5432           │         │  :9200               │   │  :6379             │
  └──────────────────┘         └─────────────────────┘   └───────────────────┘
           │
  ┌────────▼────────┐         ┌─────────────────────┐   ┌───────────────────┐
  │  MinIO           │         │  Ollama              │   │  Collector Worker  │
  │  (Object Store)  │         │  (Local LLM)         │   │  (Async Processing)│
  │  :9000           │         │  :11434              │   │                    │
  └──────────────────┘         └─────────────────────┘   └───────────────────┘
```

## Key Features

### RAG Engine (from RAGFlow + awesome-llm-apps)
- **Hybrid Search**: Combines vector similarity (pgvector) with BM25 full-text (Elasticsearch) using Reciprocal Rank Fusion
- **Corrective RAG (CRAG)**: Self-healing retrieval that evaluates relevance and auto-rewrites queries when results are poor
- **Re-ranking**: LLM-based and Cohere API re-ranking for precision improvement
- **Grounded Citations**: Every answer links back to source chunks with relevance scores
- **Semantic + Recursive Chunking**: Smart document segmentation with heading-aware splitting

### Multi-Provider LLM Support (from AnythingLLM)
- **OpenAI**: GPT-4o, GPT-4-turbo, o1-preview, etc.
- **Anthropic**: Claude Opus, Sonnet, Haiku
- **Ollama**: Any local model (Llama, Mistral, Gemma, etc.)
- Pluggable provider architecture - add new providers easily

### Workspace Isolation (from AnythingLLM)
- Workspace-based multi-tenancy with isolated document collections
- Per-workspace RAG configuration (model, temperature, chunk size, search strategy)
- Customizable system prompts per workspace
- Role-based membership (Owner, Admin, Editor, Viewer)

### Document Processing (from RAGFlow + Pathway)
- **9 file formats**: PDF, DOCX, PPTX, XLSX, CSV, HTML, JSON, Markdown, TXT
- Deep parsing with table extraction and heading preservation
- Configurable chunking strategies (recursive, semantic)
- Async background processing via collector worker

### Enterprise Features (from Open WebUI)
- **RBAC**: Admin, Manager, Member, Viewer roles
- **JWT Authentication** with secure password hashing
- **Rate Limiting**: Per-IP request throttling
- **Request Logging**: Structured logging with timing
- **Pipeline Middleware**: Extensible filter chain (query cleanup, safety, token budgeting, usage tracking)
- **Admin Dashboard**: System stats, user management, provider monitoring
- **Streaming**: SSE and WebSocket support for real-time responses

### Frontend (from Open WebUI)
- Modern React + TypeScript + Tailwind CSS
- Dark mode UI with responsive design
- Chat with citations and corrective RAG indicators
- Drag-and-drop document upload
- Workspace management
- Admin panel with system statistics

## Quick Start

### Prerequisites
- Docker and Docker Compose
- At least one LLM API key (OpenAI or Anthropic) or Ollama installed

### Setup

1. **Clone and configure:**
```bash
cp .env.example .env
# Edit .env with your API keys
```

2. **Start all services:**
```bash
docker-compose up -d
```

3. **Run database migrations:**
```bash
docker-compose exec backend alembic upgrade head
```

4. **Access the application:**
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/api/docs
- MinIO Console: http://localhost:9001

### Development

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Current user |
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| POST | `/api/documents/upload` | Upload & process document |
| GET | `/api/documents/workspace/{id}` | List documents |
| POST | `/api/chat/send` | Send message (complete) |
| POST | `/api/chat/stream` | Send message (SSE stream) |
| WS | `/api/chat/ws/{workspace_id}` | WebSocket chat |
| GET | `/api/models/providers` | Available LLM providers |
| GET | `/api/admin/stats` | System statistics |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| Database | PostgreSQL 16 + pgvector |
| Search | Elasticsearch 8 |
| Cache/Queue | Redis 7 |
| Storage | MinIO (S3-compatible) |
| LLM | OpenAI, Anthropic, Ollama |
| Embeddings | OpenAI text-embedding-3-small, Ollama nomic-embed-text |
| Deployment | Docker Compose, Nginx |

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/routes/      # FastAPI route handlers
│   │   ├── core/            # Security, middleware, exceptions
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── services/        # Business logic layer
│   │   ├── rag/
│   │   │   ├── chunking/    # Document parsing & chunking
│   │   │   ├── embeddings/  # Embedding providers
│   │   │   ├── retrieval/   # Vector, full-text, hybrid search
│   │   │   ├── llm/         # LLM provider abstraction
│   │   │   └── engine.py    # Core RAG orchestrator + CRAG
│   │   └── pipelines/       # Middleware filter framework
│   └── alembic/             # Database migrations
├── frontend/
│   └── src/
│       ├── api/             # API client
│       ├── components/      # React components
│       ├── pages/           # Page views
│       ├── stores/          # Zustand state management
│       └── types/           # TypeScript types
├── collector/               # Async document processing worker
├── nginx/                   # Reverse proxy config
└── docker-compose.yml       # Full infrastructure
```
