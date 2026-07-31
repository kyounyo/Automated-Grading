import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter, ChevronRight, AlertCircle, CheckCircle, Clock, AlertTriangle, ShieldCheck } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const SubmissionsList = () => {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const { currentData } = useAssignment();
  const mockStudents = currentData.students;

  const getStatusBadge = (student) => {
    switch (student.status) {
      case 'auto-approved':
        return <span className="status-badge" style={{ backgroundColor: 'var(--success-bg)', color: 'var(--success)' }}><CheckCircle size={14} style={{ marginRight: '4px' }} /> Auto-Approved</span>;
      case 'action-required':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            <span className="status-badge" style={{ backgroundColor: 'rgba(245, 158, 11, 0.1)', color: 'var(--warning)', width: 'fit-content' }}>
              <AlertTriangle size={14} style={{ marginRight: '4px' }} /> Action Required
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{student.flagReason}</span>
          </div>
        );
      case 'reviewed':
        return <span className="status-badge" style={{ backgroundColor: 'var(--bg-main)', color: 'var(--primary)' }}><ShieldCheck size={14} style={{ marginRight: '4px' }} /> Manually Reviewed</span>;
      default:
        return <span className="status-badge" style={{ backgroundColor: 'var(--bg-hover)', color: 'var(--text-muted)' }}><Clock size={14} style={{ marginRight: '4px' }} /> Pending</span>;
    }
  };

  const filteredStudents = mockStudents.filter(s => filter === 'all' || s.status === filter);

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - var(--header-height) - 4rem)', overflow: 'hidden' }}>
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--primary-dark)' }}>Current Submissions</h2>

          <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
            <button
              className={`btn ${filter === 'all' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'all' ? '' : 'transparent', color: filter === 'all' ? '' : 'var(--text-main)' }}
              onClick={() => setFilter('all')}
            >
              All (170)
            </button>
            <button
              className={`btn ${filter === 'action-required' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'action-required' ? 'var(--warning)' : 'transparent', color: filter === 'action-required' ? '#fff' : 'var(--text-main)', border: filter === 'action-required' ? 'none' : '1px solid var(--border)' }}
              onClick={() => setFilter('action-required')}
            >
              <AlertTriangle size={14} style={{ marginRight: '4px' }} /> Action Required (18)
            </button>
            <button
              className={`btn ${filter === 'auto-approved' ? 'btn-primary' : ''}`}
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.875rem', background: filter === 'auto-approved' ? 'var(--success)' : 'transparent', color: filter === 'auto-approved' ? '#fff' : 'var(--text-main)', border: filter === 'auto-approved' ? 'none' : '1px solid var(--border)' }}
              onClick={() => setFilter('auto-approved')}
            >
              <CheckCircle size={14} style={{ marginRight: '4px' }} /> Auto-Approved (152)
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '1rem' }}>
          <div style={{ position: 'relative' }}>
            <Search size={18} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input type="text" className="input-field" placeholder="Search ID..." style={{ paddingLeft: '2.5rem', width: '250px' }} />
          </div>
          <button className="btn" style={{ background: 'var(--bg-main)', border: '1px solid var(--border)' }}>
            <Filter size={18} /> Filter
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--bg-main)', zIndex: 1, borderBottom: '2px solid var(--border)' }}>
            <tr>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Student ID</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Submitted At</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>AI Score</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Status</th>
              <th style={{ padding: '1rem 1.5rem', color: 'var(--text-muted)', fontWeight: 600 }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredStudents.map((student) => (
              <tr key={student.id} style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer', transition: 'background-color 0.2s', backgroundColor: student.status === 'action-required' ? 'rgba(245, 158, 11, 0.02)' : 'transparent' }}
                onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-hover)'}
                onMouseOut={(e) => e.currentTarget.style.backgroundColor = student.status === 'action-required' ? 'rgba(245, 158, 11, 0.02)' : 'transparent'}
                onClick={() => navigate(`/review`, { state: { student } })}
              >
                <td style={{ padding: '1.2rem 1.5rem', fontWeight: 500, color: 'var(--primary)' }}>{student.id}</td>
                <td style={{ padding: '1.2rem 1.5rem', color: 'var(--text-main)' }}>{student.submittedAt}</td>
                <td style={{ padding: '1.2rem 1.5rem', fontWeight: 600 }}>{student.score} <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.875rem' }}>/ 100</span></td>
                <td style={{ padding: '1.2rem 1.5rem' }}>{getStatusBadge(student)}</td>
                <td style={{ padding: '1.2rem 1.5rem' }}>
                  <button className={`btn ${student.status === 'action-required' ? 'btn-primary' : ''}`} style={{ padding: '0.4rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', background: student.status === 'action-required' ? 'var(--warning)' : 'var(--bg-main)', color: student.status === 'action-required' ? '#fff' : 'var(--text-main)', border: student.status === 'action-required' ? 'none' : '1px solid var(--border)' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/review`, { state: { student } });
                    }}
                  >
                    Review <ChevronRight size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SubmissionsList;
