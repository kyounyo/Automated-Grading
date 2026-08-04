import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter, ChevronRight, CheckCircle, Clock, AlertTriangle, Play, Sparkles, RefreshCw } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const SubmissionsList = () => {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [gradingBatch, setGradingBatch] = useState(false);
  const { currentAssignmentId, submissions, triggerGradeSubmission, triggerGradeAll, loadSubmissions } = useAssignment();

  const handleGradeSingle = async (e, subId) => {
    e.stopPropagation();
    try {
      await triggerGradeSubmission(subId);
    } catch (err) {
      alert(`Grading failed: ${err.message}`);
    }
  };

  const handleGradeAllBatch = async () => {
    try {
      setGradingBatch(true);
      await triggerGradeAll(currentAssignmentId);
      alert("Asynchronous batch AI grading initiated! Submissions are now processing in the background.");
    } catch (err) {
      alert(`Batch grading failed: ${err.message}`);
    } finally {
      setGradingBatch(false);
    }
  };

  const getStatusBadge = (sub) => {
    switch (sub.status) {
      case 'graded':
        return (
          <span className="status-badge" style={{ backgroundColor: 'var(--success-bg)', color: 'var(--success)', padding: '0.25rem 0.6rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center' }}>
            <CheckCircle size={14} style={{ marginRight: '4px' }} /> Graded ({sub.confidence_score ? Math.round(sub.confidence_score * 100) : 90}% Conf)
          </span>
        );
      case 'flagged':
        return (
          <span className="status-badge" style={{ backgroundColor: 'rgba(245, 158, 11, 0.1)', color: 'var(--warning)', padding: '0.25rem 0.6rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center' }}>
            <AlertTriangle size={14} style={{ marginRight: '4px' }} /> Flagged for Review
          </span>
        );
      case 'processing':
        return (
          <span className="status-badge" style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)', color: '#2563eb', padding: '0.25rem 0.6rem', borderRadius: '4px', display: 'inline-flex', alignItems: 'center' }}>
            <RefreshCw size={14} className="spin" style={{ marginRight: '4px' }} /> Processing...
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

  const filteredSubmissions = submissions.filter(s => {
    const matchesFilter = filter === 'all' || s.status === filter;
    const matchesSearch = !searchTerm || s.student_id.toLowerCase().includes(searchTerm.toLowerCase()) || s.student_name.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesFilter && matchesSearch;
  });

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

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <button 
            className="btn btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: 'var(--primary)', padding: '0.5rem 1rem' }}
            onClick={handleGradeAllBatch}
            disabled={gradingBatch}
          >
            <Sparkles size={16} /> {gradingBatch ? 'Initiating Batch...' : 'Grade All Pending (AI)'}
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
              filteredSubmissions.map((sub) => (
                <tr 
                  key={sub.id} 
                  style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer', transition: 'background-color 0.2s', backgroundColor: sub.status === 'flagged' ? 'rgba(245, 158, 11, 0.02)' : 'transparent' }}
                  onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-hover)'}
                  onMouseOut={(e) => e.currentTarget.style.backgroundColor = sub.status === 'flagged' ? 'rgba(245, 158, 11, 0.02)' : 'transparent'}
                  onClick={() => navigate(`/review`, { state: { submission: sub } })}
                >
                  <td style={{ padding: '1.2rem 1.5rem' }}>
                    <div style={{ fontWeight: 600, color: 'var(--primary)' }}>{sub.student_name}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>ID: {sub.student_id}</div>
                  </td>
                  <td style={{ padding: '1.2rem 1.5rem', color: 'var(--text-main)', fontSize: '0.9rem' }}>{sub.file_name}</td>
                  <td style={{ padding: '1.2rem 1.5rem', fontWeight: 600 }}>
                    {sub.score != null ? (
                      <span>{sub.score} <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.875rem' }}>/ 100</span></span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Unassessed</span>
                    )}
                  </td>
                  <td style={{ padding: '1.2rem 1.5rem' }}>{getStatusBadge(sub)}</td>
                  <td style={{ padding: '1.2rem 1.5rem' }}>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      {sub.status === 'pending' && (
                        <button 
                          className="btn btn-primary" 
                          style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
                          onClick={(e) => handleGradeSingle(e, sub.id)}
                        >
                          <Play size={14} /> Grade with AI
                        </button>
                      )}
                      <button 
                        className={`btn ${sub.status === 'flagged' ? 'btn-primary' : ''}`} 
                        style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.3rem', background: sub.status === 'flagged' ? 'var(--warning)' : 'var(--bg-main)', color: sub.status === 'flagged' ? '#fff' : 'var(--text-main)', border: sub.status === 'flagged' ? 'none' : '1px solid var(--border)' }}
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
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SubmissionsList;
