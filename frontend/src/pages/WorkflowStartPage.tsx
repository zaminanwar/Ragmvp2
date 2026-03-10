import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Play, ArrowLeft, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import { useWorkflowStore } from '../stores/workflowStore';
import { useWorkspaceStore } from '../stores/workspaceStore';
import type { WorkflowDefinition } from '../types';

export default function WorkflowStartPage() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const navigate = useNavigate();
  const { activeWorkspace } = useWorkspaceStore();
  const { startRun } = useWorkflowStore();
  const [definition, setDefinition] = useState<WorkflowDefinition | null>(null);
  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (workflowId) {
      api.getWorkflowDefinition(workflowId).then(setDefinition).catch(() => {});
    }
  }, [workflowId]);

  if (!definition || !activeWorkspace) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
      </div>
    );
  }

  const schema = definition.definition_json;
  const inputDefs = schema?.inputs || {};

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const run = await startRun(definition.id, activeWorkspace.id, inputs);
      navigate(`/workflows/runs/${run.id}`);
    } catch (err: any) {
      setError(err.message);
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6">
      <button onClick={() => navigate('/workflows')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-white mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Workflows
      </button>

      <h1 className="text-2xl font-bold mb-2">{definition.name}</h1>
      {definition.description && <p className="text-gray-400 mb-6">{definition.description}</p>}

      <div className="card p-6">
        <h2 className="text-lg font-medium mb-4">Workflow Inputs</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {Object.entries(inputDefs).filter(([key]) => !key.endsWith('_filename')).map(([key, spec]) => (
            <div key={key}>
              <label className="block text-sm text-gray-300 mb-1">
                {spec.description || key}
                {spec.required && <span className="text-red-400 ml-1">*</span>}
              </label>
              {spec.type === 'file' ? (
                <input
                  type="file"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      const reader = new FileReader();
                      reader.onload = () => {
                        const base64 = (reader.result as string).split(',')[1];
                        setInputs({ ...inputs, [key]: base64, [`${key}_filename`]: file.name });
                      };
                      reader.readAsDataURL(file);
                    }
                  }}
                  className="input-field text-sm"
                />
              ) : (
                <input
                  type="text"
                  value={inputs[key] || ''}
                  onChange={(e) => setInputs({ ...inputs, [key]: e.target.value })}
                  placeholder={spec.description}
                  className="input-field text-sm"
                  required={spec.required}
                />
              )}
            </div>
          ))}

          {error && (
            <div className="text-sm text-red-400 bg-red-400/5 rounded p-3">{error}</div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {isSubmitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Starting...</>
            ) : (
              <><Play className="w-4 h-4" /> Start Workflow</>
            )}
          </button>
        </form>
      </div>

      {/* Steps preview */}
      <div className="mt-6">
        <h3 className="text-sm text-gray-500 mb-3">Steps ({schema.steps?.length || 0})</h3>
        <div className="space-y-2">
          {schema.steps?.map((step, i) => (
            <div key={step.id} className="flex items-center gap-3 text-sm">
              <span className="w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-gray-500">
                {i + 1}
              </span>
              <span className="text-gray-300">{step.name}</span>
              <span className="text-xs text-gray-600 font-mono">{step.tool}</span>
              {step.checkpoint && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-400/10 text-yellow-400">checkpoint</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
