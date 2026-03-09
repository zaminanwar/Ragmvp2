import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';
import Layout from './components/layout/Layout';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ChatPage from './pages/ChatPage';
import DocumentsPage from './pages/DocumentsPage';
import WorkspacesPage from './pages/WorkspacesPage';
import AdminPage from './pages/AdminPage';
import WorkflowsPage from './pages/WorkflowsPage';
import WorkflowStartPage from './pages/WorkflowStartPage';
import WorkflowRunPage from './pages/WorkflowRunPage';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthStore();
  if (isLoading) return <div className="flex items-center justify-center h-screen">Loading...</div>;
  if (!isAuthenticated) return <Navigate to="/login" />;
  return <>{children}</>;
}

export default function App() {
  const { checkAuth } = useAuthStore();

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<ChatPage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/chat/:conversationId" element={<ChatPage />} />
                <Route path="/documents" element={<DocumentsPage />} />
                <Route path="/workspaces" element={<WorkspacesPage />} />
                <Route path="/workflows" element={<WorkflowsPage />} />
                <Route path="/workflows/:workflowId/start" element={<WorkflowStartPage />} />
                <Route path="/workflows/runs/:runId" element={<WorkflowRunPage />} />
                <Route path="/admin" element={<AdminPage />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
