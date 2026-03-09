# Workflow Orchestration Engine — Implementation Plan

> **Base path**: `Ragmvp2-claude-enterprise-rag-system-daU8l/`

---

## 1. Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Frontend    │────▶│  API Layer   │────▶│  Services  │
│  (React)     │     │  (FastAPI)   │     │            │
└─────────────┘     └──────────────┘     └─────┬──────┘
                                               │
                    ┌──────────────────────────┤
                    │                          │
              ┌─────▼──────┐          ┌────────▼────────┐
              │  Workflow   │          │   RAG Engine    │
              │  Engine     │          │   (existing)    │
              │  ┌────────┐ │          └─────────────────┘
              │  │Executor│ │
              │  │Resolver│ │───▶ Tool Registry
              │  │Scheduler│ │        ├── rag_tools
              │  └────────┘ │        ├── llm_tools
              └─────────────┘        ├── document_tools
                                     ├── export_tools
                    │                ├── transform_tools
                    ▼                └── ALM tools (via adapters)
              ┌─────────────┐
              │  Adapters   │───▶ Polarion, DOORS, Jira (future)
              └─────────────┘
```

### Core Principles

1. **Adapter pattern** for all external systems — new ALM = new folder, no other changes
2. **Configuration-driven** — Polarion schema drives classification, same binary for any enterprise
3. **Contracts between layers** — BaseTool, ALMAdapter, ToolInput/ToolOutput
4. **Observability from day one** — structured logging on every tool exec, state transition, LLM call
5. **Idempotency everywhere** — upserts, hash checks, step results keyed by (run_id, step_id)
6. **Separable deployment** — `enable_workflow_worker` flag splits API vs worker containers
7. **Multi-tenancy isolation** — every query scoped by workspace_id
8. **Async-first** — all external calls async, cancellable, connection pooled

---

## 2. The Requirements Compliance Workflow

```
PREP: Upload corpus to RAG workspace (existing functionality)

Step 1: FETCH POLARION SCHEMA
  └─ Query Polarion API for WorkItem types, custom fields, enum values, link roles
  └─ Cache (refreshable). Drives classification in Step 2.

Step 2: PARSE & CLASSIFY requirements PDF
  └─ Parse PDF into structured blocks
  └─ LLM classifies each block using Polarion's actual schema as targets
  └─ Output is directly API-importable (no translation layer)

Step 3: IMPORT TO POLARION
  └─ Push WorkItems via REST API (idempotent upsert)
  └─ Create module, establish parent-child links

═══ HUMAN CHECKPOINT: Review/edit in Polarion ═══

Step 4: EXPORT FROM POLARION (source of truth)
  └─ Pull current state — includes any human edits since import
  └─ Polarion is canonical, compliance check uses THIS

Step 5: COMPLIANCE CHECK (RAG + LLM judgment)
  └─ For each requirement: query RAG against corpus workspace
  └─ LLM judges: Met / Partially Met / Not Met / Insufficient Evidence
  └─ Output: evidence, sources, confidence (0-1), gaps, suggested actions

Step 6: WRITE COMPLIANCE RESULTS BACK TO POLARION
  └─ Update custom fields: compliance_status, compliance_confidence,
     compliance_evidence, compliance_gaps

Step 7: GENERATE COMPLIANCE MATRIX (convenience export)
  └─ Excel: Req ID | Text | Status | Confidence | Evidence | Gaps
  └─ Summary stats, gap analysis. For stakeholder review.
