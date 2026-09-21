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
import { saveCalibrationExample, fetchCalibrationStatus } from '../api/client';

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

  // Calibration status & cards state
  const [calStatus, setCalStatus] = useState(null);
  const [loadingCalStatus, setLoadingCalStatus] = useState(false);
  const [calCardState, setCalCardState] = useState({});
  const [expandedAnswers, setExpandedAnswers] = useState({});
  const [activeScrollQ, setActiveScrollQ] = useState(null);
  const [savingAllCal, setSavingAllCal] = useState(false);
  const [launchingBatch, setLaunchingBatch] = useState(false);

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

  const activeSubmissionObj = currentSub;
  const feedback = activeSubmissionObj?.feedback || {};
  const breakdown = feedback.breakdown || [];

  // Active assignment object
  const activeAssignment = assignments?.find(a => String(a.id) === String(currentAssignmentId)) || currentAssignment;

  // View mode for calibration samples: 'normal' (standard submission review) vs 'studio' (calibration anchor editor)
  const isActuallyCalSample = Boolean(activeSubmissionObj?.is_calibration_sample);
  const [viewMode, setViewMode] = useState(() => {
    if (location.state?.isCalibration === true) return 'studio';
    if (isActuallyCalSample && activeSubmissionObj?.status !== 'graded') return 'studio';
    return 'normal';
  });

  useEffect(() => {
    if (location.state?.isCalibration !== undefined) {
      setViewMode(location.state.isCalibration ? 'studio' : 'normal');
    } else if (isActuallyCalSample && activeSubmissionObj?.status !== 'graded') {
      setViewMode('studio');
    }
  }, [location.state?.isCalibration, activeSubmissionObj?.id, activeSubmissionObj?.status, isActuallyCalSample]);

  const isCalibrationSample = isActuallyCalSample && viewMode === 'studio';

  // Submissions list navigation
  const currentIndex = submissions.findIndex(s => s.id === currentSub?.id);
  const prevSubmission = currentIndex > 0 ? submissions[currentIndex - 1] : null;
  const nextSubmission = currentIndex < submissions.length - 1 ? submissions[currentIndex + 1] : null;

  // Calibration-specific sample navigation
  const calibrationSamples = submissions.filter(s => s.is_calibration_sample);
  const currentCalIndex = calibrationSamples.findIndex(s => s.id === currentSub?.id);
  const prevCalSample = currentCalIndex > 0 ? calibrationSamples[currentCalIndex - 1] : null;
  const nextCalSample = currentCalIndex >= 0 && currentCalIndex < calibrationSamples.length - 1 ? calibrationSamples[currentCalIndex + 1] : null;

  const navigateToSubmission = (sub, isCal = (viewMode === 'studio')) => {
    if (!sub) return;
    setActiveSubmission(sub);
    navigate('/review', { state: { submission: sub, isCalibration: isCal } });
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

  // Load Calibration Status for Assignment
  const loadCalStatus = useCallback(async () => {
    if (!currentAssignmentId) return;
    try {
      setLoadingCalStatus(true);
      const data = await fetchCalibrationStatus(currentAssignmentId);
      setCalStatus(data);
    } catch (e) {
      console.warn("Could not fetch calibration status in review:", e);
    } finally {
      setLoadingCalStatus(false);
    }
  }, [currentAssignmentId]);

  useEffect(() => {
    if (isCalibrationSample) {
      loadCalStatus();
    }
  }, [isCalibrationSample, loadCalStatus]);

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
      const initialCardState = {};
      const rawText = currentSub.raw_text || currentSub.extracted_text || '';

      effectiveQuestions.forEach((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        const initialSc = q.score_awarded != null ? q.score_awarded : (currentSub.score != null ? 0 : q.max_score);
        initialScores[qKey] = initialSc;

        const extractedAns = extractStudentAnswer(rawText, qKey);
        initialCardState[qKey] = {
          score: initialSc,
          maxScore: q.max_score,
          anchorType: initialSc >= q.max_score * 0.8 ? 'high' : initialSc <= q.max_score * 0.4 ? 'low' : 'borderline',
          studentText: extractedAns || rawText.slice(0, 400),
          feedback: q.reasoning || `Examiner baseline exemplar for ${qKey}. Marks awarded strictly under rubric criteria.`,
          saving: false,
          saveSuccess: false
        };
      });

      setQuestionScores(initialScores);
      setCalCardState(initialCardState);
    }
  }, [currentSub?.id, currentSub?.status, currentSub?.score, effectiveQuestions.length]);

  // Total Max Score
  const totalMaxScore = useMemo(() => {
    if (effectiveQuestions.length > 0) {
      return effectiveQuestions.reduce((sum, q) => sum + (parseFloat(q.max_score) || 0), 0);
    }
    return 100;
  }, [effectiveQuestions]);

  // Per-question score change handler
  const handlePerQuestionScoreChange = (qKey, maxScore, rawVal) => {
    const parsed = parseFloat(rawVal);
    const validVal = isNaN(parsed) ? 0 : Math.max(0, Math.min(maxScore, parsed));
    const nextScores = { ...questionScores, [qKey]: validVal };
    setQuestionScores(nextScores);

    if (calCardState[qKey]) {
      setCalCardState(prev => ({
        ...prev,
        [qKey]: {
          ...prev[qKey],
          score: validVal,
          anchorType: validVal >= maxScore * 0.8 ? 'high' : validVal <= maxScore * 0.4 ? 'low' : 'borderline'
        }
      }));
    }

    const newSum = Object.values(nextScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
    setOverrideScore(Math.round(newSum * 10) / 10);
  };

  const handleStepQuestionScore = (qKey, maxScore, delta) => {
    const current = questionScores[qKey] != null ? questionScores[qKey] : 0;
    const stepped = Math.round((current + delta) * 10) / 10;
    const clamped = Math.max(0, Math.min(maxScore, stepped));
    handlePerQuestionScoreChange(qKey, maxScore, clamped);
  };

  const updateCalCard = (qKey, updates) => {
    setCalCardState(prev => {
      const current = prev[qKey] || {};
      const next = { ...current, ...updates };
      if (updates.score !== undefined) {
        setQuestionScores(qs => {
          const nq = { ...qs, [qKey]: updates.score };
          const newSum = Object.values(nq).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
          setOverrideScore(Math.round(newSum * 10) / 10);
          return nq;
        });
      }
      return { ...prev, [qKey]: next };
    });
  };

  const toggleExpandAnswer = (qKey) => {
    setExpandedAnswers(prev => ({ ...prev, [qKey]: !prev[qKey] }));
  };

  // 1-Click Save Calibration Exemplar for a Question
  const handleSaveCardExemplar = async (qKey, qObj) => {
    if (!currentAssignmentId) return;
    const card = calCardState[qKey] || {};
    const scoreVal = card.score != null ? parseFloat(card.score) : 0;
    const maxVal = parseFloat(qObj.max_score || card.maxScore || 10);
    const studentText = (card.studentText || '').trim() || (activeSubmissionObj?.raw_text || '').slice(0, 400);

    try {
      updateCalCard(qKey, { saving: true, saveSuccess: false });
      await saveCalibrationExample(currentAssignmentId, {
        question_number: qKey,
        student_text: studentText,
        examiner_score: scoreVal,
        max_score: maxVal,
        examiner_feedback: card.feedback || `Examiner exemplar for ${qKey}`,
        anchor_type: card.anchorType || 'borderline',
        submission_id: activeSubmissionObj?.id
      });

      updateCalCard(qKey, { saving: false, saveSuccess: true });
      await loadCalStatus();

      setTimeout(() => {
        updateCalCard(qKey, { saveSuccess: false });
      }, 2500);
    } catch (err) {
      alert(`Could not save exemplar for ${qKey}: ${err.message}`);
      updateCalCard(qKey, { saving: false });
    }
  };

  // Save All Marks for Current Submission (Overrides score and marks as graded)
  const handleSaveAllCalibrationMarks = async () => {
    if (!activeSubmissionObj) return;
    try {
      setSavingAllCal(true);
      const calculatedSum = Object.values(questionScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);
      const roundedTotal = Math.round(calculatedSum * 10) / 10;

      const updatedBreakdown = effectiveQuestions.map((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        const score = questionScores[qKey] != null ? questionScores[qKey] : (q.score_awarded ?? 0);
        return {
          question_number: qKey,
          prompt: q.prompt,
          max_score: q.max_score,
          score_awarded: score,
          score: score,
          reasoning: calCardState[qKey]?.feedback || q.reasoning || `Examiner calibration score: ${score}/${q.max_score}`
        };
      });

      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
        roundedTotal,
        "Examiner baseline calibration marked and saved",
        updatedBreakdown
      );

      if (updated) {
        setActiveSubmission(updated);
        setOverrideScore(roundedTotal.toString());
      }

      alert(`✅ Calibration marks saved! Submission score recorded as ${roundedTotal} / ${totalMaxScore}.`);
    } catch (err) {
      alert(`Failed to save calibration marks: ${err.message}`);
    } finally {
      setSavingAllCal(false);
    }
  };

  // Launch Batch Grading with Few-Shot Calibration
  const handleLaunchFewShotGrading = async () => {
    if (!currentAssignmentId) return;
    try {
      setLaunchingBatch(true);
      await triggerGradeAll(currentAssignmentId);
      alert('🚀 Batch Few-Shot AI grading job launched! Moving to Submissions List...');
      navigate('/submissions');
    } catch (err) {
      alert(`Failed to launch batch grading: ${err.message}`);
    } finally {
      setLaunchingBatch(false);
    }
  };

  // Scroll to question in left panel
  const scrollToQuestion = (qKey) => {
    setActiveScrollQ(qKey);
    const elem = document.getElementById(`student-q-${qKey}`);
    if (elem) {
      elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
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
      alert(`Grade updated successfully! Final score is now ${newScore} / ${totalMaxScore || 100}. Audit log recorded in database.`);
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
          Please choose a student submission from the Submissions List to review or calibrate.
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
          TOP BANNER: EXAMINER CALIBRATION STUDIO HEADER
          ========================================================================= */}
      {isCalibrationSample ? (
        <div style={{
          padding: '0.75rem 1.15rem',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, rgba(79, 70, 229, 0.12) 0%, rgba(124, 58, 237, 0.09) 100%)',
          border: '1.5px solid rgba(99, 102, 241, 0.35)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem',
          flexShrink: 0
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <span style={{ fontSize: '1.35rem' }}>🎯</span>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <strong style={{ fontSize: '0.95rem', color: '#4338ca' }}>Examiner Calibration Studio</strong>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', backgroundColor: '#4f46e5', color: '#fff' }}>
                  Sample {currentCalIndex >= 0 ? `${currentCalIndex + 1} of ${calibrationSamples.length}` : 'Baseline'}
                </span>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6b7280' }}>
                  • {effectiveQuestions.length} Rubric Questions
                </span>
              </div>
              <p style={{ margin: '0.15rem 0 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                Mark student answers below and click <strong>"Save Calibration Exemplar"</strong> to establish the authoritative few-shot standards that guide the AI grading model.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {calStatus && calStatus.total_calibrated_examples > 0 && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleLaunchFewShotGrading}
                disabled={launchingBatch}
                style={{
                  fontSize: '0.78rem',
                  padding: '0.35rem 0.85rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                  border: 'none',
                  boxShadow: '0 2px 5px rgba(16, 185, 129, 0.3)'
                }}
              >
                {launchingBatch ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
                Finish & Launch AI Grading ({calStatus.total_calibrated_examples} Ex)
              </button>
            )}
          </div>
        </div>
      ) : null}

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
            {isCalibrationSample ? (
              <>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => navigateToSubmission(prevCalSample, true)}
                  disabled={!prevCalSample}
                  style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !prevCalSample ? 0.4 : 1 }}
                  title={prevCalSample ? `Prev: ${formatStudentName(prevCalSample.student_name, prevCalSample.student_id, prevCalSample.student_email)}` : 'First sample'}
                >
                  <ChevronLeft size={15} /> Prev Sample
                </button>

                <span style={{ fontSize: '0.825rem', fontWeight: 700, color: '#4338ca', padding: '0 0.65rem', minWidth: '130px', textAlign: 'center' }}>
                  🎯 Sample {currentCalIndex >= 0 ? `${currentCalIndex + 1} of ${calibrationSamples.length}` : '—'}
                </span>

                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => navigateToSubmission(nextCalSample, true)}
                  disabled={!nextCalSample}
                  style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !nextCalSample ? 0.4 : 1 }}
                  title={nextCalSample ? `Next: ${formatStudentName(nextCalSample.student_name, nextCalSample.student_id, nextCalSample.student_email)}` : 'Last sample'}
                >
                  Next Sample <ChevronRight size={15} />
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => navigateToSubmission(prevSubmission, false)}
                  disabled={!prevSubmission}
                  style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !prevSubmission ? 0.4 : 1 }}
                >
                  <ChevronLeft size={15} /> Prev
                </button>

                <span style={{ fontSize: '0.825rem', fontWeight: 700, color: 'var(--secondary)', padding: '0 0.65rem', minWidth: '110px', textAlign: 'center' }}>
                  Student {currentIndex >= 0 ? `${currentIndex + 1} of ${submissions.length}` : '—'}
                </span>

                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => navigateToSubmission(nextSubmission, false)}
                  disabled={!nextSubmission}
                  style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !nextSubmission ? 0.4 : 1 }}
                >
                  Next <ChevronRight size={15} />
                </button>
              </>
            )}
          </div>

          {/* Action Status */}
          <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
            {!isCalibrationSample && activeSubmissionObj.status === 'pending' && (
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
                backgroundColor: isCalibrationSample
                  ? 'rgba(99, 102, 241, 0.12)'
                  : isFlagged ? 'var(--warning-bg)' : 'var(--success-bg)',
                color: isCalibrationSample
                  ? '#4f46e5'
                  : isFlagged ? 'var(--warning)' : 'var(--success)',
                border: `1px solid ${isCalibrationSample ? 'rgba(99, 102, 241, 0.3)' : isFlagged ? 'var(--warning-border)' : 'var(--success-border)'}`,
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                fontWeight: 700,
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem'
              }}
            >
              {isCalibrationSample ? '🎯 Calibration Sample' : isFlagged ? '⚠️ Flagged for Audit' : '✓ Graded & Approved'}
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
              {isCalibrationSample ? 'Calculated Total' : 'Total Score'}
            </span>
            <span style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)', lineHeight: 1 }}>
              {isCalibrationSample ? calculatedTotalFromQuestions : (activeSubmissionObj.score != null ? activeSubmissionObj.score : '—')}
              <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 600 }}>{totalMaxScore ? ` / ${totalMaxScore}` : ''}</span>
            </span>
          </div>
        </div>
      </div>

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

        {/* RIGHT COLUMN: Calibration Cards or Standard Grading Overrides */}
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
          {/* =========================================================================
              EXAMINER CALIBRATION MODE: INLINE QUESTION CARDS
              ========================================================================= */}
          {isCalibrationSample ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              
              {/* Calibration Header Info Box */}
              <div style={{
                padding: '0.75rem 1rem',
                backgroundColor: 'rgba(99, 102, 241, 0.05)',
                border: '1px solid rgba(99, 102, 241, 0.25)',
                borderRadius: '8px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '0.5rem'
              }}>
                <div>
                  <strong style={{ fontSize: '0.85rem', color: '#4338ca' }}>
                    Examiner Question Scoring & Exemplar Setup
                  </strong>
                  <p style={{ margin: '0.1rem 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Set examiner score, select anchor classification, and click "Save Calibration Exemplar" to establish few-shot benchmarks.
                  </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {activeSubmissionObj?.status === 'graded' && (
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => setViewMode('normal')}
                      style={{
                        fontSize: '0.75rem',
                        padding: '0.25rem 0.65rem',
                        backgroundColor: '#fff',
                        borderColor: 'rgba(99, 102, 241, 0.4)',
                        color: '#4f46e5',
                        fontWeight: 600
                      }}
                    >
                      👁️ View Normal Submission
                    </button>
                  )}
                  <span style={{ fontSize: '0.775rem', fontWeight: 700, color: '#4f46e5', backgroundColor: '#fff', padding: '0.2rem 0.6rem', borderRadius: '4px', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
                    Total: {calculatedTotalFromQuestions} / {totalMaxScore}
                  </span>
                </div>
              </div>

              {/* List of Question Cards */}
              {effectiveQuestions.map((q, idx) => {
                const qKey = q.question_number || `Q${idx + 1}`;
                const card = calCardState[qKey] || {};
                const currentScoreVal = card.score != null ? card.score : (questionScores[qKey] ?? 0);
                const maxSc = q.max_score || 10;
                const isExpanded = Boolean(expandedAnswers[qKey]);

                // Check calibration status for this question
                const qStatusObj = calStatus?.questions?.find(qs => qs.question_number.toUpperCase() === qKey.toUpperCase());
                const isQuestionCalibrated = (qStatusObj?.sample_count || 0) > 0;

                return (
                  <div
                    key={qKey}
                    className="card-panel"
                    style={{
                      padding: '1rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.65rem',
                      backgroundColor: 'var(--surface)',
                      border: card.saveSuccess ? '1.5px solid #10b981' : isQuestionCalibrated ? '1px solid rgba(99, 102, 241, 0.4)' : '1px solid var(--border)',
                      boxShadow: '0 2px 4px rgba(0, 0, 0, 0.03)'
                    }}
                  >
                    {/* Header Row */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.4rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{
                          backgroundColor: '#4f46e5',
                          color: '#fff',
                          fontSize: '0.8rem',
                          fontWeight: 800,
                          padding: '0.2rem 0.55rem',
                          borderRadius: '4px'
                        }}>
                          {qKey}
                        </span>
                        <span style={{ fontSize: '0.775rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                          Max: {maxSc} pts
                        </span>
                        {isQuestionCalibrated ? (
                          <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '0.1rem 0.45rem', borderRadius: '4px', backgroundColor: 'rgba(16, 185, 129, 0.1)', color: '#059669', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                            ✓ {qStatusObj.sample_count} Exemplar{qStatusObj.sample_count === 1 ? '' : 's'} (v{qStatusObj.version})
                          </span>
                        ) : (
                          <span style={{ fontSize: '0.72rem', fontWeight: 600, padding: '0.1rem 0.45rem', borderRadius: '4px', backgroundColor: 'rgba(245, 158, 11, 0.1)', color: '#b45309', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                            ⏳ Needs Exemplar
                          </span>
                        )}
                      </div>

                      {/* Model Answer Toggle */}
                      <button
                        type="button"
                        onClick={() => toggleExpandAnswer(qKey)}
                        style={{
                          background: 'none',
                          border: 'none',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          color: '#4f46e5',
                          cursor: 'pointer',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                      >
                        <BookOpen size={13} /> {isExpanded ? 'Hide Marking Scheme' : 'View Marking Scheme'}
                      </button>
                    </div>

                    {/* Question Prompt */}
                    <div style={{ fontSize: '0.825rem', color: 'var(--secondary)', fontWeight: 600, lineHeight: '1.4' }}>
                      {q.prompt}
                    </div>

                    {/* Collapsible Model Answer */}
                    {isExpanded && (
                      <div style={{
                        padding: '0.65rem 0.85rem',
                        backgroundColor: '#faf5ff',
                        border: '1px solid #e9d5ff',
                        borderRadius: '6px',
                        fontSize: '0.78rem',
                        color: '#581c87',
                        lineHeight: '1.45',
                        whiteSpace: 'pre-wrap'
                      }}>
                        📖 <strong>Official Model Answer & Criteria:</strong>
                        <div style={{ marginTop: '0.2rem' }}>
                          {q.model_answer || 'No specific model answer provided in rubric.'}
                        </div>
                      </div>
                    )}

                    {/* Student Response Input / Preview */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.725rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                          Student Answer (for calibration few-shot example):
                        </span>
                        <button
                          type="button"
                          onClick={() => updateCalCard(qKey, { studentText: extractStudentAnswer(rawStudentText, qKey) })}
                          style={{ background: 'none', border: 'none', fontSize: '0.7rem', color: '#4f46e5', cursor: 'pointer', textDecoration: 'underline' }}
                        >
                          Auto-Extract from Student Text
                        </button>
                      </div>
                      <textarea
                        rows={3}
                        className="input-field"
                        value={card.studentText || ''}
                        onChange={(e) => updateCalCard(qKey, { studentText: e.target.value })}
                        placeholder="Student response for this question..."
                        style={{ fontSize: '0.8rem', padding: '0.45rem', resize: 'vertical' }}
                      />
                    </div>

                    {/* Scoring Controls & Presets */}
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '0.5rem',
                      padding: '0.5rem 0.65rem',
                      backgroundColor: 'var(--bg-main)',
                      borderRadius: '6px',
                      border: '1px solid var(--border)'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--secondary)' }}>
                          Examiner Score:
                        </span>
                        {/* Quick Presets */}
                        <button
                          type="button"
                          onClick={() => updateCalCard(qKey, { score: 0 })}
                          style={{
                            padding: '0.2rem 0.45rem',
                            fontSize: '0.725rem',
                            borderRadius: '4px',
                            border: '1px solid var(--border)',
                            backgroundColor: currentScoreVal === 0 ? '#fee2e2' : '#fff',
                            color: currentScoreVal === 0 ? '#991b1b' : 'var(--text-main)',
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                        >
                          0 pts
                        </button>
                        <button
                          type="button"
                          onClick={() => updateCalCard(qKey, { score: Math.round((maxSc / 2) * 10) / 10 })}
                          style={{
                            padding: '0.2rem 0.45rem',
                            fontSize: '0.725rem',
                            borderRadius: '4px',
                            border: '1px solid var(--border)',
                            backgroundColor: currentScoreVal === Math.round((maxSc / 2) * 10) / 10 ? '#fef3c7' : '#fff',
                            color: currentScoreVal === Math.round((maxSc / 2) * 10) / 10 ? '#92400e' : 'var(--text-main)',
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                        >
                          Half ({Math.round((maxSc / 2) * 10) / 10})
                        </button>
                        <button
                          type="button"
                          onClick={() => updateCalCard(qKey, { score: maxSc })}
                          style={{
                            padding: '0.2rem 0.45rem',
                            fontSize: '0.725rem',
                            borderRadius: '4px',
                            border: '1px solid var(--border)',
                            backgroundColor: currentScoreVal === maxSc ? '#dcfce7' : '#fff',
                            color: currentScoreVal === maxSc ? '#166534' : 'var(--text-main)',
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                        >
                          Full ({maxSc})
                        </button>
                      </div>

                      {/* Stepper Input */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                        <button
                          type="button"
                          className="btn btn-outline"
                          onClick={() => handleStepQuestionScore(qKey, maxSc, -0.5)}
                          style={{ padding: '0.15rem 0.4rem', minWidth: '24px', height: '26px' }}
                        >
                          <Minus size={11} />
                        </button>
                        <input
                          type="number"
                          step="0.5"
                          min="0"
                          max={maxSc}
                          className="input-field"
                          value={currentScoreVal}
                          onChange={(e) => handlePerQuestionScoreChange(qKey, maxSc, e.target.value)}
                          style={{ width: '58px', height: '26px', padding: '0.1rem', textAlign: 'center', fontWeight: 800, fontSize: '0.85rem' }}
                        />
                        <button
                          type="button"
                          className="btn btn-outline"
                          onClick={() => handleStepQuestionScore(qKey, maxSc, 0.5)}
                          style={{ padding: '0.15rem 0.4rem', minWidth: '24px', height: '26px' }}
                        >
                          <Plus size={11} />
                        </button>
                        <span style={{ fontSize: '0.775rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                          / {maxSc}
                        </span>
                      </div>
                    </div>

                    {/* Anchor Classification Selector */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.725rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                        Anchor Type:
                      </span>
                      {[
                        { type: 'high', label: '🟢 High Anchor (Full Credit)' },
                        { type: 'borderline', label: '🟡 Borderline Anchor (Partial Credit)' },
                        { type: 'low', label: '🔴 Low Anchor (Common Error)' }
                      ].map(a => (
                        <button
                          key={a.type}
                          type="button"
                          onClick={() => updateCalCard(qKey, { anchorType: a.type })}
                          style={{
                            padding: '0.2rem 0.55rem',
                            fontSize: '0.72rem',
                            borderRadius: '12px',
                            border: card.anchorType === a.type ? '1.5px solid #4f46e5' : '1px solid var(--border)',
                            backgroundColor: card.anchorType === a.type ? 'rgba(99, 102, 241, 0.12)' : '#fff',
                            color: card.anchorType === a.type ? '#4338ca' : 'var(--text-main)',
                            fontWeight: card.anchorType === a.type ? 700 : 500,
                            cursor: 'pointer'
                          }}
                        >
                          {a.label}
                        </button>
                      ))}
                    </div>

                    {/* Examiner Rationale */}
                    <div>
                      <textarea
                        rows={2}
                        className="input-field"
                        value={card.feedback || ''}
                        onChange={(e) => updateCalCard(qKey, { feedback: e.target.value })}
                        placeholder="Examiner marking rationale (explains marks awarded to train the few-shot AI grader)..."
                        style={{ fontSize: '0.775rem', padding: '0.4rem', resize: 'vertical' }}
                      />
                    </div>

                    {/* Action Button: 1-Click Save Exemplar */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '0.5rem', paddingTop: '0.2rem' }}>
                      {card.saveSuccess && (
                        <span style={{ fontSize: '0.775rem', color: '#16a34a', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                          ✓ Saved as {qKey} Exemplar!
                        </span>
                      )}
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => handleSaveCardExemplar(qKey, q)}
                        disabled={card.saving}
                        style={{
                          fontSize: '0.775rem',
                          padding: '0.38rem 0.85rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.35rem',
                          background: 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
                          border: 'none',
                          color: '#fff',
                          boxShadow: '0 2px 4px rgba(79, 70, 229, 0.25)'
                        }}
                      >
                        {card.saving ? (
                          <>
                            <Loader2 size={13} className="spin" /> Saving Exemplar...
                          </>
                        ) : (
                          <>
                            <Target size={14} /> Save as Calibration Exemplar
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}

              {/* Bottom Actions for Calibration Sample */}
              <div className="card-panel" style={{ padding: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div>
                  <strong style={{ fontSize: '0.9rem', color: 'var(--secondary)' }}>
                    Sample Score: {calculatedTotalFromQuestions} / {totalMaxScore}
                  </strong>
                  <p style={{ margin: '0.1rem 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Save overall marks for this student or proceed to the next calibration sample.
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleSaveAllCalibrationMarks}
                    disabled={savingAllCal}
                    style={{ fontSize: '0.825rem', padding: '0.45rem 1rem' }}
                  >
                    {savingAllCal ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
                    Save Marks for this Student
                  </button>

                  {nextCalSample && (
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => navigateToSubmission(nextCalSample, true)}
                      style={{ fontSize: '0.825rem', padding: '0.45rem 0.9rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
                    >
                      Next Sample <ChevronRight size={14} />
                    </button>
                  )}
                </div>
              </div>

            </div>
          ) : (
            /* =========================================================================
                STANDARD AI GRADING REVIEW MODE
                ========================================================================= */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              
              {isActuallyCalSample && (
                <div style={{
                  padding: '0.8rem 1.15rem',
                  borderRadius: '8px',
                  background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(124, 58, 237, 0.05) 100%)',
                  border: '1px solid rgba(99, 102, 241, 0.25)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.75rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                    <span style={{ fontSize: '1.3rem' }}>🎯</span>
                    <div>
                      <strong style={{ fontSize: '0.875rem', color: '#4338ca' }}>
                        Examiner Calibration Baseline Exemplar
                      </strong>
                      <p style={{ margin: '0.15rem 0 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        This submission serves as an authoritative few-shot calibration example for AI grading.
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={() => setViewMode('studio')}
                    style={{
                      fontSize: '0.775rem',
                      padding: '0.35rem 0.75rem',
                      backgroundColor: '#fff',
                      borderColor: '#818cf8',
                      color: '#4338ca',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.35rem'
                    }}
                  >
                    <Target size={13} /> Edit in Calibration Studio →
                  </button>
                </div>
              )}

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
          )}

        </div>
      </div>
    </div>
  );
};

export default GradingReview;
