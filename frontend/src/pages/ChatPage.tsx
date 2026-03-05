import { useState, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Send, Loader2, BookOpen, Sparkles, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api/client';
import { useWorkspaceStore } from '../stores/workspaceStore';
import type { Message, Citation } from '../types';

export default function ChatPage() {
  const { conversationId } = useParams();
  const { activeWorkspace } = useWorkspaceStore();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentConvId, setCurrentConvId] = useState<string | undefined>(conversationId);
  const [expandedCitation, setExpandedCitation] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (conversationId) {
      setCurrentConvId(conversationId);
      api.getMessages(conversationId).then((data) => {
        setMessages(data.messages || []);
      }).catch(() => {});
    } else {
      setMessages([]);
      setCurrentConvId(undefined);
    }
  }, [conversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || !activeWorkspace || isStreaming) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: input.trim(),
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsStreaming(true);

    try {
      // Use non-streaming for simplicity; streaming via SSE
      const response = await api.sendMessage(
        activeWorkspace.id,
        userMessage.content,
        currentConvId,
      );

      if (!currentConvId) {
        setCurrentConvId(response.conversation_id);
      }

      const assistantMessage: Message = {
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        model_used: response.assistant_message.model_used,
        was_corrective_rag: response.assistant_message.was_corrective_rag,
        citations: response.assistant_message.citations || [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Error: ${err.message}`,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  };

  if (!activeWorkspace) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <div className="text-center">
          <Sparkles className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p className="text-lg">Select or create a workspace to start chatting</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center max-w-md">
              <Sparkles className="w-16 h-16 mx-auto mb-4 text-primary-400 opacity-60" />
              <h2 className="text-xl font-semibold text-gray-300 mb-2">Enterprise RAG</h2>
              <p className="text-sm">
                Ask questions about your documents. Use <code className="bg-gray-800 px-1 rounded">#filename</code> to reference specific documents.
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div className="card text-left">Hybrid search (vector + BM25)</div>
                <div className="card text-left">Corrective RAG with auto-rewrite</div>
                <div className="card text-left">Grounded citations</div>
                <div className="card text-left">Multi-provider LLM support</div>
              </div>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-3xl rounded-2xl px-4 py-3 ${
              msg.role === 'user'
                ? 'bg-primary-600 text-white'
                : 'bg-gray-800 text-gray-100'
            }`}>
              {msg.role === 'assistant' ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}

              {/* Corrective RAG indicator */}
              {msg.was_corrective_rag && (
                <div className="flex items-center gap-1 mt-2 text-xs text-amber-400">
                  <AlertCircle className="w-3 h-3" />
                  Query was automatically refined for better results
                </div>
              )}

              {/* Citations */}
              {msg.citations && msg.citations.length > 0 && (
                <div className="mt-3 border-t border-gray-700 pt-2">
                  <div className="flex items-center gap-1 text-xs text-gray-400 mb-2">
                    <BookOpen className="w-3 h-3" /> Sources
                  </div>
                  <div className="space-y-1">
                    {msg.citations.map((cite: Citation, idx: number) => (
                      <div key={idx}>
                        <button
                          className="text-xs text-primary-400 hover:text-primary-300 cursor-pointer"
                          onClick={() => setExpandedCitation(expandedCitation === idx ? null : idx)}
                        >
                          [{cite.position}] Score: {cite.relevance_score?.toFixed(3)}
                        </button>
                        {expandedCitation === idx && (
                          <div className="mt-1 p-2 bg-gray-900 rounded text-xs text-gray-400 border border-gray-700">
                            {cite.excerpt}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {msg.model_used && (
                <div className="text-xs text-gray-500 mt-1">{msg.model_used}</div>
              )}
            </div>
          </div>
        ))}

        {isStreaming && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-2xl px-4 py-3">
              <Loader2 className="w-5 h-5 animate-spin text-primary-400" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 p-4">
        <div className="max-w-3xl mx-auto flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder={`Ask about your documents in ${activeWorkspace.name}...`}
            className="input-field flex-1"
            disabled={isStreaming}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="btn-primary flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="text-center mt-2 text-xs text-gray-600">
          {activeWorkspace.enable_hybrid_search ? 'Hybrid Search' : 'Vector Search'}
          {activeWorkspace.enable_reranking && ' + Reranking'}
          {' | '}
          {activeWorkspace.llm_model || 'Default Model'}
        </div>
      </div>
    </div>
  );
}