```

---

## 3. Project Structure (new + modified files)

```
backend/app/
├── models/
│   ├── __init__.py                        # MODIFY: add workflow model imports
│   └── workflow.py                        # NEW: 5 SQLAlchemy models
│
├── api/routes/
│   └── workflows.py                       # NEW: all workflow endpoints
│
├── services/
│   └── workflow_service.py                # NEW: workflow business logic
│
├── workflows/                             # NEW: orchestration engine
│   ├── __init__.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── executor.py                    # State machine — step-by-step execution
│   │   ├── resolver.py                    # $-variable resolution
│   │   └── scheduler.py                   # Redis job queue + background worker
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                        # BaseTool, ToolInput, ToolOutput
│   │   ├── registry.py                    # ToolRegistry singleton
│   │   ├── rag_tools.py                   # rag.query, rag.batch_query, rag.ingest
│   │   ├── llm_tools.py                   # llm.classify, llm.extract, llm.generate
│   │   ├── document_tools.py              # document.parse, document.extract
│   │   ├── transform_tools.py             # transform.map, transform.merge
│   │   ├── export_tools.py                # export.excel
│   │   └── notify_tools.py               # notify.webhook, notify.email
│   └── templates/
│       ├── __init__.py
│       └── requirements_compliance.py     # First workflow template definition
│
├── adapters/                              # NEW: external system adapters
│   ├── __init__.py
│   ├── base.py                            # ALMAdapter ABC, AdapterConfig
│   └── polarion/
│       ├── __init__.py
│       ├── client.py                      # httpx async client for Polarion REST API
│       ├── adapter.py                     # ALMAdapter implementation
│       ├── schema.py                      # Polarion-specific data models
│       └── tools.py                       # Workflow tools that use the adapter
│
├── main.py                                # MODIFY: register router, init scheduler
├── config.py                              # MODIFY: add Polarion + workflow settings

backend/
├── requirements.txt                       # MODIFY: add jinja2, jsonschema, jsonpath-ng
├── alembic/versions/
│   └── 003_add_workflow_tables.py         # NEW: migration

frontend/src/
├── types/index.ts                         # MODIFY: add workflow interfaces
├── api/client.ts                          # MODIFY: add workflow API methods
├── App.tsx                                # MODIFY: add routes
├── stores/
│   └── workflowStore.ts                   # NEW: Zustand store
├── pages/
│   ├── WorkflowsPage.tsx                  # NEW: list/dashboard
│   ├── WorkflowStartPage.tsx              # NEW: dynamic input form
│   └── WorkflowRunPage.tsx                # NEW: run detail + timeline
├── components/
│   ├── layout/Sidebar.tsx                 # MODIFY: add nav item
│   └── workflows/
│       ├── StepTimeline.tsx               # NEW: step progress visualization
│       └── ApprovalPanel.tsx              # NEW: checkpoint approval UI

tests/
├── unit/
│   ├── test_resolver.py
│   ├── test_executor.py
│   └── test_tools/
├── integration/
│   ├── test_workflow_api.py
│   └── test_polarion_adapter.py
└── fixtures/
    ├── sample_requirements.pdf
    └── mock_polarion_schema.json
