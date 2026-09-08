import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Search, Filter, ChevronRight, CheckCircle, Clock, AlertTriangle, Play, Sparkles, RefreshCw, Download, ShieldAlert, Loader2 } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const SubmissionsList = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [filter, setFilter] = useState(location.state?.filter || 'all');
  const [searchTerm, setSearchTerm] = useState('');
  const [gradingBatch, setGradingBatch] = useState(false);
  const [gradingSubIds, setGradingSubIds] = useState(new Set());
  const [qcSettings, setQcSettings] = useState({ enable_random_qc: false, qc_audit_rate: 0.05 });
  const { currentAssignmentId, currentAssignment, submissions, triggerGradeSubmission, triggerGradeAll, loadSubmissions, handleExportCSV } = useAssignment();

  useEffect(() => {
    if (location.state?.filter) {
      setFilter(location.state.filter);
    }
  }, [location.state?.filter]);

  useEffect(() => {
    fetch('/api/assignments/qc-settings')
      .then(res => res.json())
      .then(data => {
        if (data && typeof data === 'object') {
          setQcSettings({
            enable_random_qc: !!data.enable_random_qc,
            qc_audit_rate: parseFloat(data.qc_audit_rate || 0.05)
          });
        }
      })
      .catch(err => console.warn('Could not load QC settings:', err));
  }, []);

  // Smart background polling: only poll while actively tracking grading submissions
  useEffect(() => {
    if (!currentAssignmentId || gradingSubIds.size === 0) {
      return;
    }

    const interval = setInterval(() => {
      loadSubmissions(currentAssignmentId, true);
    }, 3000);

    return () => clearInterval(interval);
  }, [currentAssignmentId, gradingSubIds.size, loadSubmissions]);

  // Auto-clear finished submissions from local grading tracker
  useEffect(() => {
    if (gradingSubIds.size === 0) return;
    setGradingSubIds(prev => {
      const next = new Set(prev);
      let changed = false;
      submissions.forEach(s => {
        if ((s.status === 'graded' || s.status === 'flagged') && next.has(s.id)) {
          next.delete(s.id);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [submissions]);

  const handleUpdateQCSettings = async (enable, rate) => {
    try {
      const res = await fetch('/api/assignments/qc-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable_random_qc: enable, qc_audit_rate: rate })
      });
      const data = await res.json();
      setQcSettings({
        enable_random_qc: !!data.enable_random_qc,
        qc_audit_rate: parseFloat(data.qc_audit_rate || 0.05)
      });
    } catch (err) {
      alert(`Could not update QC settings: ${err.message}`);
    }
  };

  const getSubmissionMaxScore = (sub) => {
    if (sub?.feedback?.breakdown && sub.feedback.breakdown.length > 0) {
      const sumBreakdown = sub.feedback.breakdown.reduce((acc, item) => acc + (parseFloat(item.max_score) || 0), 0);
      if (sumBreakdown > 0) return sumBreakdown;
    }
    if (currentAssignment?.rubric_data && currentAssignment.rubric_data.length > 0) {
      const sumRubric = currentAssignment.rubric_data.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0);
      if (sumRubric > 0) return sumRubric;
    }
    return null;
  };

  const isSubmissionGrading = (sub) => {
    return gradingSubIds.has(sub.id) || sub.status === 'processing';
  };

  const handleGradeSingle = async (e, subId) => {
    e.stopPropagation();
    setGradingSubIds(prev => new Set(prev).add(subId));
    try {
      await triggerGradeSubmission(subId);
    } catch (err) {
      alert(`Grading failed: ${err.message}`);
    } finally {
      setGradingSubIds(prev => {
        const next = new Set(prev);
        next.delete(subId);
        return next;
      });
    }
  };

  const handleGradeAllBatch = async () => {
    try {
      setGradingBatch(true);
      const pendingIds = submissions
        .filter(s => s.status === 'pending' || s.status === 'uploaded')
        .map(s => s.id);
      setGradingSubIds(prev => new Set([...prev, ...pendingIds]));
      await triggerGradeAll(currentAssignmentId);
    } catch (err) {
      console.error(`Batch grading failed: ${err.message}`);
    } finally {
      setGradingBatch(false);
    }
  };

  const onExportCSVClick = () => {
    handleExportCSV(currentAssignmentId);
  };

  const getStatusBadge = (sub) => {
    const isGrading = isSubmissionGrading(sub);
    if (isGrading) {
      return (
        <span
          className="status-badge"
          style={{
            backgroundColor: 'rgba(59, 130, 246, 0.12)',
            color: '#1d4ed8',
            padding: '0.35rem 0.75rem',
            borderRadius: '6px',
            display: 'inline-flex',
            alignItems: 'center',
            fontWeight: 600,
            fontSize: '0.825rem',
            border: '1px solid rgba(59, 130, 246, 0.35)'
          }}
        >
          <Loader2 size={15} className="spin" style={{ marginRight: '6px', flexShrink: 0, color: '#2563eb' }} />
          AI Grading in progress...
        </span>
      );
    }

    switch (sub.status) {
      case 'graded':
        return (
          <span className="status-badge" style={{ backgroundColor: 'var(--success-bg)', color: 'var(--success)', padding: '0.25rem 0.6rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center' }}>
            <CheckCircle size={14} style={{ marginRight: '4px' }} /> Graded
          </span>
        );
      case 'flagged':
        const flagReason = sub.feedback?.flag_reasons?.[0] || sub.multi_agent_audit?.audit_note || 'Multi-Agent Quality Audit requested lecturer verification.';
        return (
          <span className="status-badge" style={{ backgroundColor: 'rgba(245, 158, 11, 0.12)', color: '#b45309', padding: '0.35rem 0.75rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center', fontWeight: 600, fontSize: '0.825rem', border: '1px solid rgba(245, 158, 11, 0.3)', maxWidth: '280px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={`Flagged for Audit: ${flagReason}`}>
            <AlertTriangle size={14} style={{ marginRight: '6px', flexShrink: 0 }} /> ⚠️ Flagged for Audit: {flagReason}
          </span>
        );
      default:
        return (
          <span className="status-badge" style={{ backgroundColor: 'var(--bg-hover)', color: 'var(--text-muted)', padding: '0.25rem 0.6rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center' }}>
            <Clock size={14} style={{ marginRight: '4px' }} /> Pending AI Grade
          </span>
        );
    }
  };

  const formatStudentName = (name, id, email) => {
    if (name && !name.includes('@') && name !== 'N/A' && !name.startsWith('Student STU')) {
      return name;
    }
    const candidate = (name && name.includes('@')) ? name : (email && email.includes('@') ? email : null);
    if (candidate) {
      const prefix = candidate.split('@')[0];
      const cleaned = prefix.split(/[._\s\-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
      if (cleaned) return cleaned;
    }
    return name && name !== 'N/A' ? name : `Student ${id || ''}`.trim();
  };

  const filteredSubmissions = submissions.filter(s => {
    const matchesFilter = filter === 'all' || s.status === filter;
    const term = searchTerm.toLowerCase();
    const matchesSearch = !searchTerm ||
      (s.student_id && s.student_id.toLowerCase().includes(term)) ||
      (s.student_name && s.student_name.toLowerCase().includes(term)) ||
      (s.student_email && s.student_email.toLowerCase().includes(term));
    return matchesFilter && matchesSearch;
  });

  const totalSubmissionsCount = submissions.length;
  const gradedCount = submissions.filter(s => s.status === 'graded').length;
  const flaggedCount = submissions.filter(s => s.status === 'flagged').length;
  const processingCount = submissions.filter(s => s.status === 'processing' || isSubmissionGrading(s)).length;
  const completedCount = gradedCount + flaggedCount;
  const isBatchActive = gradingSubIds.size > 0 || processingCount > 0;
  const progressPercent = totalSubmissionsCount > 0 ? Math.round((completedCount / totalSubmissionsCount) * 100) : 0;

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - var(--header-height) - 4rem)', overflow: 'hidden' }}>
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--primary-dark)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            Current Student Submissions
          </h2>

          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
            <button
              className={`btn ${filter === 'all' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'all' ? '' : 'transparent', color: filter === 'all' ? '' : 'var(--text-main)' }}
              onClick={() => setFilter('all')}
            >
              All ({submissions.length})
            </button>
            <button
              className={`btn ${filter === 'flagged' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'flagged' ? 'var(--warning)' : 'transparent', color: filter === 'flagged' ? '#fff' : 'var(--text-main)', border: filter === 'flagged' ? 'none' : '1px solid var(--border)' }}
              onClick={() => setFilter('flagged')}
            >
              <AlertTriangle size={14} style={{ marginRight: '4px' }} /> Flagged ({submissions.filter(s => s.status === 'flagged').length})
            </button>
            <button
              className={`btn ${filter === 'graded' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'graded' ? 'var(--success)' : 'transparent', color: filter === 'graded' ? '#fff' : 'var(--text-main)', border: filter === 'graded' ? 'none' : '1px solid var(--border)' }}
              onClick={() => setFilter('graded')}
            >
              <CheckCircle size={14} style={{ marginRight: '4px' }} /> Graded ({submissions.filter(s => s.status === 'graded').length})
            </button>
            <button
              className={`btn ${filter === 'pending' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'pending' ? 'var(--primary)' : 'transparent', color: filter === 'pending' ? '#fff' : 'var(--text-main)', border: filter === 'pending' ? 'none' : '1px solid var(--border)' }}
              onClick={() => setFilter('pending')}
            >
              <Clock size={14} style={{ marginRight: '4px' }} /> Pending ({submissions.filter(s => s.status === 'pending').length})
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            className="btn btn-outline"
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', backgroundColor: '#fff', border: '1px solid var(--border)', color: 'var(--primary-dark)', padding: '0.5rem 0.9rem', fontSize: '0.875rem', fontWeight: 600 }}
            onClick={onExportCSVClick}
            title="Download full student grades as a CSV spreadsheet"
          >
            <Download size={16} color="var(--primary)" /> Export Grades (CSV)
          </button>

          <button
            className="btn btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: 'var(--primary)', padding: '0.5rem 1rem' }}
            onClick={handleGradeAllBatch}
            disabled={isBatchActive}
          >
            {isBatchActive ? (
              <>
                <Loader2 size={16} className="spin" /> Grading ({completedCount}/{totalSubmissionsCount})...
              </>
            ) : (
              <>
                <Sparkles size={16} /> Grade All Pending (AI)
              </>
            )}
          </button>

          <div style={{ position: 'relative' }}>
            <Search size={18} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              className="input-field"
              placeholder="Search Student Name / ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ paddingLeft: '2.5rem', width: '220px' }}
            />
          </div>
        </div>
      </div>

      {/* Live AI Batch Grading Progress Banner */}
      {isBatchActive && (
        <div style={{
          margin: '1rem 1.5rem 0',
          padding: '1rem 1.25rem',
          borderRadius: '8px',
          backgroundColor: '#eff6ff',
          border: '1px solid #bfdbfe',
          boxShadow: '0 2px 4px rgba(37, 99, 235, 0.06)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Loader2 size={18} className="spin" color="#2563eb" />
              <strong style={{ color: '#1e40af', fontSize: '0.95rem' }}>
                AI Multi-Agent Pipeline Active
              </strong>
            </div>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#1e40af' }}>
              {completedCount} / {totalSubmissionsCount} Submissions Completed ({progressPercent}%)
            </span>
          </div>

          <div style={{ width: '100%', height: '8px', backgroundColor: '#dbeafe', borderRadius: '4px', overflow: 'hidden', marginBottom: '0.65rem' }}>
            <div style={{ width: `${Math.max(5, progressPercent)}%`, height: '100%', backgroundColor: '#2563eb', transition: 'width 0.4s ease' }} />
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', fontSize: '0.75rem', color: '#1e40af' }}>
            <span style={{ fontWeight: 700 }}>Active Stages:</span>
            <span style={{ padding: '0.15rem 0.5rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px solid #bfdbfe', fontWeight: 600 }}>1. Text Extraction</span>
            <span>➔</span>
            <span style={{ padding: '0.15rem 0.5rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px solid #bfdbfe', fontWeight: 600 }}>2. ChromaDB RAG</span>
            <span>➔</span>
            <span style={{ padding: '0.15rem 0.5rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px solid #bfdbfe', fontWeight: 600 }}>3. Primary Grader & Auditor LLM</span>
            <span>➔</span>
            <span style={{ padding: '0.15rem 0.5rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px solid #bfdbfe', fontWeight: 600 }}>4. Confidence & Reconciliation</span>
          </div>
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--bg-main)', zIndex: 1, borderBottom: '2px solid var(--border)' }}>
            <tr>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Student</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>File Name</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>AI Score</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Status</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredSubmissions.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                  No submissions found matching criteria.
                </td>
              </tr>
            ) : (
              filteredSubmissions.map((sub) => {
                const isGrading = isSubmissionGrading(sub);
                return (
                  <tr
                    key={sub.id}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      cursor: isGrading ? 'wait' : 'pointer',
                      transition: 'background-color 0.2s ease',
                      backgroundColor: isGrading
                        ? 'rgba(59, 130, 246, 0.06)'
                        : sub.status === 'flagged'
                          ? 'rgba(245, 158, 11, 0.02)'
                          : 'transparent'
                    }}
                    onMouseOver={(e) => {
                      if (!isGrading && sub.status !== 'flagged') e.currentTarget.style.backgroundColor = 'var(--bg-hover)';
                    }}
                    onMouseOut={(e) => {
                      e.currentTarget.style.backgroundColor = isGrading
                        ? 'rgba(59, 130, 246, 0.06)'
                        : sub.status === 'flagged'
                          ? 'rgba(245, 158, 11, 0.02)'
                          : 'transparent';
                    }}
                    onClick={() => {
                      if (!isGrading) {
                        navigate(`/review`, { state: { submission: sub } });
                      }
                    }}
                  >
                    <td style={{ padding: '1.2rem 1.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <div style={{ fontWeight: 600, color: 'var(--primary)' }}>
                          {formatStudentName(sub.student_name, sub.student_id, sub.student_email)}
                        </div>
                        {isGrading && (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              fontSize: '0.75rem',
                              padding: '0.15rem 0.5rem',
                              borderRadius: '12px',
                              backgroundColor: 'rgba(59, 130, 246, 0.12)',
                              color: '#1d4ed8',
                              fontWeight: 600
                            }}
                          >
                            <Loader2 size={12} className="spin" /> Grading AI...
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.15rem' }}>
                        <span>ID: <strong>{sub.student_id}</strong></span>
                        <span>•</span>
                        <span>Email: <strong>{sub.student_email || 'N/A'}</strong></span>
                      </div>
                    </td>
                    <td style={{ padding: '1.2rem 1.5rem', color: 'var(--text-main)', fontSize: '0.9rem' }}>{sub.file_name}</td>
                    <td style={{ padding: '1.2rem 1.5rem', fontWeight: 600 }}>
                      {isGrading ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#2563eb', fontSize: '0.85rem', fontStyle: 'italic' }}>
                          <Loader2 size={13} className="spin" /> Evaluating...
                        </span>
                      ) : sub.score != null ? (
                        <span>{sub.score} <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.875rem' }}>/ {getSubmissionMaxScore(sub)}</span></span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Unassessed</span>
                      )}
                    </td>
                    <td style={{ padding: '1.2rem 1.5rem' }}>{getStatusBadge(sub)}</td>
                    <td style={{ padding: '1.2rem 1.5rem' }}>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {isGrading ? (
                          <button
                            className="btn"
                            disabled
                            style={{
                              padding: '0.4rem 0.85rem',
                              fontSize: '0.85rem',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.4rem',
                              backgroundColor: 'rgba(59, 130, 246, 0.12)',
                              color: '#1d4ed8',
                              border: '1px solid rgba(59, 130, 246, 0.3)',
                              cursor: 'wait',
                              fontWeight: 600
                            }}
                          >
                            <Loader2 size={14} className="spin" /> AI Running...
                          </button>
                        ) : (sub.status === 'pending' || sub.status === 'uploaded') ? (
                          <button
                            className="btn btn-primary"
                            style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
                            onClick={(e) => handleGradeSingle(e, sub.id)}
                          >
                            <Play size={14} /> Grade with AI
                          </button>
                        ) : null}
                        <button
                          className={`btn ${sub.status === 'flagged' ? 'btn-primary' : ''}`}
                          disabled={isGrading}
                          style={{
                            padding: '0.4rem 0.8rem',
                            fontSize: '0.85rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            background: sub.status === 'flagged' ? 'var(--warning)' : 'var(--bg-main)',
                            color: sub.status === 'flagged' ? '#fff' : 'var(--text-main)',
                            border: sub.status === 'flagged' ? 'none' : '1px solid var(--border)',
                            opacity: isGrading ? 0.6 : 1,
                            cursor: isGrading ? 'not-allowed' : 'pointer'
                          }}
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/review`, { state: { submission: sub } });
                          }}
                        >
                          Review <ChevronRight size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SubmissionsList;
