export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: string;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  temperature: number;
  similarity_top_k: number;
  enable_hybrid_search: boolean;
  enable_reranking: boolean;
  enable_adaptive_routing: boolean;
  enable_self_reflection: boolean;
  enable_hyde: boolean;
  enable_query_decomposition: boolean;
  enable_contextual_embeddings: boolean;
  enable_knowledge_graph: boolean;
  enable_semantic_cache: boolean;
  chunk_strategy: string;
}

export interface Document {
  id: string;
  workspace_id: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  status: string;
  chunk_count: number;
  created_at: string;
  error_message: string | null;
}

export interface Citation {
  chunk_id: string;
  excerpt: string;
  relevance_score: number;
  position: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  model_used?: string;
  was_corrective_rag?: boolean;
  citations?: Citation[];
  created_at: string;
}

export interface Conversation {
  id: string;
  workspace_id: string;
  title: string;
  created_at: string;
}

export interface LLMProvider {
  id: string;
  name: string;
  models: string[];
  embedding_models: string[];
  status?: string;
}

// ── Workflow Types ──────────────────────────────────────────────────────

export interface WorkflowDefinition {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  version: number;
  status: 'draft' | 'published' | 'archived';
  definition_json: WorkflowSchema;
  is_template: boolean;
  required_role: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowSchema {
  version: string;
  inputs: Record<string, { type: string; description: string; required: boolean }>;
  outputs: Record<string, { type: string; from: string }>;
  steps: WorkflowStep[];
}

export interface WorkflowStep {
  id: string;
  name: string;
  tool: string;
  inputs: Record<string, any>;
  outputs: string[];
  checkpoint?: { type: string; message: string; required_role: string };
  loop?: { over: string; as: string; batch_size?: number };
  retry?: { max_attempts: number; backoff_seconds: number };
  timeout_seconds?: number;
}

export type WorkflowRunStatus =
  | 'pending' | 'running' | 'paused' | 'waiting_approval'
  | 'completed' | 'failed' | 'cancelled';

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  workspace_id: string;
  triggered_by: string;
  status: WorkflowRunStatus;
  current_step_index: number;
  progress_pct: number;
  input_json: Record<string, any>;
  output_json: Record<string, any> | null;
  error_message: string | null;
  parent_run_id: string | null;
  overrides_json: Record<string, any> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface WorkflowStepResult {
  id: string;
  step_id: string;
  step_index: number;
  tool_name: string;
  status: string;
  input_json: Record<string, any>;
  output_json: Record<string, any> | null;
  error_message: string | null;
  duration_ms: number | null;
  retry_count: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkflowApproval {
  id: string;
  run_id: string;
  step_id: string;
  status: 'pending' | 'approved' | 'rejected';
  context_json: Record<string, any>;
  requested_at: string;
}

export interface WorkflowTool {
  name: string;
  description: string;
  input_schema: Record<string, any>;
  output_schema: Record<string, any>;
}