```

**Totals: 27 new files, 8 modified files**

---

## 4. Database Models

**New file: `backend/app/models/workflow.py`**

All models use existing `UUIDMixin`, `TimestampMixin`, `Base` from `models/base.py`.

### WorkflowDefinition (`workflow_definitions`)

| Column | Type | Notes |
|---|---|---|
| workspace_id | UUID | FK → workspaces.id, CASCADE |
| name | String(255) | |
| slug | String(255) | indexed |
| description | Text | nullable |
| version | Integer | default=1 |
| status | String(20) | "draft" / "published" / "archived" |
| definition_json | JSONB | the workflow schema (see §5) |
| created_by | UUID | FK → users.id |
| is_template | Boolean | default=False |
| required_role | String(20) | minimum role to execute, default="member" |

Relationships: `workspace`, `created_by_user`, `runs`

### WorkflowRun (`workflow_runs`)

| Column | Type | Notes |
|---|---|---|
| workflow_id | UUID | FK → workflow_definitions.id, CASCADE |
| workspace_id | UUID | FK → workspaces.id, CASCADE |
| triggered_by | UUID | FK → users.id |
| status | String(20) | pending/running/paused/waiting_approval/completed/failed/cancelled |
| current_step_index | Integer | default=0 |
| state_json | JSONB | accumulated step outputs (runtime context) |
| input_json | JSONB | initial user-provided inputs |
| output_json | JSONB | nullable, final workflow output |
| error_message | Text | nullable |
| started_at | DateTime(tz) | nullable |
| completed_at | DateTime(tz) | nullable |
| progress_pct | Integer | default=0 |
| definition_snapshot_json | JSONB | frozen copy of definition at run start |

Index on `(workspace_id, status)`. Relationships: `workflow_definition`, `step_results`, `audit_entries`

### WorkflowStepResult (`workflow_step_results`)

| Column | Type | Notes |
|---|---|---|
| run_id | UUID | FK → workflow_runs.id, CASCADE |
| step_id | String(100) | matches step id in definition |
| step_index | Integer | |
| tool_name | String(100) | |
| status | String(20) | pending/running/completed/failed/skipped |
| input_json | JSONB | resolved inputs sent to tool |
| output_json | JSONB | nullable |
| error_message | Text | nullable |
| started_at | DateTime(tz) | nullable |
| completed_at | DateTime(tz) | nullable |
| duration_ms | Integer | nullable |
| retry_count | Integer | default=0 |

Index on `(run_id, step_index)`

### WorkflowApproval (`workflow_approvals`)

| Column | Type | Notes |
|---|---|---|
| run_id | UUID | FK → workflow_runs.id, CASCADE |
| step_id | String(100) | |
| status | String(20) | pending/approved/rejected |
| requested_at | DateTime(tz) | server_default=now() |
| decided_by | UUID | FK → users.id, nullable |
| decided_at | DateTime(tz) | nullable |
| comment | Text | nullable |
| context_json | JSONB | snapshot of state for reviewer |

### WorkflowAuditEntry (`workflow_audit_entries`)

| Column | Type | Notes |
|---|---|---|
| run_id | UUID | FK → workflow_runs.id, CASCADE |
| event_type | String(50) | run_started, step_started, step_completed, step_failed, approval_requested, approval_granted, run_completed, run_failed |
| step_id | String(100) | nullable |
| user_id | UUID | FK → users.id, nullable |
| details_json | JSONB | default=dict |
| timestamp | DateTime(tz) | server_default=now() |

---

## 5. Workflow Definition Schema

Stored in `WorkflowDefinition.definition_json`. This is the format for ALL workflows.

```json
{
  "version": "1.0",
  "inputs": {
    "requirements_pdf": {
      "type": "file",
      "description": "Customer requirements PDF",
      "required": true
    },
    "corpus_workspace_id": {
      "type": "string",
      "description": "Workspace with uploaded corpus",
      "required": true
    },
    "polarion_project_id": {
      "type": "string",
      "description": "Polarion project to import into",
      "required": true
    }
  },
  "outputs": {
    "compliance_report": {
      "type": "file",
      "from": "$steps.generate_matrix.output.file_url"
    }
  },
  "steps": [
    {
      "id": "fetch_schema",
      "name": "Fetch Polarion Schema",
      "tool": "alm.get_schema",
      "inputs": {
        "project_id": "$inputs.polarion_project_id"
      },
      "outputs": ["schema"],
      "timeout_seconds": 30
    },
    {
      "id": "parse_classify",
      "name": "Parse & Classify Requirements",
      "tool": "llm.classify",
      "inputs": {
        "file": "$inputs.requirements_pdf",
        "schema": "$steps.fetch_schema.output.schema",
        "instructions": "Classify each block using the provided ALM schema..."
      },
      "outputs": ["workitems"],
      "timeout_seconds": 600
    },
    {
      "id": "import_to_polarion",
      "name": "Import to Polarion",
      "tool": "alm.create_workitems",
      "inputs": {
        "project_id": "$inputs.polarion_project_id",
        "workitems": "$steps.parse_classify.output.workitems"
      },
      "outputs": ["polarion_ids"],
      "checkpoint": {
        "type": "approval",
        "message": "Review imported requirements in Polarion before compliance check",
        "required_role": "manager",
        "show_data": "$steps.parse_classify.output.workitems"
      },
      "retry": { "max_attempts": 3, "backoff_seconds": 10 }
    },
    {
      "id": "export_from_polarion",
      "name": "Export from Polarion (Source of Truth)",
      "tool": "alm.get_workitems",
      "inputs": {
        "project_id": "$inputs.polarion_project_id",
        "module_id": "$steps.import_to_polarion.output.module_id"
      },
      "outputs": ["canonical_requirements"]
    },
    {
      "id": "compliance_check",
      "name": "Check Compliance via RAG",
      "tool": "rag.batch_query",
      "inputs": {
        "queries": "$steps.export_from_polarion.output.canonical_requirements",
        "workspace_id": "$inputs.corpus_workspace_id",
        "system_prompt": "Determine if this requirement is met by the corpus. Respond with: status (Met/Partially Met/Not Met/Insufficient Evidence), confidence (0-1), evidence (specific excerpts), gaps (what is missing), suggested_action."
      },
      "outputs": ["compliance_results"],
      "loop": {
        "over": "$steps.export_from_polarion.output.canonical_requirements",
        "as": "requirement",
        "batch_size": 5,
        "concurrency": 3
      },
      "timeout_seconds": 1800
    },
    {
      "id": "write_back",
      "name": "Write Compliance Results to Polarion",
      "tool": "alm.update_workitems",
      "inputs": {
        "project_id": "$inputs.polarion_project_id",
        "updates": "$steps.compliance_check.output.compliance_results"
      },
      "outputs": ["updated_count"],
      "retry": { "max_attempts": 3, "backoff_seconds": 10 }
    },
    {
      "id": "generate_matrix",
      "name": "Generate Compliance Matrix",
      "tool": "export.excel",
      "inputs": {
        "requirements": "$steps.export_from_polarion.output.canonical_requirements",
        "compliance": "$steps.compliance_check.output.compliance_results",
        "template": "compliance_matrix",
        "filename": "compliance_report.xlsx"
      },
      "outputs": ["file_url", "file_path"]
    }
  ],
  "error_policy": {
    "default": "fail",
    "on_step_failure": {
      "import_to_polarion": "pause",
      "write_back": "pause"
    }
  }
}
```

### Variable Resolution Syntax

| Pattern | Resolves to |
|---|---|
| `$inputs.field` | Workflow input provided at run start |
| `$steps.<step_id>.output.<field>` | Output from a previous step |
| `$steps.<id>.output.items[*].field` | JSONPath array projection |
| `$item.field` | Current loop iteration item |
| `$context.workspace_id` | System context |
| `$context.user_id` | System context |
| `$context.run_id` | System context |
| `{{expression}}` | Jinja2 template in strings |

---

## 6. Tool Interface

**`backend/app/workflows/tools/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolInput:
    params: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    # context includes: workspace_id, user_id, run_id


