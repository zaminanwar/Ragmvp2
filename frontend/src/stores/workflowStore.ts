import { create } from 'zustand';
import { api } from '../api/client';
import type { WorkflowDefinition, WorkflowRun, WorkflowApproval } from '../types';

interface WorkflowState {
  definitions: WorkflowDefinition[];
  runs: WorkflowRun[];
  activeRun: WorkflowRun | null;
  pendingApprovals: WorkflowApproval[];
  isLoading: boolean;
  error: string | null;

  fetchDefinitions: (workspaceId: string) => Promise<void>;
  fetchRuns: (workspaceId: string) => Promise<void>;
  fetchRun: (runId: string) => Promise<void>;
  startRun: (workflowId: string, workspaceId: string, inputs: Record<string, any>) => Promise<WorkflowRun>;
  cancelRun: (runId: string) => Promise<void>;
  rerunFromStep: (runId: string, stepId: string, overrides?: Record<string, any>) => Promise<WorkflowRun>;
  fetchPendingApprovals: (workspaceId: string) => Promise<void>;
  decideApproval: (approvalId: string, approved: boolean, comment?: string) => Promise<void>;
  clearError: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  definitions: [],
  runs: [],
  activeRun: null,
  pendingApprovals: [],
  isLoading: false,
  error: null,

  fetchDefinitions: async (workspaceId) => {
    set({ isLoading: true, error: null });
    try {
      const defs = await api.listWorkflowDefinitions(workspaceId);
      set({ definitions: defs, isLoading: false });
    } catch (e: any) {
      set({ error: e.message, isLoading: false });
    }
  },

  fetchRuns: async (workspaceId) => {
    set({ isLoading: true, error: null });
    try {
      const runs = await api.listWorkflowRuns(workspaceId);
      set({ runs, isLoading: false });
    } catch (e: any) {
      set({ error: e.message, isLoading: false });
    }
  },

  fetchRun: async (runId) => {
    set({ isLoading: true, error: null });
    try {
      const run = await api.getWorkflowRun(runId);
      set({ activeRun: run, isLoading: false });
    } catch (e: any) {
      set({ error: e.message, isLoading: false });
    }
  },

  startRun: async (workflowId, workspaceId, inputs) => {
    set({ isLoading: true, error: null });
    try {
      const run = await api.startWorkflowRun(workflowId, workspaceId, inputs);
      set((state) => ({ runs: [run, ...state.runs], activeRun: run, isLoading: false }));
      return run;
    } catch (e: any) {
      set({ error: e.message, isLoading: false });
      throw e;
    }
  },

  cancelRun: async (runId) => {
    try {
      const run = await api.cancelWorkflowRun(runId);
      set((state) => ({
        runs: state.runs.map((r) => (r.id === runId ? run : r)),
        activeRun: state.activeRun?.id === runId ? run : state.activeRun,
      }));
    } catch (e: any) {
      set({ error: e.message });
    }
  },

  rerunFromStep: async (runId, stepId, overrides) => {
    set({ isLoading: true, error: null });
    try {
      const newRun = await api.rerunFromStep(runId, stepId, overrides);
      set((state) => ({ runs: [newRun, ...state.runs], activeRun: newRun, isLoading: false }));
      return newRun;
    } catch (e: any) {
      set({ error: e.message, isLoading: false });
      throw e;
    }
  },

  fetchPendingApprovals: async (workspaceId) => {
    try {
      const approvals = await api.listPendingApprovals(workspaceId);
      set({ pendingApprovals: approvals });
    } catch (e: any) {
      set({ error: e.message });
    }
  },

  decideApproval: async (approvalId, approved, comment) => {
    try {
      await api.decideApproval(approvalId, approved, comment);
      set((state) => ({
        pendingApprovals: state.pendingApprovals.filter((a) => a.id !== approvalId),
      }));
    } catch (e: any) {
      set({ error: e.message });
    }
  },

  clearError: () => set({ error: null }),
}));
