import { create } from 'zustand';
import { api } from '../api/client';
import type { User } from '../types';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (email, password) => {
    const { token, user } = await api.login(email, password);
    api.setToken(token);
    set({ user, isAuthenticated: true });
  },

  register: async (email, username, password, fullName) => {
    const { token, user } = await api.register(email, username, password, fullName);
    api.setToken(token);
    set({ user, isAuthenticated: true });
  },

  logout: () => {
    api.clearToken();
    set({ user: null, isAuthenticated: false });
  },

  checkAuth: async () => {
    try {
      if (api.getToken()) {
        const user = await api.getMe();
        set({ user, isAuthenticated: true, isLoading: false });
      } else {
        set({ isLoading: false });
      }
    } catch {
      api.clearToken();
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
