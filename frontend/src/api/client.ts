const API_BASE = '/api';

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
    localStorage.setItem('rag_token', token);
  }

  getToken(): string | null {
    if (!this.token) {
      this.token = localStorage.getItem('rag_token');
    }
    return this.token;
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem('rag_token');
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...((options.headers as Record<string, string>) || {}),
    };

    if (this.getToken()) {
      headers['Authorization'] = `Bearer ${this.getToken()}`;
    }

    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(`${API_BASE}${path}`, { ...options, headers });

    if (response.status === 401) {
      this.clearToken();
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(error.detail || 'Request failed');
    }

    return response.json();
  }

  // Auth
  async register(email: string, username: string, password: string, fullName?: string) {
    return this.request<{ token: string; user: any }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, username, password, full_name: fullName }),
    });
  }

  async login(email: string, password: string) {
    return this.request<{ token: string; user: any }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }

  async getMe() {
    return this.request<any>('/auth/me');
  }

  // Workspaces
  async listWorkspaces() {
    return this.request<any[]>('/workspaces');
  }

  async createWorkspace(data: any) {
    return this.request<any>('/workspaces', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateWorkspace(id: string, data: any) {
    return this.request<any>(`/workspaces/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // Documents
  async uploadDocument(workspaceId: string, file: File, options?: { chunkStrategy?: string; chunkSize?: number }) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspace_id', workspaceId);
    if (options?.chunkStrategy) formData.append('chunk_strategy', options.chunkStrategy);
    if (options?.chunkSize) formData.append('chunk_size', String(options.chunkSize));

    return this.request<any>('/documents/upload', {
      method: 'POST',
      body: formData,
    });
  }

  async listDocuments(workspaceId: string) {
    return this.request<any[]>(`/documents/workspace/${workspaceId}`);
  }

  async deleteDocument(documentId: string) {
    return this.request<any>(`/documents/${documentId}`, { method: 'DELETE' });
  }

  async getWorkspaceStats(workspaceId: string) {
    return this.request<any>(`/documents/workspace/${workspaceId}/stats`);
  }

  // Chat
  async sendMessage(workspaceId: string, message: string, conversationId?: string) {
    return this.request<any>('/chat/send', {
      method: 'POST',
      body: JSON.stringify({ workspace_id: workspaceId, message, conversation_id: conversationId }),
    });
  }

  async streamMessage(workspaceId: string, message: string, conversationId?: string) {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.getToken()) headers['Authorization'] = `Bearer ${this.getToken()}`;

    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ workspace_id: workspaceId, message, conversation_id: conversationId }),
    });

    return response.body;
  }

  async listConversations(workspaceId: string) {
    return this.request<any[]>(`/chat/conversations/${workspaceId}`);
  }

  async getMessages(conversationId: string) {
    return this.request<any>(`/chat/conversation/${conversationId}/messages`);
  }

  async deleteConversation(conversationId: string) {
    return this.request<any>(`/chat/conversation/${conversationId}`, { method: 'DELETE' });
  }

  // Models
  async getProviders() {
    return this.request<{ providers: any[] }>('/models/providers');
  }

  // Admin
  async getSystemStats() {
    return this.request<any>('/admin/stats');
  }

  async listUsers() {
    return this.request<any[]>('/admin/users');
  }
}

export const api = new ApiClient();
