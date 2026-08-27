import React, { useState, useEffect } from 'react';
import { Database, X, RefreshCw, Layers, Hash, FileText, CheckCircle2, AlertCircle } from 'lucide-react';
import { fetchVectorStore } from '../api/client';

const VectorStoreModal = ({ assignmentId, isOpen, onClose }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadVectorData = async () => {
    if (!assignmentId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchVectorStore(assignmentId);
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to load vector store');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    if (isOpen && assignmentId) {
      fetchVectorStore(assignmentId)
        .then((result) => {
          if (isMounted) {
            setData(result);
            setLoading(false);
          }
        })
        .catch((err) => {
          if (isMounted) {
            setError(err.message || 'Failed to load vector store');
            setLoading(false);
          }
        });
    }
    return () => {
      isMounted = false;
    };
  }, [isOpen, assignmentId]);

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(15, 23, 42, 0.65)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1.5rem'
    }}>
      <div className="glass-panel" style={{
        backgroundColor: '#ffffff',
        borderRadius: '16px',
        width: '100%',
        maxWidth: '850px',
        maxHeight: '85vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: 'none',
        border: '1px solid var(--border)',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '1.25rem 1.75rem',
          borderBottom: '1px solid #e2e8f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.06) 0%, rgba(16, 185, 129, 0.06) 100%)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              background: 'var(--primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff'
            }}>
              <Database size={22} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--secondary)', fontWeight: 700 }}>
                ChromaDB Vector Embeddings Store
              </h3>
              <p style={{ margin: 0, fontSize: '0.825rem', color: 'var(--text-muted)' }}>
                Assignment Collection: <code style={{ color: 'var(--primary-dark)', fontWeight: 600 }}>{data?.collection_name || assignmentId}</code>
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              className="btn btn-outline"
              onClick={loadVectorData}
              disabled={loading}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '0.4rem',
                borderRadius: '8px',
                color: '#64748b'
              }}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '1.5rem 1.75rem', overflowY: 'auto', flex: 1 }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--text-muted)' }}>
              <RefreshCw size={28} className="animate-spin" style={{ margin: '0 auto 1rem auto', color: 'var(--primary)' }} />
              <p>Fetching vector embeddings from ChromaDB...</p>
            </div>
          )}

          {error && (
            <div style={{
              padding: '1rem 1.25rem',
              backgroundColor: '#fef2f2',
              border: '1px solid #fca5a5',
              borderRadius: '10px',
              color: '#991b1b',
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem'
            }}>
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && data && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Summary Metrics */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '1rem',
                backgroundColor: '#f8fafc',
                padding: '1rem',
                borderRadius: '12px',
                border: '1px solid #e2e8f0'
              }}>
                <div>
                  <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#64748b', fontWeight: 600 }}>Indexing Status</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.2rem', fontWeight: 700, color: data.status === 'indexed' ? 'var(--success)' : '#d97706' }}>
                    <CheckCircle2 size={16} /> {data.status === 'indexed' ? 'Indexed & Active' : 'Not Indexed'}
                  </div>
                </div>

                <div>
                  <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#64748b', fontWeight: 600 }}>Vector Count</span>
                  <div style={{ marginTop: '0.2rem', fontWeight: 700, fontSize: '1.1rem', color: 'var(--secondary)' }}>
                    {data.vector_count} chunk(s)
                  </div>
                </div>

                <div>
                  <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#64748b', fontWeight: 600 }}>Vector Dimension</span>
                  <div style={{ marginTop: '0.2rem', fontWeight: 700, fontSize: '1.1rem', color: 'var(--primary)' }}>
                    {data.vectors?.[0]?.embedding_dimensions || 384} floats
                  </div>
                </div>
              </div>

              {/* Vectors List */}
              <div>
                <h4 style={{ margin: '0 0 0.8rem 0', fontSize: '1rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Layers size={18} color="var(--primary)" /> Indexed Document Embeddings ({data.vectors?.length || 0})
                </h4>

                {data.vectors?.length === 0 ? (
                  <div style={{ padding: '2rem', textAlign: 'center', backgroundColor: '#f8fafc', borderRadius: '10px', color: 'var(--text-muted)' }}>
                    No vector embeddings indexed for this assignment yet.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {data.vectors.map((vec, idx) => (
                      <div key={vec.chunk_id || idx} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '12px',
                        padding: '1.2rem',
                        backgroundColor: '#ffffff',
                        boxShadow: 'none'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                          <span style={{
                            fontSize: '0.8rem',
                            fontWeight: 700,
                            padding: '0.2rem 0.6rem',
                            borderRadius: '6px',
                            backgroundColor: 'var(--primary-light)',
                            color: 'var(--primary-dark)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem'
                          }}>
                            <Hash size={13} /> {vec.chunk_id}
                          </span>
                          <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                            Type: {vec.metadata?.type || 'rubric_vector'}
                          </span>
                        </div>

                        {/* Chunk Content */}
                        <div style={{ marginBottom: '0.75rem' }}>
                          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                            <FileText size={14} /> Chunk Reference Text:
                          </div>
                          <pre style={{
                            margin: 0,
                            padding: '0.75rem',
                            backgroundColor: '#f8fafc',
                            borderRadius: '8px',
                            fontSize: '0.825rem',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            border: '1px solid #f1f5f9',
                            fontFamily: 'monospace',
                            color: '#334155'
                          }}>
                            {vec.text_content}
                          </pre>
                        </div>

                        {/* Vector Preview */}
                        <div>
                          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>
                            Embedding Vector Preview ({vec.embedding_dimensions} dims):
                          </div>
                          <code style={{
                            display: 'block',
                            padding: '0.5rem 0.75rem',
                            backgroundColor: '#0f172a',
                            color: '#38bdf8',
                            borderRadius: '6px',
                            fontSize: '0.78rem',
                            overflowX: 'auto',
                            fontFamily: 'monospace'
                          }}>
                            [{vec.vector_preview ? vec.vector_preview.join(', ') : 'No preview available'}]
                          </code>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default VectorStoreModal;
