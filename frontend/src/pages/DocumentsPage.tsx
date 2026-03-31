import { useState, useEffect, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, FileText, Trash2, Loader2, CheckCircle, XCircle, Clock } from 'lucide-react';
import { api } from '../api/client';
import { useWorkspaceStore } from '../stores/workspaceStore';
import type { Document } from '../types';

const STATUS_ICONS = {
  pending: <Clock className="w-4 h-4 text-yellow-400" />,
  processing: <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />,
  indexed: <CheckCircle className="w-4 h-4 text-green-400" />,
  failed: <XCircle className="w-4 h-4 text-red-400" />,
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const { activeWorkspace } = useWorkspaceStore();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [stats, setStats] = useState<any>(null);

  const fetchDocs = useCallback(async () => {
    if (!activeWorkspace) return;
    try {
      const docs = await api.listDocuments(activeWorkspace.id);
      setDocuments(docs);
    } catch {}
    try {
      const s = await api.getWorkspaceStats(activeWorkspace.id);
      setStats(s);
    } catch {}
  }, [activeWorkspace]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (!activeWorkspace) return;
      setUploading(true);
      for (const file of acceptedFiles) {
        try {
          await api.uploadDocument(activeWorkspace.id, file);
        } catch (err: any) {
          console.error('Upload failed:', err.message);
        }
      }
      setUploading(false);
      fetchDocs();
    },
    [activeWorkspace, fetchDocs]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/html': ['.html'],
      'application/json': ['.json'],
    },
  });

  const handleDelete = async (docId: string) => {
    if (!confirm('Delete this document and all its chunks?')) return;
    await api.deleteDocument(docId);
    fetchDocs();
  };

  if (!activeWorkspace) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Select a workspace to manage documents
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Documents - {activeWorkspace.name}</h1>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="card">
              <div className="text-2xl font-bold text-primary-400">{stats.document_count}</div>
              <div className="text-sm text-gray-500">Documents</div>
            </div>
            <div className="card">
              <div className="text-2xl font-bold text-primary-400">{stats.chunk_count}</div>
              <div className="text-sm text-gray-500">Chunks Indexed</div>
            </div>
          </div>
        )}

        {/* Upload Zone */}
        <div
          {...getRootProps()}
          className={`card border-2 border-dashed mb-6 cursor-pointer transition-colors text-center py-10 ${
            isDragActive ? 'border-primary-500 bg-primary-500/10' : 'border-gray-600 hover:border-gray-500'
          }`}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <div className="flex items-center justify-center gap-2">
              <Loader2 className="w-6 h-6 animate-spin text-primary-400" />
              <span>Processing documents...</span>
            </div>
          ) : (
            <>
              <Upload className="w-10 h-10 mx-auto mb-3 text-gray-500" />
              <p className="text-gray-400">
                {isDragActive ? 'Drop files here' : 'Drag & drop files or click to browse'}
              </p>
              <p className="text-xs text-gray-600 mt-2">
                Supports PDF, DOCX, TXT, MD, CSV, XLSX, HTML, JSON
              </p>
            </>
          )}
        </div>

        {/* Document List */}
        <div className="space-y-2">
          {documents.map((doc) => (
            <div key={doc.id} className="card flex items-center justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <FileText className="w-5 h-5 text-gray-500 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{doc.original_filename}</p>
                  <p className="text-xs text-gray-500">
                    {formatSize(doc.file_size)} | {doc.chunk_count} chunks | {doc.file_type.toUpperCase()}
                  </p>
                  {doc.error_message && (
                    <p className="text-xs text-red-400 mt-1">{doc.error_message}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                {STATUS_ICONS[doc.status as keyof typeof STATUS_ICONS]}
                <button
                  onClick={() => handleDelete(doc.id)}
                  className="text-gray-500 hover:text-red-400"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}

          {documents.length === 0 && (
            <p className="text-center text-gray-500 py-8">No documents yet. Upload some files to get started.</p>
          )}
        </div>
      </div>
    </div>
  );
}
