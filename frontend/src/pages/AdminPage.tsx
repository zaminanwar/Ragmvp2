import { useState, useEffect } from 'react';
import { Users, Database, MessageSquare, FileText, Folders, BarChart3 } from 'lucide-react';
import { api } from '../api/client';
import { useAuthStore } from '../stores/authStore';

export default function AdminPage() {
  const { user } = useAuthStore();
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);

  useEffect(() => {
    if (user?.role !== 'admin') return;
    api.getSystemStats().then(setStats).catch(() => {});
    api.listUsers().then(setUsers).catch(() => {});
    api.getProviders().then((d) => setProviders(d.providers)).catch(() => {});
  }, [user]);

  if (user?.role !== 'admin') {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Admin access required
      </div>
    );
  }

  const statCards = stats
    ? [
        { label: 'Users', value: stats.users, icon: Users },
        { label: 'Workspaces', value: stats.workspaces, icon: Folders },
        { label: 'Documents', value: stats.documents, icon: FileText },
        { label: 'Chunks', value: stats.chunks, icon: Database },
        { label: 'Conversations', value: stats.conversations, icon: MessageSquare },
        { label: 'Messages', value: stats.messages, icon: BarChart3 },
      ]
    : [];

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Admin Dashboard</h1>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          {statCards.map(({ label, value, icon: Icon }) => (
            <div key={label} className="card text-center">
              <Icon className="w-6 h-6 mx-auto mb-2 text-primary-400" />
              <div className="text-2xl font-bold">{value}</div>
              <div className="text-xs text-gray-500">{label}</div>
            </div>
          ))}
        </div>

        {/* LLM Providers */}
        <div className="mb-8">
          <h2 className="text-lg font-semibold mb-4">LLM Providers</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {providers.map((p) => (
              <div key={p.id} className="card">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-medium">{p.name}</h3>
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      p.status === 'offline'
                        ? 'bg-red-900/30 text-red-400'
                        : 'bg-green-900/30 text-green-400'
                    }`}
                  >
                    {p.status || 'online'}
                  </span>
                </div>
                <div className="text-xs text-gray-500">
                  {p.models.length} models | {p.embedding_models.length} embeddings
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Users Table */}
        <div>
          <h2 className="text-lg font-semibold mb-4">Users</h2>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left py-2 px-3">Username</th>
                  <th className="text-left py-2 px-3">Email</th>
                  <th className="text-left py-2 px-3">Role</th>
                  <th className="text-left py-2 px-3">Status</th>
                  <th className="text-left py-2 px-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-gray-800 hover:bg-gray-750">
                    <td className="py-2 px-3">{u.username}</td>
                    <td className="py-2 px-3 text-gray-400">{u.email}</td>
                    <td className="py-2 px-3">
                      <span className="bg-gray-700 px-2 py-0.5 rounded text-xs">{u.role}</span>
                    </td>
                    <td className="py-2 px-3">
                      <span
                        className={`text-xs ${u.is_active ? 'text-green-400' : 'text-red-400'}`}
                      >
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-gray-500 text-xs">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
