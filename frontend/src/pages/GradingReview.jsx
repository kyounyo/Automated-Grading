import React, { useState, useEffect, useMemo, useCallback } from 'react';
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
  Loader2,
  Target,
  Eye,
  BookOpen,
  Check,
  RefreshCw
} from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const GradingReview = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    currentAssignmentId,
    currentAssignment,
    assignments,
    submissions,
    activeSubmission,
    setActiveSubmission,
    handleScoreOverride,
    triggerGradeSubmission,
    triggerGradeAll
  } = useAssignment();

  // Selected Highlight Popover State
  const [activeHighlightPop, setActiveHighlightPop] = useState(null);

  // Per-Question score overrides state: { "Q1": 8.5, "Q2": 9.0 }
  const [questionScores, setQuestionScores] = useState({});

  // Overall Final Grade Override input state
  const [overrideScore, setOverrideScore] = useState('');
  const [overrideComment, setOverrideComment] = useState('');
  const [saving, setSaving] = useState(false);

  const [expandedAnswers, setExpandedAnswers] = useState({});
  const [activeScrollQ, setActiveScrollQ] = useState(null);

  // Only review AI-graded student submissions (calibration sample papers belong exclusively in the Calibration page)
  const aiSubmissions = useMemo(() => {
    const nonCal = submissions.filter(s => !s.is_calibration_sample);
    return nonCal.length > 0 ? nonCal : submissions;
  }, [submissions]);

  // Sync location.state submission into context and ensure activeSubmission is populated
  useEffect(() => {
    if (location.state?.submission && !location.state?.submission?.is_calibration_sample) {
      setActiveSubmission(location.state.submission);
    } else if (location.state?.submissionId) {
      const match = aiSubmissions.find(s => s.id === location.state.submissionId);
      if (match) setActiveSubmission(match);
    } else if (!activeSubmission && aiSubmissions.length > 0) {
      setActiveSubmission(aiSubmissions[0]);
    }
  }, [location.state, aiSubmissions]);

  const targetSubId = activeSubmission?.id || location.state?.submission?.id || location.state?.submissionId;
  const liveSub = aiSubmissions.find(s => s.id === targetSubId);
  const currentSub = liveSub
    || (activeSubmission && !activeSubmission.is_calibration_sample ? activeSubmission : null)
    || (aiSubmissions.length > 0 ? aiSubmissions[0] : null);

  const activeSubmissionObj = currentSub;
  const feedback = activeSubmissionObj?.feedback || {};
  const breakdown = feedback.breakdown || [];

  // Active assignment object
  const activeAssignment = assignments?.find(a => String(a.id) === String(currentAssignmentId)) || currentAssignment;

  // Submissions list navigation
  const currentIndex = aiSubmissions.findIndex(s => s.id === currentSub?.id);
  const prevSubmission = currentIndex > 0 ? aiSubmissions[currentIndex - 1] : null;
  const nextSubmission = currentIndex < aiSubmissions.length - 1 ? aiSubmissions[currentIndex + 1] : null;

  const navigateToSubmission = (sub) => {
    if (!sub) return;
    setActiveSubmission(sub);
    navigate('/review', { state: { submission: sub } });
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

  // Extract Question List reliably from rubric_data or breakdown
  const rubricQuestions = activeAssignment?.rubric_data || [];
  const effectiveQuestions = useMemo(() => {
    if (rubricQuestions && rubricQuestions.length > 0) {
      return rubricQuestions.map((rq, idx) => {
        const qNum = rq.question_number || `Q${idx + 1}`;
        const bdMatch = breakdown.find(b => (b.question_number || '').toUpperCase() === qNum.toUpperCase()) || {};
        return {
          question_number: qNum,
          prompt: rq.prompt || `Question ${qNum}`,
          model_answer: rq.model_answer || '',
          max_score: parseFloat(rq.max_score || bdMatch.max_score || 10),
          score_awarded: bdMatch.score_awarded ?? bdMatch.score ?? null,
          reasoning: bdMatch.reasoning || '',
          is_ai_graded: bdMatch.score != null || bdMatch.score_awarded != null
        };
      });
    } else if (breakdown && breakdown.length > 0) {
      return breakdown.map((bd, idx) => ({
        question_number: bd.question_number || `Q${idx + 1}`,
        prompt: bd.prompt || `Question ${bd.question_number || idx + 1}`,
        model_answer: bd.model_answer || '',
        max_score: parseFloat(bd.max_score || 10),
        score_awarded: bd.score_awarded ?? bd.score ?? null,
        reasoning: bd.reasoning || '',
        is_ai_graded: true
      }));
    }
    return [];
  }, [rubricQuestions, breakdown]);

  // Helper to extract student response for a given question
  const extractStudentAnswer = (rawText, qKey) => {
    if (!rawText) return '';
    const cleanQ = qKey.replace(/[^A-Za-z0-9]/g, '');
    const numOnly = cleanQ.replace(/^[A-Za-z]+/, '');
    const lines = rawText.split('\n');

    const patterns = [
      new RegExp(`^(?:Question|Q|Problem)\\s*${numOnly}\\b`, 'i'),
      new RegExp(`^${cleanQ}\\b`, 'i'),
      new RegExp(`^${numOnly}\\.\\s+`, 'i'),
      new RegExp(`\\bQuestion\\s+${numOnly}\\b`, 'i')
    ];

    let startIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (patterns.some(p => p.test(line))) {
        startIdx = i;
        break;
      }
    }

    if (startIdx !== -1) {
      const collected = [];
      for (let j = startIdx; j < lines.length; j++) {
        const line = lines[j];
        if (j > startIdx) {
          const isNextQ = /^(?:Question|Q|Problem)\s*\d+/i.test(line.trim()) || /^[0-9]+\.\s+/.test(line.trim());
          if (isNextQ) break;
        }
        collected.push(line);
        if (collected.length >= 20) break;
      }
      return collected.join('\n').trim();
    }

    return rawText.slice(0, 500);
  };

  // Sync state when currentSub changes
  useEffect(() => {
    if (currentSub) {
      setOverrideScore(currentSub.score != null ? currentSub.score.toString() : '');
      setOverrideComment('');
      setActiveHighlightPop(null);

      const initialScores = {};
      effectiveQuestions.forEach((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        initialScores[qKey] = q.score_awarded != null ? q.score_awarded : 0;
      });
      setQuestionScores(initialScores);
    }
  }, [currentSub?.id, currentSub?.status, currentSub?.score, effectiveQuestions.length]);

  // Total Max Score
  const totalMaxScore = useMemo(() => {
    if (activeAssignment?.rubric_data && activeAssignment.rubric_data.length > 0) {
      const sum = activeAssignment.rubric_data.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0);
      if (sum > 0) return sum;
    }
    if (effectiveQuestions.length > 0) {
      const sum = effectiveQuestions.reduce((sum, q) => sum + (parseFloat(q.max_score) || 0), 0);
      if (sum > 0) return sum;
    }
    return 12;
  }, [activeAssignment, effectiveQuestions]);

  // Per-question score change handler
  const handlePerQuestionScoreChange = (qKey, maxScore, rawVal) => {
    const parsed = parseFloat(rawVal);
    const validVal = isNaN(parsed) ? 0 : Math.max(0, Math.min(maxScore, parsed));
    const nextScores = { ...questionScores, [qKey]: validVal };
    setQuestionScores(nextScores);
    const newSum = Object.values(nextScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
    setOverrideScore(Math.round(newSum * 10) / 10);
  };

  const handleStepQuestionScore = (qKey, maxScore, delta) => {
    const current = questionScores[qKey] != null ? questionScores[qKey] : 0;
    const stepped = Math.round((current + delta) * 10) / 10;
    const clamped = Math.max(0, Math.min(maxScore, stepped));
    handlePerQuestionScoreChange(qKey, maxScore, clamped);
  };

  const toggleExpandAnswer = (qKey) => {
    setExpandedAnswers(prev => ({ ...prev, [qKey]: !prev[qKey] }));
  };

  // Scroll to question in left panel
  const scrollToQuestion = (qKey) => {
    setActiveScrollQ(qKey);
    const elem = document.getElementById(`student-q-${qKey}`);
    if (elem) {
      elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  // Translate technical flag reasons into plain English for lecturers
  const humaniseFlagReason = (reason) => {
    if (!reason) return reason;
    const r = reason.toLowerCase();
    if (r.includes('multi-agent discrepancy') || r.includes('quality-control tolerance')) {
      return '🤖 Two AI graders disagreed on the score — please check and confirm the final mark.';
    }
    if (r.includes('low system confidence')) {
      const pctMatch = reason.match(/(\d+)%/);
      const pct = pctMatch ? pctMatch[1] : null;
      return `📉 The AI wasn\'t very confident about this grade${pct ? ` (${pct}% confidence)` : ''} — a quick review is recommended.`;
    }
    if (r.includes('terse answer') || r.includes('short answer')) {
      return '⚠️ This student\'s answer was very short — please verify there\'s enough detail to justify the score.';
    }
    if (r.includes('random quality control') || r.includes('qc audit')) {
      return '🎲 This paper was randomly selected for a spot-check to ensure grading quality.';
    }
    return reason; // fallback to original if no match
  };

  // Highlights synthesis
  let highlights = feedback.highlights || activeSubmissionObj?.highlights || [];
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

  const isFlagged = activeSubmissionObj?.status === 'flagged';
  let rawFlagReasons = isFlagged ? (feedback.flag_reasons || []) : [];
  rawFlagReasons = rawFlagReasons.filter(r => !r.toLowerCase().includes('override'));

  const conflictedQuestions = new Set();
  if (isFlagged) {
    rawFlagReasons.forEach(reason => {
      const match = reason.match(/(?:on|question|in)\s+([A-Za-z0-9_(),\s]+?)(?::|\(|$)/i);
      if (match && match[1]) {
        match[1].split(/[,&]/).forEach(p => {
          const clean = p.trim();
          if (clean.length > 0 && (clean.toLowerCase().startsWith('q') || /\d+/.test(clean))) {
            conflictedQuestions.add(clean.toUpperCase());
          }
        });
      }
    });
  }

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
      const updatedBreakdown = effectiveQuestions.map((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        const individualScore = questionScores[qKey];
        return {
          question_number: qKey,
          prompt: q.prompt,
          max_score: q.max_score,
          score_awarded: individualScore != null ? individualScore : (q.score_awarded ?? 0),
          reasoning: q.reasoning || "Manual grade adjustment by lecturer"
        };
      });

      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
        newScore,
        overrideComment || "Grade overridden / adjusted by lecturer",
        updatedBreakdown
      );

      if (updated) {
        setOverrideScore(updated.score != null ? updated.score.toString() : newScore.toString());
      }
      alert(`Grade updated successfully! Final score is now ${newScore} / ${totalMaxScore || 12}. Audit log recorded in database.`);
      setOverrideComment('');
    } catch (err) {
      alert(`Override error: ${err.message}`);
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
      alert(`Grade approved successfully! Audit flag resolved and submission status updated.`);
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

    const questionBlocks = rawText.split(/(?=(?:^|\n\n)(?:Question|Q|Problem)\s+[A-Za-z0-9_()]+:?)/gi).filter(b => b.trim().length > 0);

    if (questionBlocks.length <= 1 && effectiveQuestions.length > 1) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {effectiveQuestions.map((q, idx) => {
            const qKey = q.question_number || `Q${idx + 1}`;
            const snippet = extractStudentAnswer(rawText, qKey);
            return (
              <div
                key={qKey}
                id={`student-q-${qKey}`}
                style={{
                  backgroundColor: 'var(--surface)',
                  border: activeScrollQ === qKey ? '2px solid #4f46e5' : '1px solid var(--border)',
                  borderRadius: '8px',
                  padding: '0.85rem 1rem',
                  transition: 'border 0.2s ease'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span style={{ fontWeight: 800, fontSize: '0.85rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    📘 {qKey} Student Response Section
                  </span>
                  <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                    Max: {q.max_score} pts
                  </span>
                </div>
                <div style={{ fontSize: '0.85rem', lineHeight: '1.6', color: 'var(--text-main)', whiteSpace: 'pre-wrap', backgroundColor: 'var(--bg-main)', padding: '0.65rem 0.85rem', borderRadius: '6px' }}>
                  {snippet || rawText}
                </div>
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {questionBlocks.map((block, bIdx) => {
          const matchHeader = block.trim().match(/^((?:Question|Q|Problem)\s+[A-Za-z0-9_()]+):?([\s\S]*)$/i);
          const headerTitle = matchHeader ? matchHeader[1] : null;
          const bodyContent = matchHeader ? matchHeader[2].trim() : block.trim();

          const matchedQ = effectiveQuestions.find(eq => {
            if (!headerTitle) return false;
            const qClean = (eq.question_number || '').replace(/[^A-Za-z0-9]/g, '').toLowerCase();
            const hClean = headerTitle.replace(/[^A-Za-z0-9]/g, '').toLowerCase();
            return hClean.includes(qClean) || qClean.includes(hClean);
          });

          const qKey = matchedQ ? matchedQ.question_number : `Q${bIdx + 1}`;

          return (
            <div
              key={bIdx}
              id={`student-q-${qKey}`}
              style={{
                backgroundColor: 'var(--surface)',
                border: activeScrollQ === qKey ? '2px solid #4f46e5' : '1px solid var(--border)',
                borderRadius: '8px',
                overflow: 'hidden',
                transition: 'border 0.2s ease'
              }}
            >
              <div
                style={{
                  padding: '0.6rem 0.9rem',
                  backgroundColor: '#EDF5FB',
                  borderBottom: '1px solid #D1E5F5',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.4rem'
                }}
              >
                <span style={{ fontWeight: 800, fontSize: '0.85rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  📘 {headerTitle || `Question ${bIdx + 1}`}
                </span>
                {matchedQ && (
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, backgroundColor: 'rgba(99, 102, 241, 0.12)', color: '#4f46e5', padding: '0.15rem 0.5rem', borderRadius: '4px' }}>
                    Max: {matchedQ.max_score} pts
                  </span>
                )}
              </div>

              <div style={{ padding: '0.9rem 1rem', fontSize: '0.875rem', lineHeight: '1.65', color: 'var(--text-main)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-body)' }}>
                {bodyContent}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  if (!currentSub) {
    return (
      <div className="card-panel" style={{ padding: '3rem 2rem', textAlign: 'center', maxWidth: '600px', margin: '3rem auto' }}>
        <FileText size={48} color="var(--primary)" style={{ opacity: 0.6, marginBottom: '1rem' }} />
        <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--secondary)' }}>No Submission Selected</h3>
        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
          Please choose a student submission from the Submissions List to review.
        </p>
        <button className="btn btn-primary" onClick={() => navigate('/submissions')}>
          <ArrowLeft size={16} /> Back to Submissions List
        </button>
      </div>
    );
  }

  const rawStudentText = activeSubmissionObj?.raw_text || activeSubmissionObj?.extracted_text || '';

  return (
    <div className="grading-review-container" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', gap: '0.65rem' }}>

      {/* =========================================================================
          NAVIGATION & METADATA BAR
          ========================================================================= */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => navigate('/submissions')}
            style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 600, fontSize: '0.825rem', padding: '0.4rem 0.85rem' }}
          >
            <ArrowLeft size={16} /> Submissions List
          </button>

          {/* Switcher */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', backgroundColor: 'var(--surface)', padding: '0.25rem 0.5rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigateToSubmission(prevSubmission)}
              disabled={!prevSubmission}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !prevSubmission ? 0.4 : 1 }}
            >
              <ChevronLeft size={15} /> Prev
            </button>

            <span style={{ fontSize: '0.825rem', fontWeight: 700, color: 'var(--secondary)', padding: '0 0.65rem', minWidth: '110px', textAlign: 'center' }}>
              Student {currentIndex >= 0 ? `${currentIndex + 1} of ${aiSubmissions.length}` : '—'}
            </span>

            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigateToSubmission(nextSubmission)}
              disabled={!nextSubmission}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !nextSubmission ? 0.4 : 1 }}
            >
              Next <ChevronRight size={15} />
            </button>
          </div>

          {/* Action Status */}
          <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
            {activeSubmissionObj.status === 'pending' && (
              <button className="btn btn-primary" onClick={handleGradeWithAI} disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.825rem', padding: '0.4rem 0.85rem' }}>
                {saving ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Run AI Grading
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
              {isFlagged ? '⚠️ Needs your review' : '✓ Graded'}
            </span>
          </div>
        </div>

        {/* Student Information Banner */}
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
              {formatStudentName(activeSubmissionObj.student_name, activeSubmissionObj.student_id, activeSubmissionObj.student_email)}
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
      </div>

      {/* Multi-Agent Quality Control & Discrepancy Status Banner */}
      {(isFlagged || feedback?.discrepancy_audit) && (
        <div
          style={{
            padding: '0.65rem 1.15rem',
            borderRadius: '8px',
            backgroundColor: isFlagged ? 'rgba(245, 158, 11, 0.08)' : 'rgba(16, 185, 129, 0.08)',
            border: `1px solid ${isFlagged ? 'rgba(245, 158, 11, 0.3)' : 'rgba(16, 185, 129, 0.25)'}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.6rem',
            flexShrink: 0
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.55rem' }}>
            {isFlagged ? (
              <AlertTriangle size={16} color="var(--warning)" style={{ flexShrink: 0, marginTop: 2 }} />
            ) : (
              <CheckCircle2 size={16} color="var(--success)" style={{ flexShrink: 0, marginTop: 2 }} />
            )}
            <div style={{ fontSize: '0.8rem', color: isFlagged ? '#92400e' : '#065f46', lineHeight: 1.55 }}>
              <strong>{isFlagged ? '⚠️ Why is this paper flagged?' : '✓ Grading verified'}</strong>
              {isFlagged && rawFlagReasons.length > 0 ? (
                <ul style={{ margin: '0.3rem 0 0 0', paddingLeft: '1.1rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                  {rawFlagReasons.map((r, i) => (
                    <li key={i} style={{ fontSize: '0.785rem' }}>{humaniseFlagReason(r)}</li>
                  ))}
                </ul>
              ) : (
                <span style={{ marginLeft: '0.35rem' }}>
                  {isFlagged
                    ? 'This paper needs your manual review before it can be finalised.'
                    : "Both AI graders agreed on this score — it's been automatically approved and is ready to finalise."}
                </span>
              )}
            </div>
          </div>

          {feedback?.discrepancy_audit && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              <span>
                Observed Δ: <strong style={{ color: 'var(--text-main)' }}>{feedback.discrepancy_audit.discrepancy} pts</strong>
              </span>
              <span>•</span>
              <span>
                Allowed Limit: <strong style={{ color: 'var(--text-main)' }}>{feedback.discrepancy_audit.allowed_discrepancy} pts</strong>
              </span>
              <span>•</span>
              <span style={{
                padding: '0.15rem 0.45rem',
                borderRadius: '4px',
                backgroundColor: '#fff',
                border: '1px solid var(--border)',
                fontWeight: 600,
                color: 'var(--primary)'
              }}>
                Tolerance: {Math.round(feedback.discrepancy_audit.tolerance_rate * 100)}%
              </span>
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          MAIN TWO-COLUMN WORKSPACE
          ========================================================================= */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.15fr) minmax(0, 1.25fr)',
          gap: '1.15rem',
          alignItems: 'stretch'
        }}
      >

        {/* LEFT COLUMN: Student Raw Submission & Question Navigation */}
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
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.925rem', fontWeight: 700 }}>
              <FileText size={16} color="var(--primary)" /> Student Response Text
            </h3>
            <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)', fontWeight: 600 }}>
              📄 {activeSubmissionObj.file_name}
            </span>
          </div>

          {/* Quick Question Jump Nav Bar */}
          {effectiveQuestions.length > 0 && (
            <div style={{
              padding: '0.45rem 1rem',
              backgroundColor: '#f8fafc',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              flexWrap: 'wrap',
              flexShrink: 0
            }}>
              <span style={{ fontSize: '0.725rem', fontWeight: 700, color: 'var(--text-muted)' }}>Jump:</span>
              {effectiveQuestions.map((q, idx) => {
                const qKey = q.question_number || `Q${idx + 1}`;
                const isCurrentActive = activeScrollQ === qKey;
                return (
                  <button
                    key={qKey}
                    type="button"
                    onClick={() => scrollToQuestion(qKey)}
                    style={{
                      padding: '0.15rem 0.5rem',
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      borderRadius: '4px',
                      backgroundColor: isCurrentActive ? '#4f46e5' : '#fff',
                      color: isCurrentActive ? '#fff' : '#4f46e5',
                      border: '1px solid rgba(99, 102, 241, 0.3)',
                      cursor: 'pointer'
                    }}
                  >
                    {qKey}
                  </button>
                );
              })}
            </div>
          )}

          {/* Scrollable Student Content */}
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
        </div>

        {/* RIGHT COLUMN: Standard Grading Breakdown & Lecturer Overrides */}
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
                    Sum: {calculatedTotalFromQuestions} / {totalMaxScore || 12}
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                  {effectiveQuestions.length === 0 ? (
                    <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-main)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
                      <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.825rem' }}>
                        No rubric questions available for this assignment.
                      </p>
                    </div>
                  ) : (
                    effectiveQuestions.map((item, index) => {
                      const qKey = item.question_number || `Q${index + 1}`;
                      const currentScoreVal = questionScores[qKey] != null ? questionScores[qKey] : (item.score_awarded ?? 0);
                      const maxSc = parseFloat(item.max_score || 10.0);

                      return (
                        <div
                          key={index}
                          className="card-secondary"
                          style={{
                            padding: '0.75rem 0.85rem',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.45rem',
                            border: '1px solid var(--border)',
                            backgroundColor: 'var(--surface)'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.4rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                              <span style={{ backgroundColor: 'var(--primary)', color: '#fff', fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.45rem', borderRadius: '4px' }}>
                                {qKey}
                              </span>
                              <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                                Max: {maxSc} pts
                              </span>
                            </div>

                            {/* Score Steppers */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                              <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => handleStepQuestionScore(qKey, maxSc, -0.5)}
                                style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px' }}
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
                                style={{ width: '55px', height: '26px', padding: '0.15rem', textAlign: 'center', fontWeight: 700, fontSize: '0.85rem' }}
                              />

                              <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => handleStepQuestionScore(qKey, maxSc, 0.5)}
                                style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px' }}
                              >
                                <Plus size={12} />
                              </button>
                            </div>
                          </div>

                          {item.reasoning && (
                            <p style={{ margin: 0, fontSize: '0.775rem', color: 'var(--text-main)', lineHeight: '1.45', backgroundColor: 'var(--surface)', padding: '0.45rem 0.65rem', borderRadius: '4px', border: '1px solid var(--border)' }}>
                              💡 <strong>AI Reasoning:</strong> {item.reasoning}
                            </p>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Card 2: Final Score Override Form */}
              <div className="card-panel" style={{ padding: '1rem 1.15rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.925rem', fontWeight: 700 }}>
                  <Save size={16} color="var(--primary)" /> Final Score Override & Audit
                </h3>

                <form onSubmit={handleOverrideSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                  <div>
                    <label className="label" style={{ fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                      Final Score (0 - {totalMaxScore || 12})
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      min="0"
                      max={totalMaxScore || 12}
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