@dataclass
class ToolOutput:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata includes: duration_ms, token_usage, prompt_version


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict   # JSON Schema for params
    output_schema: dict  # JSON Schema for data

    @abstractmethod
    async def execute(self, tool_input: ToolInput) -> ToolOutput: ...

    async def validate_input(self, params: dict) -> list[str]:
        """Optional validation, returns list of error messages."""
        return []
```

### Tool Registry

```python
class ToolRegistry:
    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None: ...

    @classmethod
    def get(cls, name: str) -> BaseTool: ...

    @classmethod
    def list_tools(cls) -> list[dict]: ...

    @classmethod
    def has(cls, name: str) -> bool: ...


def register_all_tools() -> None:
    """Called at app startup."""
    # Register each built-in tool + adapter tools
```

### Built-in Tools (13 tools)

| Module | Tools | Wraps |
|---|---|---|
| `rag_tools.py` | `rag.query`, `rag.batch_query`, `rag.ingest` | Existing RAGEngine, DocumentService |
| `llm_tools.py` | `llm.classify`, `llm.extract`, `llm.generate` | Existing LLM factory |
| `document_tools.py` | `document.parse`, `document.extract` | Existing DocumentParser |
| `transform_tools.py` | `transform.map`, `transform.merge` | Pure data manipulation |
| `export_tools.py` | `export.excel` | openpyxl (already in deps) |
| `notify_tools.py` | `notify.webhook`, `notify.email` | httpx / SMTP |
| `polarion/tools.py` | `alm.get_schema`, `alm.create_workitems`, `alm.get_workitems`, `alm.update_workitems`, `alm.create_links` | PolarionAdapter |

---

## 7. Adapter Interface

**`backend/app/adapters/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ALMSchema:
    workitem_types: list[dict]    # [{id, name, fields: [{id, type, enum_values}]}]
    link_roles: list[dict]        # [{id, name, direction}]
    custom_fields: list[dict]     # [{id, name, type, allowed_values}]


