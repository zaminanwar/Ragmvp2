import { useState } from 'react';
import { CheckCircle, XCircle } from 'lucide-react';
import type { WorkflowApproval } from '../../types';

interface ApprovalPanelProps {
  approval: WorkflowApproval;
  onDecide: (approvalId: string, approved: boolean, comment?: string) => Promise<void>;
}

export default function ApprovalPanel({ approval, onDecide }: ApprovalPanelProps) {
  const [comment, setComment] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleDecide = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
      await onDecide(approval.id, approved, comment || undefined);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="border border-yellow-500/30 rounded-lg bg-yellow-500/5 p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
        <h3 className="text-sm font-medium text-yellow-400">Approval Required</h3>
      </div>

      <p className="text-sm text-gray-300 mb-3">
        Step <span className="font-mono text-yellow-400">{approval.step_id}</span> is waiting for approval.
      </p>

      {approval.context_json && Object.keys(approval.context_json).length > 0 && (
        <details className="mb-3">
          <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-300">
            View context data
          </summary>
          <pre className="mt-2 text-xs bg-gray-900 rounded p-3 overflow-x-auto text-gray-400 max-h-48">
            {JSON.stringify(approval.context_json, null, 2)}
          </pre>
        </details>
      )}

      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Optional comment..."
        className="w-full input-field text-sm mb-3 h-20 resize-none"
      />

      <div className="flex gap-2">
        <button
          onClick={() => handleDecide(true)}
          disabled={isSubmitting}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm disabled:opacity-50"
        >
          <CheckCircle className="w-4 h-4" />
          Approve
        </button>
        <button
          onClick={() => handleDecide(false)}
          disabled={isSubmitting}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm disabled:opacity-50"
        >
          <XCircle className="w-4 h-4" />
          Reject
        </button>
      </div>
    </div>
  );
}
