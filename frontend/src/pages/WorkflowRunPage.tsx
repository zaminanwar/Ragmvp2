import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, XCircle, Download, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import { useWorkflowStore } from '../stores/workflowStore';
import StepTimeline from '../components/workflows/StepTimeline';
import ApprovalPanel from '../components/workflows/ApprovalPanel';
import type { WorkflowRun, WorkflowStepResult, WorkflowApproval, WorkflowStep } from '../types';
import { formatDistanceToNow } from 'date-fns';

export default function WorkflowRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { cancelRun, rerunFromStep, decideApproval } = useWorkflowStore();

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [steps, setSteps] = useState<WorkflowStepResult[]>([]);
  const [approvals, setApprovals] = useState<WorkflowApproval[]>([]);
  const [tab, setTab] = useState<'timeline' | 'output' | 'audit'>('timeline');
  const [auditTrail, setAuditTrail] = useState<any[]>([]);

  const fetchData = async () => {
    if (!runId) return;
    try {
      const [runData, stepsData] = await Promise.all([
        api.getWorkflowRun(runId),
        api.getWorkflowRunSteps(runId),
      ]);
      setRun(runData);
      setSteps(stepsData);

      if (runData.status === 'waiting_approval' && runData.workspace_id) {
        const pendingApprovals = await api.listPendingApprovals(runData.workspace_id);
        setApprovals(pendingApprovals.filter((a: any) => a.run_id === runId));
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchData();
    // Poll while running
    const isActive = run?.status && ['pending', 'running', 'waiting_approval'].includes(run.status);
    if (isActive) {
      const interval = setInterval(fetchData, 3000);
      return () => clearInterval(interval);
    }
  }, [runId, run?.status]);

  const handleRerun = async (stepId: string) => {
    if (!runId) return;
    try {
      const newRun = await rerunFromStep(runId, stepId);
      navigate(`/workflows/runs/${newRun.id}`);
    } catch { /* ignore */ }
  };

  const handleApproval = async (approvalId: string, approved: boolean, comment?: string) => {
    await decideApproval(approvalId, approved, comment);
    await fetchData();
  };

  const handleCancel = async () => {
    if (!runId) return;
    await cancelRun(runId);
    await fetchData();
  };

  if (!run) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
      </div>
    );
  }

  const definition = run.output_json ? null : null; // definition is in snapshot
  const snapshot = (run as any).definition_snapshot_json || {};
  const workflowSteps: WorkflowStep[] = snapshot.steps || [];
  const isActive = ['pending', 'running', 'waiting_approval'].includes(run.status);

  const statusColor: Record<string, string> = {
    pending: 'text-gray-400',
    running: 'text-blue-400',
    paused: 'text-yellow-400',
    waiting_approval: 'text-yellow-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
    cancelled: 'text-gray-500',
  };

  return (
    <div className="max-w-3xl mx-auto p-6">
      <button onClick={() => navigate('/workflows')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-white mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Workflows
      </button>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold">Workflow Run</h1>
          <p className="text-xs text-gray-500 font-mono mt-1">{run.id}</p>
          {run.parent_run_id && (
            <p className="text-xs text-gray-500 mt-0.5">
              Re-run from{' '}
              <button onClick={() => navigate(`/workflows/runs/${run.parent_run_id}`)} className="text-primary-400 hover:underline">
                {run.parent_run_id.slice(0, 8)}...
              </button>
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-sm font-medium ${statusColor[run.status] || 'text-gray-400'}`}>
            {run.status.replace('_', ' ')}
          </span>
          {isActive && (
            <button onClick={handleCancel} className="text-sm text-red-400 hover:text-red-300 flex items-center gap-1">
              <XCircle className="w-4 h-4" /> Cancel
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {run.status === 'running' && (
        <div className="mb-6">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Progress</span>
            <span>{run.progress_pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${run.progress_pct}%` }} />
          </div>
        </div>
      )}

      {/* Approval panels */}
      {approvals.length > 0 && (
        <div className="mb-6 space-y-3">
          {approvals.map((a) => (
            <ApprovalPanel key={a.id} approval={a} onDecide={handleApproval} />
          ))}
        </div>
      )}

      {/* Error */}
      {run.error_message && (
        <div className="mb-6 p-3 rounded-lg bg-red-400/5 border border-red-500/20 text-sm text-red-400">
          {run.error_message}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-gray-900 rounded-lg p-1">
        {(['timeline', 'output', 'audit'] as const).map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t);
              if (t === 'audit' && auditTrail.length === 0 && runId) {
                api.getWorkflowAuditTrail(runId).then(setAuditTrail).catch(() => {});
              }
            }}
            className={`flex-1 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === t ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'timeline' && (
        <StepTimeline
          steps={workflowSteps}
          stepResults={steps}
          currentStepIndex={run.current_step_index}
          onRerunFromStep={handleRerun}
        />
      )}

      {tab === 'output' && (
        <div className="card p-4">
          {run.output_json ? (
            <>
              <pre className="text-sm text-gray-300 overflow-x-auto">
                {JSON.stringify(run.output_json, null, 2)}
              </pre>
              {run.output_json.compliance_report && (
                <a
                  href={run.output_json.compliance_report}
                  className="mt-3 inline-flex items-center gap-1.5 btn-primary text-sm"
                >
                  <Download className="w-4 h-4" /> Download Report
                </a>
              )}
            </>
          ) : (
            <p className="text-gray-500 text-sm">
              {run.status === 'completed' ? 'No output data.' : 'Workflow has not completed yet.'}
            </p>
          )}
        </div>
      )}

      {tab === 'audit' && (
        <div className="space-y-2">
          {auditTrail.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-8">No audit entries.</p>
          ) : (
            auditTrail.map((entry: any, i: number) => (
              <div key={i} className="flex gap-3 text-sm">
                <span className="text-xs text-gray-600 w-32 shrink-0 text-right">
                  {entry.timestamp ? formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true }) : ''}
                </span>
                <div>
                  <span className="text-gray-300">{entry.event_type.replace(/_/g, ' ')}</span>
                  {entry.step_id && <span className="text-gray-600 ml-1 font-mono">({entry.step_id})</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Metadata */}
      <div className="mt-6 text-xs text-gray-600 space-y-1">
        {run.started_at && <p>Started: {new Date(run.started_at).toLocaleString()}</p>}
        {run.completed_at && <p>Completed: {new Date(run.completed_at).toLocaleString()}</p>}
      </div>
    </div>
  );
}