@dataclass
class WorkItemCreate:
    type: str
    title: str
    description: str
    fields: dict          # custom field values
    parent_id: str | None = None


@dataclass
class WorkItemResult:
    id: str               # ALM-assigned ID
    external_id: str      # our tracking ID
    url: str              # link to item in ALM UI


@dataclass
class WorkItemUpdate:
    id: str
    fields: dict          # fields to update


@dataclass
class AdapterConfig:
    base_url: str
    auth_token: str

    @classmethod
    async def from_workspace(cls, workspace_id, db):
        # Today: reads from Settings
        # Tomorrow: reads from secrets manager
        ...


class ALMAdapter(ABC):
    @abstractmethod
    async def get_schema(self, project_id: str) -> ALMSchema: ...

    @abstractmethod
    async def create_workitems(
        self, project_id: str, items: list[WorkItemCreate]
    ) -> list[WorkItemResult]: ...

    @abstractmethod
    async def get_workitems(
        self, project_id: str, module_id: str | None = None
    ) -> list[dict]: ...

    @abstractmethod
    async def update_workitems(
        self, project_id: str, updates: list[WorkItemUpdate]
    ) -> int: ...

    @abstractmethod
    async def create_links(
        self, project_id: str, links: list[dict]
    ) -> None: ...
```

### Polarion Implementation

**`backend/app/adapters/polarion/client.py`** — async httpx client with connection pooling, auth headers, error handling, retry logic.

**`backend/app/adapters/polarion/adapter.py`** — implements `ALMAdapter` using the client. Maps between generic `WorkItemCreate`/`ALMSchema` and Polarion's specific REST API format.

**`backend/app/adapters/polarion/schema.py`** — Polarion-specific Pydantic models for API request/response shapes.

**`backend/app/adapters/polarion/tools.py`** — workflow tools (`alm.get_schema`, `alm.create_workitems`, etc.) that instantiate the adapter and delegate.

---

## 8. Execution Engine

### Variable Resolver (`engine/resolver.py`)

```python
class VariableResolver:
    def __init__(self, state: dict, inputs: dict, context: dict):
        self._state = state      # {"step_id": {"output": {...}}}
        self._inputs = inputs
        self._context = context
        self._loop_vars = {}

    def resolve(self, value: Any) -> Any:
        """Recursively resolve all $-references and {{templates}} in a value."""
        ...

    def set_loop_var(self, name: str, value: Any) -> None: ...
    def clear_loop_vars(self) -> None: ...
```

### Workflow Executor (`engine/executor.py`)

```python
class WorkflowExecutor:
    def __init__(self, db: AsyncSession, run: WorkflowRun):
        self.db = db
        self.run = run
        self._definition = run.definition_snapshot_json
        self._state = run.state_json or {}
        self._resolver = VariableResolver(self._state, run.input_json, {...})

    async def execute(self) -> None:
        """Execute from current_step_index to completion. Resumes after checkpoints."""
        steps = self._definition["steps"]
        for i in range(self.run.current_step_index, len(steps)):
            step = steps[i]

            # Checkpoint gate
            if "checkpoint" in step:
                await self._handle_checkpoint(step, i)
                if self.run.status == "waiting_approval":
                    return  # paused

            # Execute step (with loop/retry support)
            await self._execute_step(step, i)
            if self.run.status == "failed":
                return

            # Progress
            self.run.current_step_index = i + 1
            self.run.progress_pct = int(((i + 1) / len(steps)) * 100)
            await self._save_state()

        self.run.status = "completed"
        self.run.completed_at = utcnow()
        self.run.output_json = self._resolve_outputs()
        await self._save_state()

    async def _execute_step(self, step_def, index): ...
    async def _execute_loop(self, step_def, index, tool): ...
    async def _handle_checkpoint(self, step_def, index): ...
    async def _handle_step_failure(self, step_def, error): ...
    async def _save_state(self): ...
    async def _audit(self, event_type, step_id=None, details_json=None): ...
