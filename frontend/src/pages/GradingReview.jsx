import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle, AlertTriangle, Edit3, ShieldAlert, Cpu, Clock, Layers, Save, FileText } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const GradingReview = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { submissions, handleScoreOverride, triggerGradeSubmission } = useAssignment();

  // Selected submission from router state or default to first submission
  const navSubmission = location.state?.submission;
  const currentSubId = navSubmission?.id || (submissions.length > 0 ? submissions[0].id : null);
  const activeSubmission = submissions.find(s => s.id === currentSubId) || navSubmission;

  const [overrideScore, setOverrideScore] = useState('');
  const [overrideComment, setOverrideComment] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (activeSubmission && activeSubmission.score != null) {
      setOverrideScore(activeSubmission.score.toString());
    }
  }, [activeSubmission]);

  if (!activeSubmission) {
    return (
      <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center' }}>
        <h2>No Submission Selected</h2>
        <button className="btn btn-primary" onClick={() => navigate('/submissions')} style={{ marginTop: '1rem' }}>
          Return to Submissions List
        </button>
      </div>
    );
  }

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    const newScore = parseFloat(overrideScore);
    if (isNaN(newScore) || newScore < 0 || newScore > 100) {
      alert("Please enter a valid score between 0 and 100.");
      return;
    }

    try {
      setSaving(true);
      await handleScoreOverride(activeSubmission.id, newScore, overrideComment);
      alert("Grade overridden successfully! Audit log record saved into PostgreSQL.");
      setOverrideComment('');
    } catch (err) {
      alert(`Override failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleGradeWithAI = async () => {
    try {
      setSaving(true);
      await triggerGradeSubmission(activeSubmission.id);
      alert("AI grading pipeline completed successfully!");
    } catch (err) {
      alert(`AI grading failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const feedback = activeSubmission.feedback || {};
  const breakdown = feedback.breakdown || [];
  const highlights = activeSubmission.highlights || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', paddingBottom: '2rem' }}>
      
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button 
          className="btn" 
          onClick={() => navigate('/submissions')}
          style={{ background: 'var(--bg-main)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <ArrowLeft size={18} /> Back to Submissions
        </button>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {activeSubmission.status === 'pending' && (
            <button className="btn btn-primary" onClick={handleGradeWithAI} disabled={saving}>
              Run AI Grading Pipeline
            </button>
          )}
          <span className="status-badge" style={{ backgroundColor: activeSubmission.status === 'flagged' ? 'rgba(245, 158, 11, 0.1)' : 'var(--success-bg)', color: activeSubmission.status === 'flagged' ? 'var(--warning)' : 'var(--success)', padding: '0.5rem 1rem', fontSize: '0.9rem', fontWeight: 600 }}>
            {activeSubmission.status === 'flagged' ? '⚠️ Flagged for Audit' : '✓ Graded'}
          </span>
        </div>
      </div>

      {/* Main Grid: Left Side Submission Info & Rubric, Right Side Override Panel */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>
        
        {/* Left Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {/* Submission Details Banner */}
          <div className="glass-panel" style={{ padding: '1.5rem', borderLeft: '4px solid var(--primary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ margin: 0, color: 'var(--primary-dark)' }}>{activeSubmission.student_name}</h2>
                <p style={{ margin: '0.2rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  Student ID: <strong>{activeSubmission.student_id}</strong> | File: <strong>{activeSubmission.file_name}</strong>
                </p>
              </div>

              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--primary)' }}>
                  {activeSubmission.score != null ? activeSubmission.score : 'N/A'} <span style={{ fontSize: '1rem', color: 'var(--text-muted)' }}>/ 100</span>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Confidence: {activeSubmission.confidence_score ? `${Math.round(activeSubmission.confidence_score * 100)}%` : 'N/A'}
                </div>
              </div>
            </div>
          </div>

          {/* Extracted Student Submission Content (Verification View) */}
          <div className="glass-panel" style={{ padding: '1.5rem', backgroundColor: 'rgba(244, 247, 249, 0.7)', borderLeft: '4px solid var(--primary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <FileText size={20} color="var(--primary)" /> Extracted Student Submission Content (Verification View)
              </h3>
              <span className="status-badge" style={{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)', fontSize: '0.8rem', fontWeight: 600 }}>
                Verification Mode
              </span>
            </div>
            <pre style={{ 
              margin: 0, 
              padding: '1rem', 
              backgroundColor: '#fff', 
              border: '1px solid var(--border)', 
              borderRadius: '8px', 
              fontSize: '0.875rem', 
              lineHeight: '1.6', 
              whiteSpace: 'pre-wrap', 
              fontFamily: 'monospace',
              maxHeight: '350px',
              overflowY: 'auto'
            }}>
              {activeSubmission.raw_text || activeSubmission.extracted_text || `Student Response for ${activeSubmission.student_name} (${activeSubmission.student_id}):\n(File: ${activeSubmission.file_name})\n\nQuestion Q6:\n(a) Advantages: May be biodegradable - do not need removal. Provides longer release duration. Disadvantages: Limited to non-acid labile. (b) In situ gelling attributes: Systems contain solvent...\n\nQuestion Q8:\n(a) Disagree: Lyophilization is not necessary if drug is stable in solution...`}
            </pre>
          </div>

          {/* AI Overall Summary */}
          {feedback.summary && (
            <div className="glass-panel" style={{ padding: '1.5rem', backgroundColor: 'var(--bg-main)' }}>
              <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--secondary)' }}>AI Evaluation Summary</h3>
              <p style={{ margin: 0, color: 'var(--text-main)', lineHeight: '1.6' }}>{feedback.summary}</p>
            </div>
          )}

          {/* Rubric Breakdown */}
          <div className="glass-panel" style={{ padding: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', color: 'var(--secondary)' }}>Rubric Criteria & AI Reasoning Breakdown</h3>
            {breakdown.length === 0 ? (
              <p style={{ color: 'var(--text-muted)' }}>No breakdown data available.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {breakdown.map((item, index) => (
                  <div key={index} style={{ padding: '1rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--bg-main)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <strong style={{ color: 'var(--primary)' }}>{item.question_number}</strong>
                      <span style={{ fontWeight: 600 }}>{item.score_awarded} / {item.max_score} marks</span>
                    </div>
                    <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-main)' }}>{item.reasoning}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Targeted Text Highlights */}
          {highlights.length > 0 && (
            <div className="glass-panel" style={{ padding: '1.5rem' }}>
              <h3 style={{ margin: '0 0 1rem 0', color: 'var(--secondary)' }}>Targeted Text Highlights & Reasoning</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {highlights.map((hl, i) => (
                  <div key={i} style={{ padding: '0.75rem 1rem', borderRadius: '6px', backgroundColor: hl.type === 'strength' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)', borderLeft: `4px solid ${hl.type === 'strength' ? 'var(--success)' : '#ef4444'}` }}>
                    <div style={{ fontStyle: 'italic', fontSize: '0.9rem', color: 'var(--text-main)', marginBottom: '0.3rem' }}>"{hl.text}"</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>💡 <strong>Reasoning:</strong> {hl.comment}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>

        {/* Right Column: Lecturer Manual Score Override Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <div className="glass-panel" style={{ padding: '1.5rem', position: 'sticky', top: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Edit3 size={18} /> Lecturer Grade Override
            </h3>

            <form onSubmit={handleOverrideSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.4rem', color: 'var(--text-main)' }}>
                  New Final Score (0 - 100)
                </label>
                <input 
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  className="input-field"
                  value={overrideScore}
                  onChange={(e) => setOverrideScore(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', fontSize: '1.1rem', fontWeight: 600 }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.4rem', color: 'var(--text-main)' }}>
                  Audit Comment / Justification
                </label>
                <textarea 
                  rows={4}
                  className="input-field"
                  placeholder="Explain reason for grade adjustment (e.g. Granted partial credit for boundary case method)..."
                  value={overrideComment}
                  onChange={(e) => setOverrideComment(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', fontSize: '0.9rem' }}
                />
              </div>

              <button 
                type="submit" 
                className="btn btn-primary" 
                disabled={saving}
                style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', width: '100%', padding: '0.75rem' }}
              >
                <Save size={18} /> {saving ? 'Saving to Database...' : 'Save Grade & Record Audit Log'}
              </button>
            </form>

            <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              🔒 <strong>Audit Assurance:</strong> All grade overrides are recorded permanently in PostgreSQL audit logs for rater reliability verification.
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};

export default GradingReview;
