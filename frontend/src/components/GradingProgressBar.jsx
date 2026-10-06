import React from 'react';
import { Loader2 } from 'lucide-react';

/**
 * GradingProgressBar
 * Pops out ONLY during active grading process to show real-time progress.
 * Hidden automatically when grading is not active (no "Grading Complete!" popup).
 */
const GradingProgressBar = ({ submissions = [], isGrading = false }) => {
  const total = submissions.length;
  const graded = submissions.filter(s =>
    s.status === 'graded' || s.status === 'flagged' || s.status === 'approved'
  ).length;
  const processing = submissions.filter(s =>
    ['processing', 'grading', 'extracting_answers', 'retrieving_rubric'].includes(s.status)
  ).length;
  const pending = submissions.filter(s =>
    s.status === 'pending' || s.status === 'uploaded'
  ).length;

  const isActivelyGrading = Boolean(isGrading || processing > 0);

  // Strictly pop out ONLY during the grading process
  if (!isActivelyGrading || total === 0) return null;

  const pct = total > 0 ? Math.round((graded / total) * 100) : 0;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '5.5rem',
        right: '1.75rem',
        width: '280px',
        backgroundColor: '#EFF6FF',
        border: '1px solid #BFDBFE',
        borderRadius: '10px',
        padding: '0.9rem 1.1rem',
        zIndex: 999,
        boxShadow: '0 10px 25px -5px rgba(37, 99, 235, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.05)',
        animation: 'slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1) both',
      }}
    >
      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(20px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.6rem' }}>
        <Loader2 size={16} color="#2563EB" className="spin" />
        <span style={{ fontWeight: 700, fontSize: '0.82rem', color: '#1D4ED8' }}>
          Grading Submissions…
        </span>
      </div>

      {/* Counter */}
      <div style={{ marginBottom: '0.55rem' }}>
        <span style={{ fontSize: '1.35rem', fontWeight: 800, color: '#1D4ED8', lineHeight: 1 }}>
          {graded}
        </span>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted, #64748b)', marginLeft: '0.3rem' }}>
          / {total} papers graded
        </span>
      </div>

      {/* Progress bar */}
      <div style={{
        width: '100%', height: '6px',
        backgroundColor: 'rgba(255, 255, 255, 0.85)',
        borderRadius: '3px', overflow: 'hidden', marginBottom: '0.5rem',
        border: '1px solid rgba(191, 219, 254, 0.8)'
      }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          backgroundColor: '#2563EB',
          borderRadius: '3px',
          transition: 'width 0.4s ease',
        }} />
      </div>

      {/* Detail row */}
      <div style={{ display: 'flex', gap: '0.85rem', fontSize: '0.75rem', color: '#475569' }}>
        <span>⚡ {processing > 0 ? `${processing} grading now` : 'Processing…'}</span>
        {pending > 0 && <span>⏳ {pending} waiting</span>}
      </div>
    </div>
  );
};

export default GradingProgressBar;