```

### Workflow Scheduler (`engine/scheduler.py`)

Uses Redis `blpop` as a lightweight job queue. No Celery dependency.

```python
class WorkflowScheduler:
    QUEUE_KEY = "workflow:job_queue"

    def __init__(self, redis_client, session_factory):
        self._redis = redis_client
        self._session_factory = session_factory

    async def enqueue(self, run_id: uuid.UUID) -> None:
        await self._redis.rpush(self.QUEUE_KEY, str(run_id))

    async def resume(self, run_id: uuid.UUID) -> None:
        await self._redis.rpush(self.QUEUE_KEY, str(run_id))

    async def start_worker(self) -> None:
        """Background loop — called from app lifespan."""
        while True:
            job = await self._redis.blpop(self.QUEUE_KEY, timeout=5)
            if job:
                run_id = uuid.UUID(job[1].decode())
                asyncio.create_task(self._process(run_id))

    async def _process(self, run_id): ...
```

---

## 9. Service Layer

**`backend/app/services/workflow_service.py`**

```python
class WorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Definitions ---
    async def create_definition(self, workspace_id, name, definition_json, created_by) -> WorkflowDefinition: ...
    async def update_definition(self, workflow_id, **kwargs) -> WorkflowDefinition: ...
    async def list_definitions(self, workspace_id, status=None) -> list[WorkflowDefinition]: ...
    async def get_definition(self, workflow_id) -> WorkflowDefinition: ...
    async def publish_definition(self, workflow_id) -> WorkflowDefinition: ...
    async def validate_definition(self, definition_json: dict) -> list[str]:
        """Check tool refs exist, variable refs point to earlier steps, schema valid."""
        ...

    # --- Runs ---
    async def start_run(self, workflow_id, workspace_id, triggered_by, input_json) -> WorkflowRun:
        """Create run, snapshot definition, return for enqueueing."""
        ...
    async def get_run(self, run_id) -> WorkflowRun: ...
    async def list_runs(self, workspace_id, workflow_id=None, status=None) -> list[WorkflowRun]: ...
    async def cancel_run(self, run_id) -> WorkflowRun: ...
    async def get_run_steps(self, run_id) -> list[WorkflowStepResult]: ...
    async def get_run_progress(self, run_id) -> dict: ...

    # --- Approvals ---
    async def submit_approval(self, approval_id, user_id, approved, comment=None) -> WorkflowApproval: ...
    async def list_pending_approvals(self, workspace_id) -> list[WorkflowApproval]: ...

    # --- Audit ---
    async def get_audit_trail(self, run_id) -> list[WorkflowAuditEntry]: ...
```

---

## 10. API Endpoints

**`backend/app/api/routes/workflows.py`** — all under `/api/workflows/`

### Definitions

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/definitions` | manager | Create workflow definition |
| GET | `/definitions` | member | List definitions for workspace |
| GET | `/definitions/{id}` | member | Get definition detail |
| PATCH | `/definitions/{id}` | manager | Update definition |
| POST | `/definitions/{id}/publish` | manager | Publish draft → published |
| POST | `/definitions/validate` | member | Validate without saving |

