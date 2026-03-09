import { CheckCircle, XCircle, Clock, Loader2, SkipForward, RotateCcw } from 'lucide-react';
import type { WorkflowStep, WorkflowStepResult } from '../../types';

interface StepTimelineProps {
  steps: WorkflowStep[];
  stepResults: WorkflowStepResult[];
  currentStepIndex: number;
  onRerunFromStep?: (stepId: string) => void;
}

const statusConfig: Record<string, { icon: typeof CheckCircle; color: string; bg: string }> = {
  completed: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-400/10' },
  running: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-400/10' },
  failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-400/10' },
  skipped: { icon: SkipForward, color: 'text-gray-500', bg: 'bg-gray-500/10' },
  pending: { icon: Clock, color: 'text-gray-500', bg: 'bg-gray-800' },
};

export default function StepTimeline({ steps, stepResults, currentStepIndex, onRerunFromStep }: StepTimelineProps) {
  const getStepResult = (stepId: string) => stepResults.find((r) => r.step_id === stepId);

  return (
    <div className="space-y-1">
      {steps.map((step, index) => {
        const result = getStepResult(step.id);
        const status = result?.status || (index < currentStepIndex ? 'completed' : index === currentStepIndex ? 'running' : 'pending');
        const config = statusConfig[status] || statusConfig.pending;
        const Icon = config.icon;
        const isLast = index === steps.length - 1;

        return (
          <div key={step.id} className="flex gap-3">
            {/* Timeline line + icon */}
            <div className="flex flex-col items-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center ${config.bg}`}>
                <Icon className={`w-4 h-4 ${config.color} ${status === 'running' ? 'animate-spin' : ''}`} />
              </div>
              {!isLast && <div className="w-0.5 h-full min-h-[2rem] bg-gray-800" />}
            </div>

            {/* Content */}
            <div className="flex-1 pb-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-medium text-gray-200">{step.name}</h4>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {step.tool}
                    {result?.duration_ms != null && (
                      <span className="ml-2 text-gray-600">
                        {result.duration_ms < 1000
                          ? `${result.duration_ms}ms`
                          : `${(result.duration_ms / 1000).toFixed(1)}s`}
                      </span>
                    )}
                  </p>
                </div>
                {onRerunFromStep && (status === 'completed' || status === 'failed') && (
                  <button
                    onClick={() => onRerunFromStep(step.id)}
                    className="text-xs text-gray-500 hover:text-primary-400 flex items-center gap-1"
                    title="Re-run from this step"
                  >
                    <RotateCcw className="w-3 h-3" /> Re-run
                  </button>
                )}
              </div>

              {result?.error_message && (
                <p className="text-xs text-red-400 mt-1 bg-red-400/5 rounded px-2 py-1">
                  {result.error_message}
                </p>
              )}

              {step.checkpoint && (
                <span className="inline-block mt-1 text-xs px-2 py-0.5 rounded bg-yellow-400/10 text-yellow-400">
                  Requires approval
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
