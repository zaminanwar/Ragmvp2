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