### Runs

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/runs` | per required_role | Start a new run |
| GET | `/runs` | member | List runs for workspace |
| GET | `/runs/{id}` | member | Get run detail |
| GET | `/runs/{id}/progress` | member | Lightweight polling endpoint |
| GET | `/runs/{id}/steps` | member | Get step results |
| POST | `/runs/{id}/cancel` | manager or trigger user | Cancel a run |
| GET | `/runs/{id}/audit` | manager | Get audit trail |
| WS | `/runs/{id}/ws` | member | Real-time progress (Phase 5) |

### Approvals

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/approvals/pending` | manager | List pending approvals |
| POST | `/approvals/{id}/decide` | manager | Approve or reject |

### Tools

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/tools` | member | List registered tools + schemas |

---

## 11. Configuration Changes

**`backend/app/config.py`** — add to Settings:

```python
# Polarion
polarion_base_url: str | None = None
polarion_api_token: str | None = None
polarion_default_project_id: str | None = None

# Workflow Engine
enable_workflow_worker: bool = True      # False for API-only containers
workflow_max_concurrent_runs: int = 10
workflow_default_timeout_seconds: int = 3600
workflow_step_default_timeout_seconds: int = 300
```

**`backend/requirements.txt`** — add:

```
jinja2==3.1.4
jsonschema==4.23.0
jsonpath-ng==1.7.0
```

**`backend/app/main.py`** — add to lifespan:

```python
from app.workflows.tools.registry import register_all_tools
register_all_tools()

if settings.enable_workflow_worker:
    from app.workflows.engine.scheduler import WorkflowScheduler
    scheduler = WorkflowScheduler(redis_client, session_factory)
    asyncio.create_task(scheduler.start_worker())
```

Add router:
```python
from app.api.routes import workflows
app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])
```

---

## 12. Frontend Changes

### New Types (`types/index.ts`)

```typescript
interface WorkflowDefinition {
  id: string; workspace_id: string; name: string; slug: string;
  description: string | null; version: number;
  status: 'draft' | 'published' | 'archived';
  definition_json: WorkflowSchema; is_template: boolean;
  created_at: string;
}

interface WorkflowSchema {
  version: string;
  inputs: Record<string, { type: string; description: string; required: boolean }>;
  outputs: Record<string, { type: string; from: string }>;
  steps: WorkflowStep[];
}

interface WorkflowStep {
  id: string; name: string; tool: string;
  inputs: Record<string, any>; outputs: string[];
  checkpoint?: { type: string; message: string; required_role: string };
  loop?: { over: string; as: string; batch_size?: number };
  retry?: { max_attempts: number; backoff_seconds: number };
}

interface WorkflowRun {
  id: string; workflow_id: string; workspace_id: string;
  status: 'pending'|'running'|'paused'|'waiting_approval'|'completed'|'failed'|'cancelled';
  current_step_index: number; progress_pct: number;
  input_json: Record<string, any>;
  output_json: Record<string, any> | null;
  error_message: string | null;
  started_at: string | null; completed_at: string | null; created_at: string;
}

interface WorkflowStepResult {
  id: string; step_id: string; step_index: number; tool_name: string;
  status: string; duration_ms: number | null; error_message: string | null;
}

