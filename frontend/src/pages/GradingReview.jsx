import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle, AlertTriangle, Edit3, ShieldAlert, Cpu, Clock, Layers, Save, FileText, ChevronDown, ChevronUp, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const GradingReview = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentAssignment, submissions, handleScoreOverride, triggerGradeSubmission } = useAssignment();

  // Selected submission from router state or default to first submission
  const navSubmission = location.state?.submission;
  const currentSubId = navSubmission?.id || (submissions.length > 0 ? submissions[0].id : null);
  const activeSubmission = submissions.find(s => s.id === currentSubId) || navSubmission;

  const [overrideScore, setOverrideScore] = useState('');
  const [overrideComment, setOverrideComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [showRawContent, setShowRawContent] = useState(true);
  const [questionScores, setQuestionScores] = useState({});
  const [activeHighlightPop, setActiveHighlightPop] = useState(null);

  useEffect(() => {
    if (activeSubmission) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      if (activeSubmission.score != null) {
        setOverrideScore(activeSubmission.score.toString());
      }
      const feedback = activeSubmission.feedback || {};
      const breakdown = feedback.breakdown || [];
      const initialScores = {};
      breakdown.forEach((item, idx) => {
        const qKey = item.question_number || `Q${idx + 1}`;
        initialScores[qKey] = item.score_awarded != null ? item.score_awarded : 0;
      });
      setQuestionScores(initialScores);
      setActiveHighlightPop(null);
    }
  }, [activeSubmission?.id]);

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

  // Calculate next and previous submission targets
  const currentIndex = submissions.findIndex(s => s.id === activeSubmission.id);
  const prevSubmission = currentIndex > 0 ? submissions[currentIndex - 1] : null;
  const nextSubmission = currentIndex >= 0 && currentIndex < submissions.length - 1 ? submissions[currentIndex + 1] : null;

  const navigateToSubmission = (targetSub) => {
    if (targetSub) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      navigate('/review', { state: { submission: targetSub }, replace: true });
    }
  };

  const feedback = activeSubmission.feedback || {};
  const rawBreakdown = feedback.breakdown || [];
  const highlights = activeSubmission.highlights || [];

  const breakdown = rawBreakdown.length > 0
    ? rawBreakdown
    : (currentAssignment?.rubric_data && currentAssignment.rubric_data.length > 0
      ? currentAssignment.rubric_data.map((r, idx) => ({
          question_number: r.question_number || r.criterion || `Q${idx + 1}`,
          score_awarded: 0.0,
          max_score: parseFloat(r.max_score || r.maxMark || 5.0),
          reasoning: "Rubric criteria loaded. Pending AI grading evaluation."
        }))
      : []);

  const totalMaxScore = breakdown.length > 0
    ? breakdown.reduce((acc, item) => acc + (parseFloat(item.max_score) || 0), 0)
    : (currentAssignment?.rubric_data && currentAssignment.rubric_data.length > 0
      ? currentAssignment.rubric_data.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0)
      : null);

  const calculatedTotalFromQuestions = breakdown.length > 0
    ? breakdown.reduce((sum, item, idx) => {
      const qKey = item.question_number || `Q${idx + 1}`;
      const val = parseFloat(questionScores[qKey]);
      return sum + (isNaN(val) ? 0 : val);
    }, 0)
    : (activeSubmission.score ?? 0);

  const handlePerQuestionScoreChange = (qKey, maxScore, valStr) => {
    setQuestionScores(prev => ({
      ...prev,
      [qKey]: valStr
    }));
  };

  const handleSaveQuestionOverrides = async (e) => {
    if (e) e.preventDefault();
    try {
      setSaving(true);
      const updatedBreakdown = breakdown.map((item, idx) => {
        const qKey = item.question_number || `Q${idx + 1}`;
        const rawVal = parseFloat(questionScores[qKey]);
        const validVal = isNaN(rawVal) ? 0 : Math.max(0, Math.min(item.max_score, rawVal));
        return {
          ...item,
          score_awarded: Math.round(validVal * 10) / 10
        };
      });

      const newTotal = updatedBreakdown.reduce((acc, curr) => acc + curr.score_awarded, 0);
      await handleScoreOverride(activeSubmission.id, newTotal, overrideComment || "Per-question manual mark adjustment by lecturer", updatedBreakdown);
      alert(`Question marks updated successfully! Final submission score is now ${newTotal} / ${totalMaxScore}.`);
    } catch (err) {
      alert(`Override failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    const newScore = parseFloat(overrideScore);
    if (isNaN(newScore) || newScore < 0 || (totalMaxScore && newScore > totalMaxScore)) {
      alert(`Please enter a valid score between 0 and ${totalMaxScore || 100}.`);
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

  const renderHighlightedRawText = (rawText, highlightsList) => {
    const isBlank = !rawText || rawText.trim() === '' || rawText.trim() === '-' || rawText.trim() === 'N/A';
    if (isBlank) {
      return (
        <div style={{ padding: '1.5rem', backgroundColor: 'rgba(239, 68, 68, 0.06)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)', textAlign: 'center' }}>
          <AlertTriangle size={24} color="#ef4444" style={{ marginBottom: '0.4rem' }} />
          <h4 style={{ margin: '0 0 0.25rem 0', color: '#991b1b' }}>Blank / Empty Student Submission Response</h4>
          <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            Student provided no text response ('-'). 0.0 marks awarded across all questions.
          </p>
        </div>
      );
    }

    if (!highlightsList || highlightsList.length === 0) {
      return (
        <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', lineHeight: '1.7', fontSize: '0.875rem', color: 'var(--text-main)', backgroundColor: '#fff', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
          {rawText}
        </div>
      );
    }

    const sortedHighlights = [...highlightsList].filter(h => h.text && h.text.trim().length > 3);
    let parts = [rawText];

    sortedHighlights.forEach((hl, idx) => {
      const quote = hl.text ? hl.text.trim() : '';
      if (!quote) return;
      const newParts = [];

      parts.forEach(part => {
        if (typeof part !== 'string') {
          newParts.push(part);
          return;
        }

        let matchIdx = part.toLowerCase().indexOf(quote.toLowerCase());
        let matchLen = quote.length;

        if (matchIdx === -1 && quote.length > 15) {
          const subKey = quote.slice(0, Math.min(25, quote.length)).toLowerCase();
          matchIdx = part.toLowerCase().indexOf(subKey);
          if (matchIdx !== -1) {
            matchLen = Math.min(quote.length, part.length - matchIdx);
          }
        }

        if (matchIdx === -1 && quote.length > 5) {
          const words = quote.split(/\s+/).filter(w => w.length > 2);
          if (words.length > 0) {
            const firstWord = words[0].toLowerCase();
            matchIdx = part.toLowerCase().indexOf(firstWord);
            if (matchIdx !== -1) {
              matchLen = Math.min(quote.length, part.length - matchIdx);
            }
          }
        }

        if (matchIdx === -1) {
          newParts.push(part);
        } else {
          const before = part.slice(0, matchIdx);
          const matchedStr = part.slice(matchIdx, matchIdx + matchLen);
          const after = part.slice(matchIdx + matchLen);

          if (before) newParts.push(before);

          const isStrength = hl.type === 'strength' || (hl.score_awarded && hl.score_awarded > 0);
          newParts.push(
            <mark
              key={`${idx}-${matchIdx}`}
              onClick={(e) => {
                e.stopPropagation();
                setActiveHighlightPop(hl);
              }}
              style={{
                backgroundColor: isStrength ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)',
                color: isStrength ? '#065f46' : '#991b1b',
                borderBottom: `3px solid ${isStrength ? 'var(--success)' : '#ef4444'}`,
                borderRadius: '4px',
                padding: '0.2rem 0.45rem',
                margin: '0 0.15rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {matchedStr}
              <span style={{
                fontSize: '0.725rem',
                marginLeft: '0.35rem',
                padding: '0.1rem 0.4rem',
                borderRadius: '3px',
                backgroundColor: isStrength ? 'var(--success)' : '#ef4444',
                color: '#fff',
                fontWeight: 700
              }}>
                {hl.question_number ? `${hl.question_number} ` : ''}{hl.score_awarded != null ? `+${hl.score_awarded} marks` : (isStrength ? '✓ Earned' : '0 marks')}
              </span>
            </mark>
          );

          if (after) newParts.push(after);
        }
      });

      parts = newParts;
    });

    return (
      <div style={{ position: 'relative' }}>
        <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', lineHeight: '1.8', fontSize: '0.875rem', color: 'var(--text-main)', backgroundColor: '#fff', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border)', maxHeight: '450px', overflowY: 'auto' }}>
          {parts}
        </div>

        {/* Interactive Click Popover Card for Highlighted Text */}
        {activeHighlightPop && (
          <div
            style={{
              marginTop: '0.85rem',
              padding: '1rem 1.25rem',
              backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
              borderLeft: `5px solid ${activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'var(--success)' : '#ef4444'}`,
              borderRadius: '8px',
              border: '1px solid var(--border)',
              position: 'relative'
            }}
          >
            <button
              type="button"
              onClick={() => setActiveHighlightPop(null)}
              style={{ position: 'absolute', top: '0.6rem', right: '0.8rem', background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '1rem', color: 'var(--text-muted)' }}
            >
              ✕
            </button>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem', paddingRight: '1.5rem' }}>
              <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--primary-dark)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Layers size={16} color="var(--primary)" /> {activeHighlightPop.question_number ? (activeHighlightPop.question_number.startsWith('Q') ? `Question ${activeHighlightPop.question_number}` : `Question Q${activeHighlightPop.question_number}`) : 'Question Mark Evidence'}
              </span>
              <span style={{ fontSize: '0.825rem', fontWeight: 700, padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)', color: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? '#065f46' : '#991b1b' }}>
                {activeHighlightPop.score_awarded != null ? `+${activeHighlightPop.score_awarded} Marks` : 'Marks Feedback'}
              </span>
            </div>

            <div style={{ fontStyle: 'italic', fontSize: '0.875rem', color: 'var(--text-main)', marginBottom: '0.4rem', padding: '0.4rem 0.6rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px dashed var(--border)' }}>
              📄 <strong>Selected Student Quote:</strong> "{activeHighlightPop.text}"
            </div>

            <div style={{ fontSize: '0.85rem', color: 'var(--text-main)', lineHeight: '1.55' }}>
              💡 <strong>Feedback & Rubric Reason:</strong> {activeHighlightPop.comment}
            </div>
          </div>
        )}
      </div>
    );
  };

  const rawStudentText = activeSubmission.raw_text || activeSubmission.extracted_text || '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', paddingBottom: '2rem' }}>

      {/* Top Header Banner with Student Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn"
            onClick={() => navigate('/submissions')}
            style={{ background: 'var(--bg-main)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <ArrowLeft size={18} /> Back to Submissions
          </button>
        </div>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {activeSubmission.status === 'pending' && (
            <button className="btn btn-primary" onClick={handleGradeWithAI} disabled={saving}>
              Run AI Grading Pipeline
            </button>
          )}
          <span className="status-badge" style={{ backgroundColor: activeSubmission.status === 'flagged' ? 'rgba(245, 158, 11, 0.12)' : 'var(--success-bg)', color: activeSubmission.status === 'flagged' ? '#b45309' : 'var(--success)', padding: '0.5rem 1rem', fontSize: '0.9rem', fontWeight: 600, border: activeSubmission.status === 'flagged' ? '1px solid rgba(245, 158, 11, 0.3)' : 'none' }}>
            {activeSubmission.status === 'flagged'
              ? `⚠️ Flagged for Audit: ${feedback.flag_reasons?.[0] || activeSubmission.multi_agent_audit?.audit_note || 'Multi-Agent Quality Audit requested lecturer verification.'}`
              : '✓ Graded'}
          </span>
        </div>
      </div>

      {/* Main Grid: Left Side Submission Info & Rubric, Right Side Override Panel */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>

        {/* Left Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

          {/* Sticky Freeze Student Information Details Banner */}
          <div 
            className="glass-panel" 
            style={{ 
              padding: '0.9rem 1.25rem', 
              borderLeft: '4px solid var(--primary)',
              position: 'sticky',
              top: '1rem',
              zIndex: 10,
              backgroundColor: '#fff',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.05)'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, color: 'var(--primary-dark)', fontSize: '1.15rem' }}>{activeSubmission.student_name || `Student ${activeSubmission.student_id}`}</h3>
                <p style={{ margin: '0.15rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.825rem' }}>
                  Student ID: <strong>{activeSubmission.student_id}</strong> | Email: <strong>{activeSubmission.student_email || 'N/A'}</strong> | File: <strong>{activeSubmission.file_name}</strong>
                </p>
              </div>

              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--primary)' }}>
                  {activeSubmission.score != null ? activeSubmission.score : 'N/A'} <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 400 }}>{totalMaxScore ? `/ ${totalMaxScore}` : ''}</span>
                </div>
                <div style={{ fontSize: '0.75rem', color: activeSubmission.confidence_score < 0.75 ? 'var(--warning)' : 'var(--text-muted)', fontWeight: activeSubmission.confidence_score < 0.75 ? 600 : 400 }}>
                  Confidence: {activeSubmission.confidence_score ? `${Math.round(activeSubmission.confidence_score * 100)}%` : 'N/A'}
                  {activeSubmission.confidence_score < 0.75 && ' ⚠️ (Lowered by Multi-Agent Discrepancy)'}
                </div>
              </div>
            </div>
          </div>

          {/* Full Raw Text View with Inline Mark Highlights */}
          <div
            className="glass-panel"
            style={{
              padding: '1.25rem 1.5rem',
              backgroundColor: 'rgba(244, 247, 249, 0.7)',
              borderLeft: '4px solid var(--primary)'
            }}
          >
            <div
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', marginBottom: showRawContent ? '1rem' : 0 }}
              onClick={() => setShowRawContent(!showRawContent)}
            >
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.05rem' }}>
                <FileText size={18} color="var(--primary)" /> Full Student Raw Text & Highlighted Mark Evidence
              </h3>
              <button
                type="button"
                className="btn btn-outline"
                style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem', pointerEvents: 'none' }}
              >
                {showRawContent ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                {showRawContent ? 'Hide Full Submission' : 'View Full Submission'}
              </button>
            </div>

            {showRawContent && (
              <div style={{ paddingTop: '0.5rem', borderTop: '1px solid var(--border)' }}>
                {renderHighlightedRawText(rawStudentText, highlights)}
              </div>
            )}
          </div>

          {/* AI Overall Summary */}
          {feedback.summary && (
            <div className="glass-panel" style={{ padding: '1.5rem', backgroundColor: 'var(--bg-main)' }}>
              <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--secondary)' }}>AI Evaluation Summary</h3>
              <p style={{ margin: 0, color: 'var(--text-main)', lineHeight: '1.6' }}>{feedback.summary}</p>
            </div>
          )}

          {/* Detailed Rubric Criteria & Per-Question Lecturer Mark Override */}
          <div className="glass-panel" style={{ padding: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Edit3 size={18} color="var(--primary)" /> Rubric Criteria & Per-Question Mark Override
              </h3>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--primary)' }}>
                Total: {calculatedTotalFromQuestions} / {totalMaxScore || 100} marks
              </div>
            </div>

            {breakdown.length === 0 ? (
              <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-main)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  {activeSubmission.status === 'pending'
                    ? '⌛ Submission pending AI grading. Click "Run AI Grading Pipeline" to evaluate this paper.'
                    : 'No rubric breakdown available for this assignment.'}
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                {breakdown.map((item, index) => {
                  const qKey = item.question_number || `Q${index + 1}`;
                  const currentScoreVal = questionScores[qKey] != null ? questionScores[qKey] : (item.score_awarded ?? 0);

                  return (
                    <div key={index} style={{ padding: '1.15rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--bg-main)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <strong style={{ color: 'var(--primary)', fontSize: '1.05rem' }}>{qKey}</strong>

                        {/* Lecturer Question Score Override Input */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <label style={{ fontSize: '0.825rem', color: 'var(--text-muted)', fontWeight: 600 }}>Score:</label>
                          <input
                            type="number"
                            step="0.5"
                            min="0"
                            max={item.max_score}
                            className="input-field"
                            value={currentScoreVal}
                            onChange={(e) => handlePerQuestionScoreChange(qKey, item.max_score, e.target.value)}
                            style={{ width: '80px', padding: '0.35rem 0.5rem', textAlign: 'center', fontWeight: 700, fontSize: '0.95rem', borderRadius: '6px', border: '1px solid var(--primary)' }}
                          />
                          <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-muted)' }}>/ {item.max_score} marks</span>
                        </div>
                      </div>

                      <p style={{ margin: 0, fontSize: '0.925rem', color: 'var(--text-main)', lineHeight: '1.65' }}>
                        💡 <strong>AI Evaluation Reasoning:</strong> {item.reasoning}
                      </p>
                    </div>
                  );
                })}

                {/* Per-Question Override Save Action */}
                <div style={{ marginTop: '0.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)' }}>
                    Sum of Question Marks: <strong>{calculatedTotalFromQuestions} / {totalMaxScore || 100}</strong>
                  </span>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleSaveQuestionOverrides}
                    disabled={saving}
                    style={{ padding: '0.6rem 1.25rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                  >
                    <Save size={16} /> Save Question Mark Overrides
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Right Column: Sticky Container for Grade Override & Navigation */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', position: 'sticky', top: '1.5rem', alignSelf: 'start' }}>
          
          {/* Card 1: Lecturer Grade Override Box */}
          <div className="glass-panel" style={{ padding: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Edit3 size={18} /> Lecturer Grade Override
            </h3>

            <form onSubmit={handleOverrideSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.4rem', color: 'var(--text-main)' }}>
                  New Final Score (0 - {totalMaxScore || 100})
                </label>
                <input 
                  type="number"
                  step="0.5"
                  min="0"
                  max={totalMaxScore}
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

            <div style={{ marginTop: '1.25rem', paddingTop: '0.85rem', borderTop: '1px solid var(--border)', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              🔒 All grade overrides are recorded permanently in PostgreSQL audit logs.
            </div>
          </div>

          {/* Card 2: Student Quick Navigation Box (Directly below Lecturer Grade Override box in 2nd column) */}
          <div className="glass-panel" style={{ padding: '1.25rem', borderTop: '4px solid var(--primary)', backgroundColor: '#fff' }}>
            <div style={{ textAlign: 'center', marginBottom: '0.75rem', fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 700 }}>
              Quick Student Navigation ({currentIndex >= 0 ? `${currentIndex + 1} of ${submissions.length}` : ''})
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => navigateToSubmission(prevSubmission)}
                disabled={!prevSubmission}
                style={{ 
                  width: '100%',
                  padding: '0.65rem', 
                  fontSize: '0.875rem', 
                  display: 'flex', 
                  alignItems: 'center', 
                  justify: 'center',
                  gap: '0.5rem', 
                  opacity: !prevSubmission ? 0.45 : 1,
                  fontWeight: 600
                }}
                title={prevSubmission ? `Previous: ${prevSubmission.student_name} (${prevSubmission.student_id})` : 'First Student'}
              >
                <ChevronLeft size={18} /> Previous Student
              </button>

              <button
                type="button"
                className="btn btn-primary"
                onClick={() => navigateToSubmission(nextSubmission)}
                disabled={!nextSubmission}
                style={{ 
                  width: '100%',
                  padding: '0.65rem', 
                  fontSize: '0.875rem', 
                  display: 'flex', 
                  alignItems: 'center', 
                  justify: 'center',
                  gap: '0.5rem', 
                  backgroundColor: 'var(--primary)', 
                  opacity: !nextSubmission ? 0.45 : 1,
                  fontWeight: 600
                }}
                title={nextSubmission ? `Next: ${nextSubmission.student_name} (${nextSubmission.student_id})` : 'Last Student'}
              >
                Next Student <ChevronRight size={18} />
              </button>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
};

export default GradingReview;
