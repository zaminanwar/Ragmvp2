import { create } from 'zustand';
import { api } from '../api/client';
import type { Workspace } from '../types';

interface WorkspaceState {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  isLoading: boolean;
  fetchWorkspaces: () => Promise<void>;
  setActiveWorkspace: (ws: Workspace) => void;
  createWorkspace: (data: Partial<Workspace>) => Promise<Workspace>;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  workspaces: [],
  activeWorkspace: null,
  isLoading: false,

  fetchWorkspaces: async () => {
    set({ isLoading: true });
    try {
      const workspaces = await api.listWorkspaces();
      set({ workspaces, isLoading: false });
      if (workspaces.length > 0 && !useWorkspaceStore.getState().activeWorkspace) {
        set({ activeWorkspace: workspaces[0] });
      }
    } catch {
      set({ isLoading: false });
    }
  },

  setActiveWorkspace: (ws) => set({ activeWorkspace: ws }),

  createWorkspace: async (data) => {
    const ws = await api.createWorkspace(data);
    set((state) => ({ workspaces: [...state.workspaces, ws], activeWorkspace: ws }));
    return ws;
  },
}));