interface WorkflowApproval {
  id: string; run_id: string; step_id: string;
  status: 'pending' | 'approved' | 'rejected';
  context_json: Record<string, any>; requested_at: string;
}
```

### New Pages

- **WorkflowsPage** — 3 tabs: Templates/Definitions, Active Runs, History
- **WorkflowStartPage** — dynamic form generated from `definition_json.inputs`
- **WorkflowRunPage** — step timeline, approval panel, output downloads, audit trail

### New Components

- **StepTimeline** — vertical timeline with status icons per step
- **ApprovalPanel** — context display, approve/reject buttons, comment field

### New Store (`stores/workflowStore.ts`)

Zustand store with: definitions[], activeRun, runs[], pendingApprovals[], and actions for fetch/start/cancel/approve.

### Routing + Nav

Routes: `/workflows`, `/workflows/:id/start`, `/workflows/runs/:runId`
Sidebar: "Workflows" nav item with pending approval badge.

---

## 13. Implementation Phases

### Phase 1 — Foundation (Week 1)

1. `models/workflow.py` — all 5 models
2. `models/__init__.py` — add imports
3. Alembic migration `003_add_workflow_tables.py`
4. `workflows/tools/base.py` — BaseTool, ToolInput, ToolOutput
5. `workflows/tools/registry.py` — ToolRegistry
6. `workflows/engine/resolver.py` — VariableResolver
7. `adapters/base.py` — ALMAdapter, AdapterConfig, data classes
8. Unit tests for resolver

### Phase 2 — Engine + Tools (Week 2)

1. `workflows/engine/executor.py` — WorkflowExecutor
2. `workflows/engine/scheduler.py` — WorkflowScheduler
3. `workflows/tools/document_tools.py`
4. `workflows/tools/llm_tools.py`
5. `workflows/tools/rag_tools.py`
6. `workflows/tools/transform_tools.py`
7. `workflows/tools/export_tools.py`
8. `adapters/polarion/client.py` — async HTTP client
9. `adapters/polarion/adapter.py` — ALMAdapter impl
10. `adapters/polarion/schema.py` — Polarion models
11. Unit test executor with mock 2-step workflow

### Phase 3 — API + First Workflow (Week 3)

1. `services/workflow_service.py`
2. `api/routes/workflows.py` — all endpoints
3. `adapters/polarion/tools.py` — ALM workflow tools
4. `workflows/tools/notify_tools.py`
5. `workflows/templates/requirements_compliance.py`
6. Modify `main.py` — router, lifespan init
7. Modify `config.py` — new settings
8. Modify `requirements.txt` — new deps
9. End-to-end test: start compliance workflow via API

### Phase 4 — Frontend (Week 4)

1. `types/index.ts` — add interfaces
2. `api/client.ts` — add methods
3. `stores/workflowStore.ts`
4. `pages/WorkflowsPage.tsx`
5. `pages/WorkflowStartPage.tsx`
6. `pages/WorkflowRunPage.tsx`
7. `components/workflows/StepTimeline.tsx`
8. `components/workflows/ApprovalPanel.tsx`
9. `App.tsx` — add routes
10. `Sidebar.tsx` — add nav item + badge

### Phase 5 — Polish (Week 5)

1. WebSocket progress updates (Redis pub/sub → WS)
2. Workflow definition validation (tool refs, variable refs, schema)
3. RBAC enforcement on all endpoints
4. Error handling edge cases
5. Audit trail UI tab
6. Testing with real Polarion instance
7. Observability: structured logging on tool exec + state transitions

---

## 14. What NOT To Build Now

| Skip | Reason |
|---|---|
| K8s / Helm charts | Docker Compose is fine until deployment target exists |
| Custom RBAC beyond existing roles | admin/manager/member/viewer is sufficient |
| Workflow version migration | Snapshot on run is enough |
| Multi-region | Solve when customer needs it |
| Third-party plugin SDK | BaseTool interface IS the SDK, document later |
| Celery | Redis blpop queue is sufficient, upgradeable later |

---

## 15. Key Design Decisions Summary

| Decision | Rationale |
|---|---|
| Redis blpop queue, not Celery | Avoids new infra dep; already have Redis; upgradeable |
| Definition snapshot on run start | Editing workflows doesn't break in-flight runs |
| Tools are stateless | Everything via ToolInput; independently testable |
| Adapter pattern for ALM | Polarion today, DOORS/Jama tomorrow, zero engine changes |
| Schema-driven classification | LLM targets = Polarion's actual types/fields, self-adapting |
| Loops + batching first-class | "For each requirement, query RAG" is the core pattern |
| Approval gates block execution | Executor returns, scheduler resumes on approval |
| Audit trail separate from step results | Every state transition logged for compliance |
| enable_workflow_worker flag | Same codebase, split API vs worker at deploy time |
| Secrets via AdapterConfig | Today: settings. Tomorrow: secrets manager. No code change. |
