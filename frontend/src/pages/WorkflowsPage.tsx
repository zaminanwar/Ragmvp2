import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Play, Clock, CheckCircle, XCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { useWorkflowStore } from '../stores/workflowStore';
import { useWorkspaceStore } from '../stores/workspaceStore';
import type { WorkflowRunStatus } from '../types';
import { formatDistanceToNow } from 'date-fns';

const statusBadge: Record<WorkflowRunStatus, { color: string; icon: typeof CheckCircle }> = {
  pending: { color: 'text-gray-400 bg-gray-400/10', icon: Clock },
  running: { color: 'text-blue-400 bg-blue-400/10', icon: Loader2 },
  paused: { color: 'text-yellow-400 bg-yellow-400/10', icon: AlertTriangle },
  waiting_approval: { color: 'text-yellow-400 bg-yellow-400/10', icon: AlertTriangle },
  completed: { color: 'text-green-400 bg-green-400/10', icon: CheckCircle },
  failed: { color: 'text-red-400 bg-red-400/10', icon: XCircle },
  cancelled: { color: 'text-gray-500 bg-gray-500/10', icon: XCircle },
};

type Tab = 'definitions' | 'active' | 'history';

export default function WorkflowsPage() {
  const [tab, setTab] = useState<Tab>('definitions');
  const { activeWorkspace } = useWorkspaceStore();
  const { definitions, runs, pendingApprovals, isLoading, fetchDefinitions, fetchRuns, fetchPendingApprovals } = useWorkflowStore();

  useEffect(() => {
    if (activeWorkspace) {
      fetchDefinitions(activeWorkspace.id);
      fetchRuns(activeWorkspace.id);
      fetchPendingApprovals(activeWorkspace.id);
    }
  }, [activeWorkspace, fetchDefinitions, fetchRuns, fetchPendingApprovals]);

  const activeRuns = runs.filter((r) => ['pending', 'running', 'paused', 'waiting_approval'].includes(r.status));
  const historyRuns = runs.filter((r) => ['completed', 'failed', 'cancelled'].includes(r.status));

  if (!activeWorkspace) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Select a workspace to view workflows
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Workflows</h1>
        {pendingApprovals.length > 0 && (
          <span className="px-3 py-1 rounded-full bg-yellow-400/10 text-yellow-400 text-sm">
            {pendingApprovals.length} pending approval{pendingApprovals.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1">
        {([
          ['definitions', 'Templates'],
          ['active', `Active (${activeRuns.length})`],
          ['history', 'History'],
        ] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex-1 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === key ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-gray-500">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
        </div>
      ) : (
        <>
          {/* Definitions / Templates */}
          {tab === 'definitions' && (
            <div className="space-y-3">
              {definitions.length === 0 ? (
                <p className="text-gray-500 text-center py-12">No workflow definitions yet.</p>
              ) : (
                definitions.map((def) => (
                  <div key={def.id} className="card p-4 flex items-center justify-between">
                    <div>
                      <h3 className="font-medium">{def.name}</h3>
                      <p className="text-sm text-gray-500 mt-1">{def.description || 'No description'}</p>
                      <div className="flex gap-2 mt-2">
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400">
                          v{def.version}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          def.status === 'published' ? 'bg-green-400/10 text-green-400' :
                          def.status === 'draft' ? 'bg-gray-800 text-gray-400' :
                          'bg-gray-800 text-gray-500'
                        }`}>
                          {def.status}
                        </span>
                        <span className="text-xs text-gray-600">
                          {def.definition_json?.steps?.length || 0} steps
                        </span>
                      </div>
                    </div>
                    {def.status === 'published' && (
                      <Link
                        to={`/workflows/${def.id}/start`}
                        className="btn-primary flex items-center gap-1.5 text-sm"
                      >
                        <Play className="w-4 h-4" /> Run
                      </Link>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Active Runs */}
          {tab === 'active' && (
            <div className="space-y-3">
              {activeRuns.length === 0 ? (
                <p className="text-gray-500 text-center py-12">No active runs.</p>
              ) : (
                activeRuns.map((run) => <RunCard key={run.id} run={run} definitions={definitions} />)
              )}
            </div>
          )}

          {/* History */}
          {tab === 'history' && (
            <div className="space-y-3">
              {historyRuns.length === 0 ? (
                <p className="text-gray-500 text-center py-12">No completed runs yet.</p>
              ) : (
                historyRuns.map((run) => <RunCard key={run.id} run={run} definitions={definitions} />)
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RunCard({ run, definitions }: { run: any; definitions: any[] }) {
  const def = definitions.find((d: any) => d.id === run.workflow_id);
  const badge = statusBadge[run.status as WorkflowRunStatus] || statusBadge.pending;
  const Icon = badge.icon;

  return (
    <Link to={`/workflows/runs/${run.id}`} className="card p-4 block hover:bg-gray-800/50 transition-colors">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">{def?.name || 'Unknown Workflow'}</h3>
          <p className="text-xs text-gray-500 mt-1">
            Started {run.created_at ? formatDistanceToNow(new Date(run.created_at), { addSuffix: true }) : 'unknown'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {run.status === 'running' && (
            <div className="w-24 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: `${run.progress_pct}%` }} />
            </div>
          )}
          <span className={`flex items-center gap-1 text-xs px-2 py-1 rounded ${badge.color}`}>
            <Icon className={`w-3 h-3 ${run.status === 'running' ? 'animate-spin' : ''}`} />
            {run.status.replace('_', ' ')}
          </span>
        </div>
      </div>
      {run.error_message && (
        <p className="text-xs text-red-400 mt-2 truncate">{run.error_message}</p>
      )}
    </Link>
  );
}
