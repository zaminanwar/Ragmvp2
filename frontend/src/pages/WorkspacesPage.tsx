import { useState, useEffect } from 'react';
import { Plus, Settings, Folders } from 'lucide-react';
import { useWorkspaceStore } from '../stores/workspaceStore';

export default function WorkspacesPage() {
  const { workspaces, activeWorkspace, setActiveWorkspace, fetchWorkspaces, createWorkspace } =
    useWorkspaceStore();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await createWorkspace({
        name: name.trim(),
        description: description.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
      } as any);
      setName('');
      setDescription('');
      setSystemPrompt('');
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
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="bg-gray-700 px-2 py-0.5 rounded">{ws.llm_model || 'Default Model'}</span>
                {ws.enable_hybrid_search && (
                  <span className="bg-green-900/30 text-green-400 px-2 py-0.5 rounded">Hybrid Search</span>
                )}
                {ws.enable_reranking && (
                  <span className="bg-blue-900/30 text-blue-400 px-2 py-0.5 rounded">Reranking</span>
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
