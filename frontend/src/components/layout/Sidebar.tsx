import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { MessageSquare, FileText, Folders, Shield, LogOut, Plus, ChevronDown, GitBranch } from 'lucide-react';
import { useWorkflowStore } from '../../stores/workflowStore';
import { useAuthStore } from '../../stores/authStore';
import { useWorkspaceStore } from '../../stores/workspaceStore';
import { api } from '../../api/client';
import type { Conversation } from '../../types';

export default function Sidebar() {
  const location = useLocation();
  const { user, logout } = useAuthStore();
  const { workspaces, activeWorkspace, setActiveWorkspace, fetchWorkspaces } = useWorkspaceStore();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showWsDropdown, setShowWsDropdown] = useState(false);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  useEffect(() => {
    if (activeWorkspace) {
      api.listConversations(activeWorkspace.id).then(setConversations).catch(() => {});
    }
  }, [activeWorkspace]);

  const { pendingApprovals, fetchPendingApprovals } = useWorkflowStore();

  useEffect(() => {
    if (activeWorkspace) {
      fetchPendingApprovals(activeWorkspace.id);
    }
  }, [activeWorkspace, fetchPendingApprovals]);

  const navItems = [
    { path: '/chat', icon: MessageSquare, label: 'Chat', badge: 0 },
    { path: '/documents', icon: FileText, label: 'Documents', badge: 0 },
    { path: '/workflows', icon: GitBranch, label: 'Workflows', badge: pendingApprovals.length },
    { path: '/workspaces', icon: Folders, label: 'Workspaces', badge: 0 },
  ];

  if (user?.role === 'admin') {
    navItems.push({ path: '/admin', icon: Shield, label: 'Admin', badge: 0 });
  }

  return (
    <div className="w-64 bg-gray-950 border-r border-gray-800 flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-lg font-bold text-primary-400">Enterprise RAG</h1>
        <p className="text-xs text-gray-500 mt-1">Intelligent Knowledge Platform</p>
      </div>

      {/* Workspace Selector */}
      <div className="p-3 border-b border-gray-800">
        <div
          className="flex items-center justify-between p-2 rounded-lg bg-gray-800 cursor-pointer hover:bg-gray-700"
          onClick={() => setShowWsDropdown(!showWsDropdown)}
        >
          <span className="text-sm truncate">{activeWorkspace?.name || 'Select Workspace'}</span>
          <ChevronDown className="w-4 h-4 text-gray-400" />
        </div>
        {showWsDropdown && (
          <div className="mt-1 bg-gray-800 rounded-lg border border-gray-700 max-h-40 overflow-y-auto">
            {workspaces.map((ws) => (
              <div
                key={ws.id}
                className={`p-2 text-sm cursor-pointer hover:bg-gray-700 ${
                  ws.id === activeWorkspace?.id ? 'text-primary-400' : 'text-gray-300'
                }`}
                onClick={() => {
                  setActiveWorkspace(ws);
                  setShowWsDropdown(false);
                }}
              >
                {ws.name}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <Link to="/chat" className="flex items-center gap-2 btn-primary w-full justify-center text-sm">
          <Plus className="w-4 h-4" /> New Chat
        </Link>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-3">
        <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Recent</div>
        {conversations.map((conv) => (
          <Link
            key={conv.id}
            to={`/chat/${conv.id}`}
            className="block p-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg truncate mb-1"
          >
            {conv.title}
          </Link>
        ))}
      </div>

      {/* Navigation */}
      <nav className="p-3 border-t border-gray-800">
        {navItems.map(({ path, icon: Icon, label, badge }) => (
          <Link
            key={path}
            to={path}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm mb-1 ${
              location.pathname.startsWith(path)
                ? 'bg-primary-600/20 text-primary-400'
                : 'text-gray-400 hover:text-white hover:bg-gray-800'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
            {badge > 0 && (
              <span className="ml-auto text-xs px-1.5 py-0.5 rounded-full bg-yellow-400/20 text-yellow-400">
                {badge}
              </span>
            )}
          </Link>
        ))}
      </nav>

      {/* User */}
      <div className="p-3 border-t border-gray-800 flex items-center justify-between">
        <div className="text-sm">
          <div className="text-gray-300">{user?.username}</div>
          <div className="text-xs text-gray-500">{user?.role}</div>
        </div>
        <button onClick={logout} className="text-gray-500 hover:text-red-400">
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
