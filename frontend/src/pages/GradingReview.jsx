import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  CheckCircle, 
  AlertTriangle, 
  Edit3, 
  Layers, 
  Save, 
  FileText, 
  ChevronLeft, 
  ChevronRight,
  Plus,
  Minus,
  Sparkles
} from 'lucide-react';
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
  const [questionScores, setQuestionScores] = useState({});
  const [activeHighlightPop, setActiveHighlightPop] = useState(null);

  useEffect(() => {
    if (activeSubmission) {
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
  }, [activeSubmission?.id, activeSubmission?.score, activeSubmission?.status]);

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
    const nextScores = {
      ...questionScores,
      [qKey]: valStr
    };
    setQuestionScores(nextScores);

    // Auto-calculate new total and update New Final Score (overrideScore) in real time
    let newSum = 0;
    breakdown.forEach((item, idx) => {
      const key = item.question_number || `Q${idx + 1}`;
      const val = parseFloat(key === qKey ? valStr : nextScores[key]);
      newSum += isNaN(val) ? 0 : val;
    });
    setOverrideScore((Math.round(newSum * 10) / 10).toString());
  };

  const handleStepQuestionScore = (qKey, maxScore, delta) => {
    const current = parseFloat(questionScores[qKey]) || 0;
    const newVal = Math.max(0, Math.min(maxScore, Math.round((current + delta) * 10) / 10));
    handlePerQuestionScoreChange(qKey, maxScore, newVal.toString());
  };

  const handleOverrideSubmit = async (e) => {
    if (e) e.preventDefault();
    const newScore = parseFloat(overrideScore);
    if (isNaN(newScore) || newScore < 0 || (totalMaxScore && newScore > totalMaxScore)) {
      alert(`Please enter a valid score between 0 and ${totalMaxScore || 100}.`);
      return;
    }

    try {
      setSaving(true);
      // Map updated per-question breakdown
      let updatedBreakdown = breakdown.map((item, idx) => {
        const qKey = item.question_number || `Q${idx + 1}`;
        const rawVal = parseFloat(questionScores[qKey]);
        const validVal = isNaN(rawVal) ? 0 : Math.max(0, Math.min(item.max_score, rawVal));
        return {
          ...item,
          score_awarded: Math.round(validVal * 10) / 10
        };
      });

      // If user directly typed an overall score differing from subquestions sum, sync breakdown
      const breakdownSum = updatedBreakdown.reduce((sum, item) => sum + item.score_awarded, 0);
      if (Math.abs(breakdownSum - newScore) > 0.05 && breakdownSum > 0) {
        const scale = newScore / breakdownSum;
        updatedBreakdown = updatedBreakdown.map(item => ({
          ...item,
          score_awarded: Math.round(Math.min(item.max_score, item.score_awarded * scale) * 10) / 10
        }));
      }

      const updated = await handleScoreOverride(
        activeSubmission.id,
        newScore,
        overrideComment || "Grade overridden / adjusted by lecturer",
        updatedBreakdown
      );

      if (updated) {
        setOverrideScore(updated.score != null ? updated.score.toString() : newScore.toString());
        const updatedFb = updated.feedback || {};
        const updatedBd = updatedFb.breakdown || [];
        if (updatedBd.length > 0) {
          const nextScores = {};
          updatedBd.forEach((item, idx) => {
            const qKey = item.question_number || `Q${idx + 1}`;
            nextScores[qKey] = item.score_awarded != null ? item.score_awarded : 0;
          });
          setQuestionScores(nextScores);
        }
      }

      alert(`Grade updated successfully! Final score is now ${newScore} / ${totalMaxScore || 100}. Audit log recorded in database.`);
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
        <div style={{ padding: '2rem 1.5rem', backgroundColor: 'rgba(239, 68, 68, 0.06)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)', textAlign: 'center' }}>
          <AlertTriangle size={28} color="#ef4444" style={{ marginBottom: '0.5rem' }} />
          <h4 style={{ margin: '0 0 0.25rem 0', color: '#991b1b' }}>Blank / Empty Student Submission</h4>
          <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            Student provided no text response ('-'). 0.0 marks awarded across all questions.
          </p>
        </div>
      );
    }

    if (!highlightsList || highlightsList.length === 0) {
      return (
        <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', lineHeight: '1.8', fontSize: '0.875rem', color: 'var(--text-main)' }}>
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
          const isSelected = activeHighlightPop?.text === hl.text;

          newParts.push(
            <mark
              key={`${idx}-${matchIdx}`}
              onClick={(e) => {
                e.stopPropagation();
                setActiveHighlightPop(hl);
              }}
              style={{
                backgroundColor: isSelected 
                  ? (isStrength ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.45)') 
                  : (isStrength ? 'rgba(16, 185, 129, 0.22)' : 'rgba(239, 68, 68, 0.22)'),
                color: isStrength ? '#065f46' : '#991b1b',
                borderBottom: `3px solid ${isStrength ? 'var(--success)' : '#ef4444'}`,
                borderRadius: '4px',
                padding: '0.2rem 0.45rem',
                margin: '0 0.15rem',
                fontWeight: 600,
                cursor: 'pointer',
                boxShadow: isSelected ? '0 0 0 2px var(--primary)' : 'none',
                transition: 'all 0.15s ease'
              }}
              title="Click to view AI grading reason and awarded marks"
            >
              {matchedStr}
              <span style={{
                fontSize: '0.72rem',
                marginLeft: '0.35rem',
                padding: '0.1rem 0.4rem',
                borderRadius: '3px',
                backgroundColor: isStrength ? 'var(--success)' : '#ef4444',
                color: '#fff',
                fontWeight: 700,
                display: 'inline-block'
              }}>
                {hl.question_number ? `${hl.question_number} ` : ''}{hl.score_awarded != null ? `+${hl.score_awarded}m` : (isStrength ? '✓' : '0m')}
              </span>
            </mark>
          );

          if (after) newParts.push(after);
        }
      });

      parts = newParts;
    });

    return (
      <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', lineHeight: '1.8', fontSize: '0.875rem', color: 'var(--text-main)' }}>
        {parts}
      </div>
    );
  };

  const rawStudentText = activeSubmission.raw_text || activeSubmission.extracted_text || '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', paddingBottom: '2rem' }}>

      {/* Top Header Controls: Back Button, Quick Student Switcher, AI Actions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn"
            onClick={() => navigate('/submissions')}
            style={{ background: 'var(--bg-main)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}
          >
            <ArrowLeft size={18} /> Submissions List
          </button>
        </div>

        {/* Center Quick Student Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', backgroundColor: '#fff', padding: '0.3rem 0.6rem', borderRadius: '8px', border: '1px solid var(--border)', boxShadow: 'var(--shadow-sm)' }}>
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => navigateToSubmission(prevSubmission)}
            disabled={!prevSubmission}
            style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.3rem', opacity: !prevSubmission ? 0.4 : 1 }}
            title={prevSubmission ? `Previous: ${prevSubmission.student_name || prevSubmission.student_id}` : 'First student'}
          >
            <ChevronLeft size={16} /> Prev
          </button>

          <span style={{ fontSize: '0.825rem', fontWeight: 700, color: 'var(--secondary)', padding: '0 0.5rem', minWidth: '100px', textAlign: 'center' }}>
            Student {currentIndex >= 0 ? `${currentIndex + 1} of ${submissions.length}` : '—'}
          </span>

          <button
            type="button"
            className="btn btn-outline"
            onClick={() => navigateToSubmission(nextSubmission)}
            disabled={!nextSubmission}
            style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.3rem', opacity: !nextSubmission ? 0.4 : 1 }}
            title={nextSubmission ? `Next: ${nextSubmission.student_name || nextSubmission.student_id}` : 'Last student'}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>

        {/* Right Status & Action */}
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          {activeSubmission.status === 'pending' && (
            <button className="btn btn-primary" onClick={handleGradeWithAI} disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Sparkles size={16} /> Run AI Grading
            </button>
          )}
          <span className="status-badge" style={{ backgroundColor: activeSubmission.status === 'flagged' ? 'rgba(245, 158, 11, 0.12)' : 'var(--success-bg)', color: activeSubmission.status === 'flagged' ? '#b45309' : 'var(--success)', padding: '0.4rem 0.85rem', fontSize: '0.85rem', fontWeight: 600, border: activeSubmission.status === 'flagged' ? '1px solid rgba(245, 158, 11, 0.3)' : 'none', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            {activeSubmission.status === 'flagged'
              ? `⚠️ Flagged: ${feedback.flag_reasons?.[0] || 'Quality Audit Discrepancy'}`
              : '✓ Graded'}
          </span>
        </div>
      </div>

      {/* Student Information Banner */}
      <div 
        className="glass-panel" 
        style={{ 
          padding: '0.85rem 1.25rem', 
          borderLeft: '4px solid var(--primary)',
          backgroundColor: '#fff'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <h3 style={{ margin: 0, color: 'var(--primary-dark)', fontSize: '1.2rem', fontWeight: 700 }}>
                {activeSubmission.student_name || `Student ${activeSubmission.student_id}`}
              </h3>
              <span style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem', backgroundColor: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '4px', fontWeight: 600, color: 'var(--text-muted)' }}>
                ID: {activeSubmission.student_id}
              </span>
            </div>
            <p style={{ margin: '0.2rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              Email: <strong>{activeSubmission.student_email || 'N/A'}</strong> | File: <strong>{activeSubmission.file_name}</strong>
              {activeSubmission.model_used && ` | Model: ${activeSubmission.model_used}`}
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Total Score
              </div>
              <div style={{ fontSize: '1.45rem', fontWeight: 800, color: 'var(--primary)', lineHeight: 1.1 }}>
                {activeSubmission.score != null ? activeSubmission.score : 'N/A'} 
                <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 500 }}>{totalMaxScore ? ` / ${totalMaxScore}` : ''}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* DUAL PANE SIDE-BY-SIDE MAIN CONTAINER */}
      <div 
        style={{ 
          display: 'grid', 
          gridTemplateColumns: 'minmax(0, 1.15fr) minmax(0, 1fr)', 
          gap: '1.25rem',
          alignItems: 'start'
        }}
      >

        {/* LEFT PANE: Highlighted Student Raw Submission */}
        <div 
          className="glass-panel" 
          style={{ 
            display: 'flex', 
            flexDirection: 'column', 
            height: 'calc(100vh - 215px)', 
            minHeight: '620px',
            overflow: 'hidden',
            backgroundColor: '#ffffff',
            borderTop: '4px solid var(--primary)'
          }}
        >
          {/* Left Pane Header */}
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', backgroundColor: 'rgba(244, 247, 249, 0.7)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1rem', fontWeight: 700 }}>
              <FileText size={18} color="var(--primary)" /> Highlighted Student Raw Submission
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, backgroundColor: '#fff', padding: '0.2rem 0.55rem', borderRadius: '4px', border: '1px solid var(--border)' }}>
              {highlights.length} Evidence Highlight{highlights.length === 1 ? '' : 's'}
            </span>
          </div>

          {/* Left Pane Scrollable Text Content */}
          <div 
            style={{ 
              flex: 1, 
              overflowY: 'auto', 
              padding: '1.25rem', 
              backgroundColor: '#ffffff'
            }}
          >
            {renderHighlightedRawText(rawStudentText, highlights)}
          </div>

          {/* Left Pane Bottom Evidence Popover Card */}
          {activeHighlightPop && (
            <div
              style={{
                padding: '0.85rem 1.15rem',
                backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                borderTop: `3px solid ${activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'var(--success)' : '#ef4444'}`,
                borderBottom: '1px solid var(--border)',
                position: 'relative'
              }}
            >
              <button
                type="button"
                onClick={() => setActiveHighlightPop(null)}
                style={{ position: 'absolute', top: '0.5rem', right: '0.75rem', background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '1rem', color: 'var(--text-muted)', fontWeight: 700 }}
              >
                ✕
              </button>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem', paddingRight: '1.5rem' }}>
                <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--primary-dark)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <Layers size={15} color="var(--primary)" /> {activeHighlightPop.question_number ? (activeHighlightPop.question_number.startsWith('Q') ? `Question ${activeHighlightPop.question_number}` : `Question Q${activeHighlightPop.question_number}`) : 'Question Mark Evidence'}
                </span>
                <span style={{ fontSize: '0.8rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)', color: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? '#065f46' : '#991b1b' }}>
                  {activeHighlightPop.score_awarded != null ? `+${activeHighlightPop.score_awarded} Marks` : (activeHighlightPop.type === 'strength' ? 'Strength' : 'Weakness')}
                </span>
              </div>

              <div style={{ fontStyle: 'italic', fontSize: '0.8rem', color: 'var(--text-main)', marginBottom: '0.35rem', padding: '0.3rem 0.5rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px dashed var(--border)' }}>
                📄 "{activeHighlightPop.text}"
              </div>

              <div style={{ fontSize: '0.8rem', color: 'var(--text-main)', lineHeight: '1.45' }}>
                💡 <strong>AI Rubric Reasoning:</strong> {activeHighlightPop.comment}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT PANE: Score Override & Rubric Evaluation Controls */}
        <div 
          style={{ 
            height: 'calc(100vh - 215px)', 
            minHeight: '620px',
            overflowY: 'auto', 
            paddingRight: '6px',
            display: 'flex', 
            flexDirection: 'column', 
            gap: '1.25rem' 
          }}
        >

          {/* Section 1: Detailed Rubric Criteria & Per-Question Score Overrides */}
          <div className="glass-panel" style={{ padding: '1.25rem', borderTop: '4px solid var(--accent)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1rem', fontWeight: 700 }}>
                <Edit3 size={18} color="var(--accent)" /> Per-Question Score Override
              </h3>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--primary)', backgroundColor: 'var(--primary-light)', padding: '0.2rem 0.6rem', borderRadius: '4px' }}>
                Sum: {calculatedTotalFromQuestions} / {totalMaxScore || 100} marks
              </div>
            </div>

            {breakdown.length === 0 ? (
              <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-main)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  {activeSubmission.status === 'pending'
                    ? '⌛ Submission pending AI grading. Click "Run AI Grading" to evaluate this paper.'
                    : 'No rubric breakdown available for this assignment.'}
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                {breakdown.map((item, index) => {
                  const qKey = item.question_number || `Q${index + 1}`;
                  const currentScoreVal = questionScores[qKey] != null ? questionScores[qKey] : (item.score_awarded ?? 0);
                  const maxSc = parseFloat(item.max_score || 10.0);

                  return (
                    <div 
                      key={index} 
                      style={{ 
                        padding: '0.85rem 1rem', 
                        border: '1px solid var(--border)', 
                        borderRadius: '8px', 
                        background: '#ffffff',
                        boxShadow: 'var(--shadow-sm)'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <span style={{ backgroundColor: 'var(--primary)', color: '#fff', fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.45rem', borderRadius: '4px' }}>
                            {qKey}
                          </span>
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                            Max: {maxSc} marks
                          </span>
                        </div>

                        {/* Step Controls and Score Input */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                          <button
                            type="button"
                            className="btn btn-outline"
                            onClick={() => handleStepQuestionScore(qKey, maxSc, -0.5)}
                            style={{ padding: '0.2rem 0.4rem', minWidth: '24px', height: '28px', borderRadius: '4px' }}
                            title="Decrease score by 0.5"
                          >
                            <Minus size={13} />
                          </button>

                          <input
                            type="number"
                            step="0.5"
                            min="0"
                            max={maxSc}
                            className="input-field"
                            value={currentScoreVal}
                            onChange={(e) => handlePerQuestionScoreChange(qKey, maxSc, e.target.value)}
                            style={{ width: '65px', height: '28px', padding: '0.2rem', textAlign: 'center', fontWeight: 700, fontSize: '0.9rem', borderRadius: '4px', border: '1px solid var(--primary)' }}
                          />

                          <button
                            type="button"
                            className="btn btn-outline"
                            onClick={() => handleStepQuestionScore(qKey, maxSc, 0.5)}
                            style={{ padding: '0.2rem 0.4rem', minWidth: '24px', height: '28px', borderRadius: '4px' }}
                            title="Increase score by 0.5"
                          >
                            <Plus size={13} />
                          </button>
                        </div>
                      </div>

                      <p style={{ margin: 0, fontSize: '0.825rem', color: 'var(--text-main)', lineHeight: '1.5', backgroundColor: 'var(--bg-main)', padding: '0.5rem 0.75rem', borderRadius: '6px', borderLeft: '3px solid var(--primary)' }}>
                        💡 <strong>AI Reasoning:</strong> {item.reasoning}
                      </p>
                    </div>
                  );
                })}

                {/* Auto-sync notification footer */}
                <div style={{ marginTop: '0.25rem', paddingTop: '0.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Auto-summed Total: <strong style={{ color: 'var(--primary)' }}>{calculatedTotalFromQuestions} / {totalMaxScore || 100}</strong>
                  </span>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    ✨ Synced to Final Override
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Section 2: Lecturer Final Grade Override & PostgreSQL Audit Submission */}
          <div className="glass-panel" style={{ padding: '1.25rem', borderTop: '4px solid var(--primary)' }}>
            <h3 style={{ margin: '0 0 0.85rem 0', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1rem', fontWeight: 700 }}>
              <Save size={18} color="var(--primary)" /> Final Score Override & Audit
            </h3>

            <form onSubmit={handleOverrideSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  New Final Score (0 - {totalMaxScore || 100})
                </label>
                <input 
                  type="number"
                  step="0.5"
                  min="0"
                  max={totalMaxScore || 100}
                  className="input-field"
                  value={overrideScore}
                  onChange={(e) => setOverrideScore(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem 0.75rem', fontSize: '1.1rem', fontWeight: 700, color: 'var(--primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem', color: 'var(--text-main)' }}>
                  Audit Comment / Justification
                </label>
                <textarea 
                  rows={3}
                  className="input-field"
                  placeholder="Explain reason for grade override (e.g. Adjusted marks for alternate derivation method)..."
                  value={overrideComment}
                  onChange={(e) => setOverrideComment(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem 0.75rem', fontSize: '0.85rem' }}
                />
              </div>

              <button 
                type="submit" 
                className="btn btn-primary" 
                disabled={saving}
                style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', width: '100%', padding: '0.65rem', fontWeight: 600 }}
              >
                <Save size={16} /> {saving ? 'Saving to Database...' : 'Save Grade & Record Audit Log'}
              </button>
            </form>

            <div style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--border)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              🔒 Overrides are recorded in PostgreSQL audit logs with full delta traceability.
            </div>
          </div>

          {/* Section 3: AI Overall Evaluation Summary */}
          {feedback.summary && (
            <div className="glass-panel" style={{ padding: '1.15rem', backgroundColor: '#fff' }}>
              <h4 style={{ margin: '0 0 0.4rem 0', color: 'var(--secondary)', fontSize: '0.9rem', fontWeight: 700 }}>
                AI Overall Evaluation Summary
              </h4>
              <p style={{ margin: 0, color: 'var(--text-main)', lineHeight: '1.5', fontSize: '0.85rem' }}>
                {feedback.summary}
              </p>
            </div>
          )}

        </div>

      </div>
    </div>
  );
};

export default GradingReview;
