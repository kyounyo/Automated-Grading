import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Save,
  CheckCircle2,
  FileText,
  AlertTriangle,
  Layers,
  Plus,
  Minus,
  Edit3,
  Award,
  HelpCircle,
  ShieldAlert,
  Zap,
  Loader2
} from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const GradingReview = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    currentAssignmentId,
    currentAssignment,
    submissions,
    activeSubmission,
    setActiveSubmission,
    handleScoreOverride,
    triggerGradeSubmission
  } = useAssignment();

  // Selected Highlight Popover State
  const [activeHighlightPop, setActiveHighlightPop] = useState(null);

  // Per-Question score overrides state: { "Q1": 8.5, "Q2": 9.0 }
  const [questionScores, setQuestionScores] = useState({});

  // Overall Final Grade Override input state
  const [overrideScore, setOverrideScore] = useState('');
  const [overrideComment, setOverrideComment] = useState('');
  const [saving, setSaving] = useState(false);

  // Sync location.state submission into context and ensure activeSubmission is populated
  useEffect(() => {
    if (location.state?.submission) {
      setActiveSubmission(location.state.submission);
    } else if (location.state?.submissionId) {
      const match = submissions.find(s => s.id === location.state.submissionId);
      if (match) setActiveSubmission(match);
    } else if (!activeSubmission && submissions.length > 0) {
      setActiveSubmission(submissions[0]);
    }
  }, [location.state, submissions]);

  const targetSubId = activeSubmission?.id || location.state?.submission?.id || location.state?.submissionId;
  const liveSub = submissions.find(s => s.id === targetSubId);
  const currentSub = liveSub
    || activeSubmission
    || location.state?.submission
    || (submissions.length > 0 ? submissions[0] : null);

  // Sync state when currentSub changes
  useEffect(() => {
    if (currentSub) {
      setOverrideScore(currentSub.score != null ? currentSub.score.toString() : '');
      setOverrideComment('');
      setActiveHighlightPop(null);

      const fb = currentSub.feedback || {};
      const bd = fb.breakdown || [];
      const initialScores = {};
      bd.forEach((item, idx) => {
        const qKey = item.question_number || `Q${idx + 1}`;
        initialScores[qKey] = item.score_awarded != null ? item.score_awarded : (item.score != null ? item.score : 0);
      });
      setQuestionScores(initialScores);
    }
  }, [currentSub?.id, currentSub?.status, currentSub?.score]);

  // Navigate to adjacent submission
  const currentIndex = submissions.findIndex(s => s.id === currentSub?.id);
  const prevSubmission = currentIndex > 0 ? submissions[currentIndex - 1] : null;
  const nextSubmission = currentIndex < submissions.length - 1 ? submissions[currentIndex + 1] : null;

  const navigateToSubmission = (sub) => {
    if (!sub) return;
    setActiveSubmission(sub);
    navigate('/review', { state: { submission: sub } });
  };

  if (!currentSub) {
    return (
      <div className="card-panel" style={{ padding: '3rem 2rem', textAlign: 'center', maxWidth: '600px', margin: '3rem auto' }}>
        <FileText size={48} color="var(--primary)" style={{ opacity: 0.6, marginBottom: '1rem' }} />
        <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--secondary)' }}>No Submission Selected</h3>
        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
          Please choose a student submission from the Submissions List to review AI grading breakdown.
        </p>
        <button className="btn btn-primary" onClick={() => navigate('/submissions')}>
          <ArrowLeft size={16} /> Back to Submissions List
        </button>
      </div>
    );
  }

  const activeSubmissionObj = currentSub;
  const feedback = activeSubmissionObj.feedback || {};
  const breakdown = feedback.breakdown || [];
  
  // Extract or synthesize highlights from breakdown reasoning if highlights array is empty
  let highlights = feedback.highlights || activeSubmissionObj.highlights || [];
  if (highlights.length === 0 && breakdown.length > 0) {
    breakdown.forEach((item, idx) => {
      const qNum = item.question_number || `Q${idx + 1}`;
      const scoreAwarded = item.score_awarded ?? item.score ?? 0;
      const isPositive = scoreAwarded > 0;
      
      const quoteMatches = (item.reasoning || '').match(/'([^']+)'|"([^"]+)"/g);
      if (quoteMatches) {
        quoteMatches.forEach(qm => {
          const cleanQ = qm.replace(/['"]/g, '').trim();
          if (cleanQ.length > 4) {
            highlights.push({
              text: cleanQ,
              type: isPositive ? 'strength' : 'weakness',
              score_awarded: isPositive ? scoreAwarded : 0,
              question_number: qNum,
              comment: item.reasoning
            });
          }
        });
      }
    });
  }

  // Determine Flags and Conflicted Questions:
  // A submission is flagged ONLY if its current status is 'flagged' (not finalized by lecturer override)
  const isFlagged = activeSubmissionObj.status === 'flagged';

  let rawFlagReasons = isFlagged ? (feedback.flag_reasons || []) : [];
  if (isFlagged && rawFlagReasons.length === 0) {
    rawFlagReasons = ['⚠️ Flagged for Quality Audit: Score discrepancy or low AI confidence detected'];
  }

  // Filter out any "Lecturer Manual Override Applied" strings from conflict reasons
  rawFlagReasons = rawFlagReasons.filter(r => !r.toLowerCase().includes('override'));

  // Parse specific conflicted questions from flag reasons (e.g. "on Q6(a), Q8")
  const conflictedQuestions = new Set();
  if (isFlagged) {
    rawFlagReasons.forEach(reason => {
      const match = reason.match(/(?:on|question|in)\s+([A-Za-z0-9_(),\s]+?)(?::|\(|$)/i);
      if (match && match[1]) {
        const parts = match[1].split(/[,&]/);
        parts.forEach(p => {
          const clean = p.trim();
          if (clean.length > 0 && (clean.toLowerCase().startsWith('q') || /\d+/.test(clean))) {
            conflictedQuestions.add(clean.toUpperCase());
          }
        });
      }
    });
  }

  const totalMaxScore = currentAssignment?.rubric_data
    ? currentAssignment.rubric_data.reduce((acc, q) => acc + (parseFloat(q.max_score) || 0), 0)
    : (breakdown.length > 0 ? breakdown.reduce((acc, b) => acc + (parseFloat(b.max_score) || 0), 0) : null);

  // Per-question score stepper
  const handleStepQuestionScore = (qKey, maxScore, delta) => {
    const current = questionScores[qKey] != null ? questionScores[qKey] : 0;
    const stepped = Math.round((current + delta) * 10) / 10;
    const clamped = Math.max(0, Math.min(maxScore, stepped));

    const nextScores = { ...questionScores, [qKey]: clamped };
    setQuestionScores(nextScores);

    const newSum = Object.values(nextScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
    setOverrideScore(Math.round(newSum * 10) / 10);
  };

  const handlePerQuestionScoreChange = (qKey, maxScore, rawVal) => {
    const parsed = parseFloat(rawVal);
    const validVal = isNaN(parsed) ? 0 : Math.max(0, Math.min(maxScore, parsed));
    const nextScores = { ...questionScores, [qKey]: validVal };
    setQuestionScores(nextScores);

    const newSum = Object.values(nextScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
    setOverrideScore(Math.round(newSum * 10) / 10);
  };

  const calculatedTotalFromQuestions = Object.values(questionScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    const newScore = parseFloat(overrideScore);
    if (isNaN(newScore)) {
      alert("Please enter a valid numeric grade.");
      return;
    }

    try {
      setSaving(true);
      let updatedBreakdown = breakdown.map((item, idx) => {
        const qKey = item.question_number || `Q${idx + 1}`;
        const individualScore = questionScores[qKey];
        return {
          ...item,
          score_awarded: individualScore != null ? individualScore : item.score_awarded
        };
      });

      const breakdownSum = updatedBreakdown.reduce((sum, item) => sum + (item.score_awarded || 0), 0);
      if (Math.abs(breakdownSum - newScore) > 0.05 && breakdownSum > 0) {
        const scale = newScore / breakdownSum;
        updatedBreakdown = updatedBreakdown.map(item => ({
          ...item,
          score_awarded: Math.round(Math.min(item.max_score, item.score_awarded * scale) * 10) / 10
        }));
      }

      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
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

  const handleApproveGrade = async () => {
    try {
      setSaving(true);
      const currentScore = activeSubmissionObj.score != null ? activeSubmissionObj.score : 0.0;
      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
        currentScore,
        overrideComment || "Audited and approved by lecturer",
        activeSubmissionObj.feedback?.breakdown
      );
      if (updated) {
        setActiveSubmission(updated);
        setOverrideScore(updated.score != null ? updated.score.toString() : currentScore.toString());
      }
      alert(`Grade approved successfully! Audit flag resolved and submission status updated to Graded & Approved.`);
      setOverrideComment('');
    } catch (err) {
      alert(`Approve failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleGradeWithAI = async () => {
    try {
      setSaving(true);
      await triggerGradeSubmission(activeSubmissionObj.id);
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
        <div style={{ padding: '2rem 1.5rem', backgroundColor: 'var(--danger-bg)', borderRadius: '8px', border: '1px solid var(--danger)', textAlign: 'center' }}>
          <AlertTriangle size={28} color="var(--danger)" style={{ marginBottom: '0.5rem' }} />
          <h4 style={{ margin: '0 0 0.25rem 0', color: 'var(--danger)' }}>Blank / Empty Student Submission</h4>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Student provided no text response ('-'). 0.0 marks awarded across all questions.
          </p>
        </div>
      );
    }

    const questionBlocks = rawText.split(/(?=(?:^|\n\n)Question\s+[A-Za-z0-9_()]+:)/g).filter(b => b.trim().length > 0);

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {questionBlocks.map((block, bIdx) => {
          const matchHeader = block.trim().match(/^(Question\s+[A-Za-z0-9_()]+):([\s\S]*)$/);
          const headerTitle = matchHeader ? matchHeader[1] : null;
          const bodyContent = matchHeader ? matchHeader[2].trim() : block.trim();

          const matchedBreakdown = breakdown.find(b => {
            if (!headerTitle) return false;
            const qClean = (b.question_number || '').replace(/[^A-Za-z0-9]/g, '').toLowerCase();
            const hClean = headerTitle.replace(/[^A-Za-z0-9]/g, '').toLowerCase();
            return hClean.includes(qClean) || qClean.includes(hClean);
          });

          // Check if this question is flagged for conflict
          const isQConflicted = Array.from(conflictedQuestions).some(cq => {
            if (!headerTitle) return false;
            const cleanHeader = headerTitle.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
            const cleanCQ = cq.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
            return cleanHeader.includes(cleanCQ) || cleanCQ.includes(cleanHeader);
          });

          const isBodyEmpty = !bodyContent || bodyContent === '-' || bodyContent === 'N/A';

          return (
            <div
              key={bIdx}
              style={{
                backgroundColor: 'var(--surface)',
                border: isQConflicted ? '1.5px solid #F59E0B' : '1px solid var(--border)',
                borderRadius: '8px',
                overflow: 'hidden'
              }}
            >
              {/* Question Header Pill */}
              <div
                style={{
                  padding: '0.6rem 0.9rem',
                  backgroundColor: isQConflicted ? '#FEF9EE' : '#EDF5FB',
                  borderBottom: `1px solid ${isQConflicted ? '#FCD34D' : '#D1E5F5'}`,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.4rem'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontWeight: 800, fontSize: '0.85rem', color: isQConflicted ? '#92400E' : 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    📘 {headerTitle || `Question Part ${bIdx + 1}`}
                  </span>
                  {isQConflicted && (
                    <span style={{ fontSize: '0.7rem', fontWeight: 700, backgroundColor: '#FEF3C7', color: '#B45309', padding: '0.1rem 0.4rem', borderRadius: '4px', border: '1px solid #FDE68A' }}>
                      ⚠️ Conflicted Question
                    </span>
                  )}
                </div>

                {matchedBreakdown && (
                  <span style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    backgroundColor: (matchedBreakdown.score_awarded || 0) > 0 ? 'var(--success-bg)' : 'var(--danger-bg)',
                    color: (matchedBreakdown.score_awarded || 0) > 0 ? 'var(--success)' : 'var(--danger)',
                    padding: '0.15rem 0.5rem',
                    borderRadius: '4px',
                    border: `1px solid ${(matchedBreakdown.score_awarded || 0) > 0 ? 'var(--success-border)' : 'var(--danger-border)'}`
                  }}>
                    Awarded: {matchedBreakdown.score_awarded != null ? matchedBreakdown.score_awarded : 0} / {matchedBreakdown.max_score || 10} pts
                  </span>
                )}
              </div>

              {/* Student Response Content */}
              <div style={{ padding: '0.9rem 1rem', fontSize: '0.875rem', lineHeight: '1.65', color: 'var(--text-main)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-body)' }}>
                {isBodyEmpty ? (
                  <span style={{ color: 'var(--danger)', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <AlertTriangle size={14} color="var(--danger)" /> No response submitted for this question (-). 0 marks awarded.
                  </span>
                ) : (
                  renderHighlightedSnippet(bodyContent, highlightsList, headerTitle)
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderHighlightedSnippet = (textSnippet, highlightsList, currentHeader) => {
    if (!highlightsList || highlightsList.length === 0) {
      return textSnippet;
    }

    const relevantHighlights = highlightsList.filter(h => {
      if (!h.text || h.text.trim().length < 3) return false;
      return textSnippet.toLowerCase().includes(h.text.trim().toLowerCase());
    });

    if (relevantHighlights.length === 0) {
      return textSnippet;
    }

    let parts = [textSnippet];

    relevantHighlights.forEach((hl, idx) => {
      const quote = hl.text.trim();
      const newParts = [];

      parts.forEach(part => {
        if (typeof part !== 'string') {
          newParts.push(part);
          return;
        }

        let matchIdx = part.toLowerCase().indexOf(quote.toLowerCase());
        if (matchIdx === -1) {
          newParts.push(part);
        } else {
          const before = part.slice(0, matchIdx);
          const matchedStr = part.slice(matchIdx, matchIdx + quote.length);
          const after = part.slice(matchIdx + quote.length);

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
                  ? (isStrength ? 'rgba(34, 197, 94, 0.45)' : 'rgba(239, 68, 68, 0.45)')
                  : (isStrength ? 'rgba(34, 197, 94, 0.22)' : 'rgba(239, 68, 68, 0.22)'),
                color: isStrength ? '#14532D' : '#7F1D1D',
                borderBottom: `2.5px solid ${isStrength ? '#16A34A' : '#DC2626'}`,
                borderRadius: '4px',
                padding: '0.15rem 0.35rem',
                margin: '0 0.15rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
              title="Click to view AI grading evidence & reasoning"
            >
              {matchedStr}
              <span style={{
                fontSize: '0.7rem',
                marginLeft: '0.3rem',
                padding: '0.05rem 0.35rem',
                borderRadius: '3px',
                backgroundColor: isStrength ? '#16A34A' : '#DC2626',
                color: '#fff',
                fontWeight: 700,
                display: 'inline-block'
              }}>
                {hl.score_awarded != null ? `+${hl.score_awarded}m` : (isStrength ? '✓ Key Point' : '⚠️ Issue')}
              </span>
            </mark>
          );

          if (after) newParts.push(after);
        }
      });

      parts = newParts;
    });

    return parts;
  };

  const rawStudentText = activeSubmissionObj.raw_text || activeSubmissionObj.extracted_text || '';

  return (
    <div className="grading-review-container" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', gap: '0.65rem' }}>

      {/* =========================================================================
          1. PERMANENTLY FROZEN TOP HEADER & STUDENT METADATA
          ========================================================================= */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
        
        {/* Row 1: Back Button | Quick Student Switcher | Action Status */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => navigate('/submissions')}
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 600, fontSize: '0.825rem', padding: '0.4rem 0.85rem' }}
          >
            <ArrowLeft size={16} /> Submissions List
          </button>

          {/* Quick Student Switcher */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', backgroundColor: 'var(--surface)', padding: '0.25rem 0.5rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigateToSubmission(prevSubmission)}
              disabled={!prevSubmission}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !prevSubmission ? 0.4 : 1 }}
              title={prevSubmission ? `Previous: ${prevSubmission.student_name || prevSubmission.student_id}` : 'First student'}
            >
              <ChevronLeft size={15} /> Prev
            </button>

            <span style={{ fontSize: '0.825rem', fontWeight: 700, color: 'var(--secondary)', padding: '0 0.65rem', minWidth: '110px', textAlign: 'center' }}>
              Student {currentIndex >= 0 ? `${currentIndex + 1} of ${submissions.length}` : '—'}
            </span>

            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigateToSubmission(nextSubmission)}
              disabled={!nextSubmission}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !nextSubmission ? 0.4 : 1 }}
              title={nextSubmission ? `Next: ${nextSubmission.student_name || nextSubmission.student_id}` : 'Last student'}
            >
              Next <ChevronRight size={15} />
            </button>
          </div>

          {/* Right Status & Actions */}
          <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
            {activeSubmissionObj.status === 'pending' && (
              <button className="btn btn-primary" onClick={handleGradeWithAI} disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.825rem', padding: '0.4rem 0.85rem' }}>
                {saving ? (
                  <>
                    <Loader2 size={15} className="spin" /> AI Grading in progress...
                  </>
                ) : (
                  <>
                    <Sparkles size={15} /> Run AI Grading
                  </>
                )}
              </button>
            )}

            {isFlagged && (
              <button
                className="btn btn-primary"
                onClick={handleApproveGrade}
                disabled={saving}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  fontSize: '0.825rem',
                  padding: '0.4rem 0.85rem',
                  backgroundColor: 'var(--success)',
                  borderColor: 'var(--success)',
                  color: '#fff',
                  fontWeight: 600
                }}
                title="Approve current grade and clear audit flag"
              >
                {saving ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={15} />} Approve & Clear Flag
              </button>
            )}

            <span
              className="status-badge"
              style={{
                backgroundColor: isFlagged ? 'var(--warning-bg)' : 'var(--success-bg)',
                color: isFlagged ? 'var(--warning)' : 'var(--success)',
                border: `1px solid ${isFlagged ? 'var(--warning-border)' : 'var(--success-border)'}`,
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                fontWeight: 700,
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem'
              }}
            >
              {isFlagged ? `⚠️ Flagged for Audit` : '✓ Graded & Approved'}
            </span>
          </div>
        </div>

        {/* Row 2: Frozen Student Information & Total Score Banner */}
        <div
          className="card-panel"
          style={{
            padding: '0.65rem 1.15rem',
            backgroundColor: 'var(--surface)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.65rem'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--secondary)' }}>
              {activeSubmissionObj.student_name || `Student ${activeSubmissionObj.student_id}`}
            </span>
            <span style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem', backgroundColor: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '4px', fontWeight: 600, color: 'var(--text-muted)' }}>
              ID: {activeSubmissionObj.student_id}
            </span>
            <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>
              Email: <strong>{activeSubmissionObj.student_email || 'N/A'}</strong> | File: <strong>{activeSubmissionObj.file_name}</strong>
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '0.775rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
              Total Score
            </span>
            <span style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)', lineHeight: 1 }}>
              {activeSubmissionObj.score != null ? activeSubmissionObj.score : '—'}
              <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 600 }}>{totalMaxScore ? ` / ${totalMaxScore}` : ''}</span>
            </span>
          </div>
        </div>

        {/* Row 3: SPECIFIC AUDIT & CONFLICT REASONS BANNER (If Flagged) */}
        {isFlagged && rawFlagReasons.length > 0 && (
          <div
            style={{
              backgroundColor: '#FFFBEB',
              border: '1.5px solid #F59E0B',
              borderRadius: '8px',
              padding: '0.65rem 1rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <span style={{ fontWeight: 800, fontSize: '0.85rem', color: '#92400E', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <ShieldAlert size={17} color="#D97706" /> Quality Audit & Discrepancy Alerts ({rawFlagReasons.length})
              </span>
              <span style={{ fontSize: '0.725rem', fontWeight: 700, backgroundColor: '#FEF3C7', color: '#B45309', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid #FDE68A' }}>
                Human Lecturer Review Recommended
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {rawFlagReasons.map((reason, idx) => {
                // Extract flag category
                let flagType = "Audit Discrepancy";
                let flagColor = "#B45309";
                let flagBg = "#FEF3C7";

                if (reason.includes("Multi-Agent Conflict")) {
                  flagType = "🤖 Multi-Agent Grading Conflict";
                  flagColor = "#B45309";
                  flagBg = "#FEF3C7";
                } else if (reason.includes("Low System Confidence")) {
                  flagType = "📉 Low AI Confidence";
                  flagColor = "#C2410C";
                  flagBg = "#FFEDD5";
                } else if (reason.includes("Terse Answer")) {
                  flagType = "⚠️ Brief / Terse Answer";
                  flagColor = "#A16207";
                  flagBg = "#FEF9C3";
                } else if (reason.includes("Quality Audit")) {
                  flagType = "🎲 Random QA Sampling";
                  flagColor = "#4338CA";
                  flagBg = "#EEF2FF";
                }

                return (
                  <div
                    key={idx}
                    style={{
                      backgroundColor: '#FFFFFF',
                      border: '1px solid #FCD34D',
                      borderRadius: '6px',
                      padding: '0.4rem 0.75rem',
                      fontSize: '0.8rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '0.5rem'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ backgroundColor: flagBg, color: flagColor, fontWeight: 700, fontSize: '0.725rem', padding: '0.15rem 0.45rem', borderRadius: '4px' }}>
                        {flagType}
                      </span>
                      <span style={{ color: '#78350F', fontWeight: 600 }}>
                        {reason}
                      </span>
                    </div>

                    {conflictedQuestions.size > 0 && (
                      <span style={{ fontSize: '0.725rem', fontWeight: 700, color: '#92400E', backgroundColor: '#FEF3C7', padding: '0.1rem 0.45rem', borderRadius: '4px' }}>
                        Target: {Array.from(conflictedQuestions).join(', ')}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

      </div>

      {/* =========================================================================
          2. SPACIOUS TWO-COLUMN SEPARATED LAYOUT (Independent Scrolling Viewports)
          ========================================================================= */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.25fr) minmax(0, 1fr)',
          gap: '1.25rem',
          alignItems: 'stretch'
        }}
      >

        {/* LEFT COLUMN: Highlighted Student Raw Submission */}
        <div
          className="card-panel"
          style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            overflow: 'hidden',
            backgroundColor: 'var(--surface)'
          }}
        >
          {/* Header */}
          <div style={{ padding: '0.75rem 1.15rem', borderBottom: '1px solid var(--border)', backgroundColor: 'var(--bg-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.95rem', fontWeight: 700 }}>
              <FileText size={17} color="var(--primary)" /> Highlighted Student Response
            </h3>
            <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)', fontWeight: 600, backgroundColor: 'var(--surface)', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}>
              {highlights.length} Evidence Highlight{highlights.length === 1 ? '' : 's'}
            </span>
          </div>

          {/* Scrollable Question Blocks */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '1.15rem',
              backgroundColor: 'var(--surface)'
            }}
          >
            {renderHighlightedRawText(rawStudentText, highlights)}
          </div>

          {/* Evidence Popover at Bottom of Left Column */}
          {activeHighlightPop && (
            <div
              style={{
                flexShrink: 0,
                padding: '0.75rem 1.15rem',
                backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? '#EDFBF3' : '#FDF2F2',
                borderTop: `2px solid ${activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? '#16A34A' : '#DC2626'}`,
                position: 'relative'
              }}
            >
              <button
                type="button"
                onClick={() => setActiveHighlightPop(null)}
                style={{ position: 'absolute', top: '0.4rem', right: '0.65rem', background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 700 }}
              >
                ✕
              </button>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem', paddingRight: '1.25rem' }}>
                <span style={{ fontWeight: 700, fontSize: '0.8rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                  <Layers size={14} color="var(--primary)" /> {activeHighlightPop.question_number ? (activeHighlightPop.question_number.startsWith('Q') ? `Question ${activeHighlightPop.question_number}` : `Question Q${activeHighlightPop.question_number}`) : 'Evidence Quote'}
                </span>
                <span style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  padding: '0.1rem 0.4rem',
                  borderRadius: '4px',
                  backgroundColor: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'var(--success-bg)' : 'var(--danger-bg)',
                  color: activeHighlightPop.type === 'strength' || (activeHighlightPop.score_awarded > 0) ? 'var(--success)' : 'var(--danger)'
                }}>
                  {activeHighlightPop.score_awarded != null ? `+${activeHighlightPop.score_awarded} Marks` : (activeHighlightPop.type === 'strength' ? 'Strength' : 'Weakness')}
                </span>
              </div>

              <div style={{ fontStyle: 'italic', fontSize: '0.775rem', color: 'var(--text-main)', marginBottom: '0.25rem', padding: '0.25rem 0.45rem', backgroundColor: '#fff', borderRadius: '4px', border: '1px solid var(--border)' }}>
                📄 "{activeHighlightPop.text}"
              </div>

              <div style={{ fontSize: '0.775rem', color: 'var(--text-main)', lineHeight: '1.4' }}>
                💡 <strong>AI Rubric Reasoning:</strong> {activeHighlightPop.comment}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Grading Overrides & AI Evaluation Summary */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
            height: '100%',
            overflowY: 'auto',
            paddingRight: '4px'
          }}
        >
          {/* Card 1: Per-Question Score Overrides */}
          <div
            className="card-panel"
            style={{
              padding: '1rem 1.15rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.75rem',
              backgroundColor: 'var(--surface)'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.925rem', fontWeight: 700 }}>
                <Edit3 size={16} color="var(--primary)" /> Per-Question Score Override
              </h3>
              <span style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--primary-dark)', backgroundColor: 'var(--primary-light)', padding: '0.15rem 0.5rem', borderRadius: '4px' }}>
                Sum: {calculatedTotalFromQuestions} / {totalMaxScore || 100}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {breakdown.length === 0 ? (
                <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-main)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
                  <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.825rem' }}>
                    {activeSubmissionObj.status === 'pending'
                      ? '⌛ Submission pending AI grading. Click "Run AI Grading" above.'
                      : 'No rubric breakdown available for this assignment.'}
                  </p>
                </div>
              ) : (
                breakdown.map((item, index) => {
                  const qKey = item.question_number || `Q${index + 1}`;
                  const currentScoreVal = questionScores[qKey] != null ? questionScores[qKey] : (item.score_awarded ?? 0);
                  const maxSc = parseFloat(item.max_score || 10.0);

                  // Check if this breakdown item has an active conflict
                  const isItemConflicted = Array.from(conflictedQuestions).some(cq => {
                    const cleanQ = qKey.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
                    const cleanCQ = cq.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
                    return cleanQ.includes(cleanCQ) || cleanCQ.includes(cleanQ);
                  });

                  return (
                    <div
                      key={index}
                      className="card-secondary"
                      style={{
                        padding: '0.75rem 0.85rem',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.45rem',
                        border: isItemConflicted ? '1.5px solid #F59E0B' : '1px solid var(--border)',
                        backgroundColor: isItemConflicted ? '#FEFDF9' : 'var(--surface)'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.4rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <span style={{ backgroundColor: isItemConflicted ? '#F59E0B' : 'var(--primary)', color: '#fff', fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.45rem', borderRadius: '4px' }}>
                            {qKey}
                          </span>
                          <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                            Max: {maxSc} pts
                          </span>
                          {isItemConflicted && (
                            <span style={{ fontSize: '0.7rem', fontWeight: 700, backgroundColor: '#FEF3C7', color: '#B45309', padding: '0.1rem 0.4rem', borderRadius: '4px', border: '1px solid #FDE68A' }}>
                              ⚠️ Conflict
                            </span>
                          )}
                        </div>

                        {/* Score Steppers */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                          <button
                            type="button"
                            className="btn btn-outline"
                            onClick={() => handleStepQuestionScore(qKey, maxSc, -0.5)}
                            style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px', borderRadius: '4px' }}
                            title="Decrease 0.5"
                          >
                            <Minus size={12} />
                          </button>

                          <input
                            type="number"
                            step="0.5"
                            min="0"
                            max={maxSc}
                            className="input-field"
                            value={currentScoreVal}
                            onChange={(e) => handlePerQuestionScoreChange(qKey, maxSc, e.target.value)}
                            style={{ width: '55px', height: '26px', padding: '0.15rem', textAlign: 'center', fontWeight: 700, fontSize: '0.85rem', borderRadius: '4px', border: `1px solid ${isItemConflicted ? '#F59E0B' : 'var(--primary)'}` }}
                          />

                          <button
                            type="button"
                            className="btn btn-outline"
                            onClick={() => handleStepQuestionScore(qKey, maxSc, 0.5)}
                            style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px', borderRadius: '4px' }}
                            title="Increase 0.5"
                          >
                            <Plus size={12} />
                          </button>
                        </div>
                      </div>

                      <p style={{ margin: 0, fontSize: '0.775rem', color: 'var(--text-main)', lineHeight: '1.45', backgroundColor: isItemConflicted ? '#FFFBEB' : 'var(--surface)', padding: '0.45rem 0.65rem', borderRadius: '4px', border: `1px solid ${isItemConflicted ? '#FCD34D' : 'var(--border)'}` }}>
                        💡 <strong>AI Reasoning:</strong> {item.reasoning}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Card 2: Final Score Override & Audit Form */}
          <div className="card-panel" style={{ padding: '1rem 1.15rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.925rem', fontWeight: 700 }}>
              <Save size={16} color="var(--primary)" /> Final Score Override & Audit
            </h3>

            <form onSubmit={handleOverrideSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              <div>
                <label className="label" style={{ fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                  Final Score (0 - {totalMaxScore || 100})
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  max={totalMaxScore || 100}
                  className="input-field"
                  value={overrideScore}
                  onChange={(e) => setOverrideScore(e.target.value)}
                  style={{ width: '100%', padding: '0.4rem 0.65rem', fontSize: '1.05rem', fontWeight: 800, color: 'var(--primary)' }}
                  required
                />
              </div>

              <div>
                <label className="label" style={{ fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                  Audit Comment / Justification
                </label>
                <textarea
                  rows={2}
                  className="input-field"
                  placeholder="Explain reason for grade override (e.g. Alternate derivation accepted)..."
                  value={overrideComment}
                  onChange={(e) => setOverrideComment(e.target.value)}
                  style={{ width: '100%', padding: '0.4rem 0.65rem', fontSize: '0.8rem', resize: 'vertical' }}
                />
              </div>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving}
                style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.45rem', width: '100%', padding: '0.5rem', fontWeight: 600, fontSize: '0.825rem' }}
              >
                <Save size={15} /> {saving ? 'Saving...' : 'Save & Record Audit'}
              </button>
            </form>

            <div style={{ paddingTop: '0.35rem', borderTop: '1px solid var(--border)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              🔒 Overrides are recorded in PostgreSQL audit logs with full delta traceability.
            </div>
          </div>

          {/* Card 3: AI Overall Evaluation Summary */}
          {feedback.summary && (
            <div className="card-panel" style={{ padding: '1rem 1.15rem', display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
              <h4 style={{ margin: 0, color: 'var(--secondary)', fontSize: '0.875rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Award size={15} color="var(--primary)" /> AI Overall Evaluation Summary
              </h4>
              <p style={{ margin: 0, color: 'var(--text-main)', lineHeight: '1.45', fontSize: '0.8rem' }}>
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
