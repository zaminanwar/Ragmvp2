import { useState, useEffect } from 'react';
import { Plus, Settings, Folders } from 'lucide-react';
import { useWorkspaceStore } from '../stores/workspaceStore';

const FEATURE_TOGGLES = [
  { key: 'enable_hybrid_search', label: 'Hybrid Search', desc: 'Vector + BM25 full-text search' },
  { key: 'enable_reranking', label: 'Reranking', desc: 'Re-score results for better relevance' },
  { key: 'enable_adaptive_routing', label: 'Adaptive Routing', desc: 'Auto-select best search strategy' },
  { key: 'enable_self_reflection', label: 'Self-Reflection', desc: 'Hallucination check & regeneration' },
  { key: 'enable_hyde', label: 'HyDE', desc: 'Hypothetical Document Embeddings' },
  { key: 'enable_query_decomposition', label: 'Query Decomposition', desc: 'Break complex questions into sub-queries' },
  { key: 'enable_contextual_embeddings', label: 'Contextual Embeddings', desc: 'Add document context to chunk embeddings' },
  { key: 'enable_knowledge_graph', label: 'Knowledge Graph', desc: 'Entity & relationship extraction' },
  { key: 'enable_semantic_cache', label: 'Semantic Cache', desc: 'Cache similar queries for faster responses' },
] as const;

const CHUNK_STRATEGIES = [
  { value: 'recursive', label: 'Recursive' },
  { value: 'semantic', label: 'Semantic' },
  { value: 'hierarchical', label: 'Hierarchical' },
];

const BADGE_COLORS: Record<string, string> = {
  enable_hybrid_search: 'bg-green-900/30 text-green-400',
  enable_reranking: 'bg-blue-900/30 text-blue-400',
  enable_adaptive_routing: 'bg-purple-900/30 text-purple-400',
  enable_self_reflection: 'bg-amber-900/30 text-amber-400',
  enable_hyde: 'bg-cyan-900/30 text-cyan-400',
  enable_query_decomposition: 'bg-rose-900/30 text-rose-400',
  enable_contextual_embeddings: 'bg-teal-900/30 text-teal-400',
  enable_knowledge_graph: 'bg-orange-900/30 text-orange-400',
  enable_semantic_cache: 'bg-indigo-900/30 text-indigo-400',
};

export default function WorkspacesPage() {
  const { workspaces, activeWorkspace, setActiveWorkspace, fetchWorkspaces, createWorkspace } =
    useWorkspaceStore();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [creating, setCreating] = useState(false);
  const [chunkStrategy, setChunkStrategy] = useState('recursive');
  const [features, setFeatures] = useState<Record<string, boolean>>({
    enable_hybrid_search: true,
    enable_reranking: true,
    enable_adaptive_routing: true,
    enable_self_reflection: true,
    enable_hyde: false,
    enable_query_decomposition: false,
    enable_contextual_embeddings: false,
    enable_knowledge_graph: false,
    enable_semantic_cache: false,
  });

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const toggleFeature = (key: string) => {
    setFeatures((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await createWorkspace({
        name: name.trim(),
        description: description.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
        chunk_strategy: chunkStrategy,
        ...features,
      } as any);
      setName('');
      setDescription('');
      setSystemPrompt('');
      setChunkStrategy('recursive');
      setFeatures({
        enable_hybrid_search: true,
        enable_reranking: true,
        enable_adaptive_routing: true,
        enable_self_reflection: true,
        enable_hyde: false,
        enable_query_decomposition: false,
        enable_contextual_embeddings: false,
        enable_knowledge_graph: false,
        enable_semantic_cache: false,
      });
      setShowCreate(false);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Workspaces</h1>
          <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-2">
            <Plus className="w-4 h-4" /> New Workspace
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <form onSubmit={handleCreate} className="card mb-6 space-y-4">
            <h2 className="text-lg font-semibold">Create Workspace</h2>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} className="input-field" required />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Description</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} className="input-field" rows={2} />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">System Prompt (optional)</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                className="input-field"
                rows={3}
                placeholder="Custom instructions for the AI assistant in this workspace..."
              />
            </div>

            {/* Chunk Strategy */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">Chunk Strategy</label>
              <select
                value={chunkStrategy}
                onChange={(e) => setChunkStrategy(e.target.value)}
                className="input-field"
              >
                {CHUNK_STRATEGIES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>

            {/* Feature Toggles */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">RAG Pipeline Features</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {FEATURE_TOGGLES.map(({ key, label, desc }) => (
                  <label
                    key={key}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      features[key]
                        ? 'border-primary-500 bg-primary-500/10'
                        : 'border-gray-700 hover:border-gray-600'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={features[key]}
                      onChange={() => toggleFeature(key)}
                      className="mt-0.5 accent-primary-500"
                    />
                    <div>
                      <div className="text-sm font-medium">{label}</div>
                      <div className="text-xs text-gray-500">{desc}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <button type="submit" disabled={creating} className="btn-primary">
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="btn-secondary">
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Workspace Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`card cursor-pointer transition-colors ${
                ws.id === activeWorkspace?.id
                  ? 'border-primary-500 bg-primary-500/10'
                  : 'hover:border-gray-600'
              }`}
              onClick={() => setActiveWorkspace(ws)}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <Folders className="w-8 h-8 text-primary-400" />
                  <div>
                    <h3 className="font-semibold">{ws.name}</h3>
                    {ws.description && (
                      <p className="text-sm text-gray-500 mt-1">{ws.description}</p>
                    )}
                  </div>
                </div>
                <Settings className="w-4 h-4 text-gray-500" />
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                <span className="bg-gray-700 px-2 py-0.5 rounded">{ws.llm_model || 'Default Model'}</span>
                {ws.chunk_strategy && ws.chunk_strategy !== 'recursive' && (
                  <span className="bg-gray-700 px-2 py-0.5 rounded">{ws.chunk_strategy} chunks</span>
                )}
                {FEATURE_TOGGLES.map(({ key, label }) =>
                  (ws as any)[key] ? (
                    <span key={key} className={`px-2 py-0.5 rounded ${BADGE_COLORS[key] || 'bg-gray-700'}`}>
                      {label}
                    </span>
                  ) : null
                )}
              </div>
            </div>
          ))}
        </div>

        {workspaces.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <Folders className="w-16 h-16 mx-auto mb-4 opacity-50" />
            <p className="text-lg">No workspaces yet</p>
            <p className="text-sm mt-2">Create one to start organizing your documents</p>
          </div>
        )}
      </div>
    </div>
  );
}
