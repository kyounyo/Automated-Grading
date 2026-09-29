import React, { useState, useEffect, useMemo } from 'react';
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
  ShieldAlert,
  Loader2
} from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { fetchSubmissionDetail } from '../api/client';

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
    loadSubmissions
  } = useAssignment();

  // Selected Highlight Popover State
  const [activeHighlightPop, setActiveHighlightPop] = useState(null);

  // Per-Question score overrides state: { "Q6": 5.0, "Q8": 9.0 }
  const [questionScores, setQuestionScores] = useState({});

  // Overall Final Grade Override input state
  const [overrideScore, setOverrideScore] = useState('');
  const [overrideComment, setOverrideComment] = useState('');
  const [saving, setSaving] = useState(false);

  // Only review AI-graded student submissions (calibration sample papers belong exclusively in the Calibration page)
  // Review all student submissions for the assignment
  const reviewSubmissions = useMemo(() => {
    return submissions && submissions.length > 0 ? submissions : [];
  }, [submissions]);

  // Sync location.state submission into context and ensure activeSubmission is populated
  useEffect(() => {
    if (location.state?.submission) {
      setActiveSubmission(location.state.submission);
    } else if (location.state?.submissionId) {
      const match = reviewSubmissions.find(s => s.id === location.state.submissionId);
      if (match) setActiveSubmission(match);
    } else if (!activeSubmission && reviewSubmissions.length > 0) {
      setActiveSubmission(reviewSubmissions[0]);
    }
  }, [location.state, reviewSubmissions]);

  // targetSubId: Prioritize the submission passed from route navigation (the exact paper clicked!)
  const targetSubId = location.state?.submission?.id || location.state?.submissionId || activeSubmission?.id;
  const liveSub = reviewSubmissions.find(s => s.id === targetSubId);
  // Prioritize route submission or newly completed score data
  const currentSub = (location.state?.submission && location.state.submission.id === targetSubId && location.state.submission.score != null)
    ? (liveSub || location.state.submission)
    : (activeSubmission?.id === targetSubId && activeSubmission?.score != null)
      ? activeSubmission
      : (liveSub || activeSubmission || (reviewSubmissions.length > 0 ? reviewSubmissions[0] : null));

  const isSubmissionUnfinished = !currentSub || currentSub.score == null || ['pending', 'uploaded', 'processing', 'extracting_answers', 'retrieving_rubric', 'grading'].includes(currentSub?.status);

  // Live auto-refresh when viewing an in-progress submission
  useEffect(() => {
    if (!targetSubId) return;
    if (!isSubmissionUnfinished) return;

    const interval = setInterval(async () => {
      try {
        const fresh = await fetchSubmissionDetail(targetSubId);
        if (fresh && fresh.score != null) {
          setActiveSubmission(fresh);
          if (currentAssignmentId) loadSubmissions(currentAssignmentId, true);
        }
      } catch (err) {
        // silent retry
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [targetSubId, isSubmissionUnfinished, currentAssignmentId, loadSubmissions, setActiveSubmission]);

  const activeSubmissionObj = currentSub;
  const feedback = activeSubmissionObj?.feedback || {};
  const breakdown = feedback.breakdown || [];

  // Active assignment object
  const activeAssignment = assignments?.find(a => String(a.id) === String(currentAssignmentId)) || currentAssignment;

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

  // Helper to extract main question key (e.g. "Q6(a)" -> "Q6", "6" -> "Q6", "Question 8" -> "Q8")
  const extractMainQKey = (qStr) => {
    if (!qStr) return '';
    const m = String(qStr).match(/(?:QUESTION|Q)?\s*(\d+)/i);
    return m ? `Q${m[1]}` : String(qStr).replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  };

  // Check if rubric allows 0.5 marks
  const allowsHalfMarks = useMemo(() => {
    if (!activeAssignment?.rubric_data) return true;
    const str = JSON.stringify(activeAssignment.rubric_data).toLowerCase();
    return str.includes('0.5') || str.includes('half mark') || str.includes('half-mark');
  }, [activeAssignment]);

  const stepIncrement = allowsHalfMarks ? 0.5 : 1.0;

  // Extract Question List reliably from rubric_data or breakdown, aggregating subquestions into main questions
  const rubricQuestions = activeAssignment?.rubric_data || [];
  const effectiveQuestions = useMemo(() => {
    if (rubricQuestions && rubricQuestions.length > 0) {
      return rubricQuestions.map((rq, idx) => {
        const qNum = rq.question_number || `Q${idx + 1}`;
        const mainQKey = extractMainQKey(qNum);

        // Find all matching breakdown items (either exact match or subquestions like Q6(a), Q6(b))
        const matchingItems = (breakdown || []).filter(b => {
          const bRaw = b.question_number || b.criterion || '';
          const bMainKey = extractMainQKey(bRaw);
          return bMainKey === mainQKey || bRaw.toUpperCase() === qNum.toUpperCase();
        });

        let resolvedScore = null;
        let resolvedReasoning = '';

        if (matchingItems.length > 0) {
          const totalSum = matchingItems.reduce((acc, item) => {
            const sc = item.score_awarded ?? item.score;
            return acc + (sc != null ? parseFloat(sc) : 0);
          }, 0);
          resolvedScore = allowsHalfMarks ? Math.round(totalSum * 10) / 10 : Math.round(totalSum);

          if (matchingItems.length > 1) {
            resolvedReasoning = matchingItems.map(m => {
              const mQ = m.question_number || '';
              const mSc = m.score_awarded ?? m.score ?? '';
              const mMx = m.max_score ? `/${m.max_score}` : '';
              const mR = m.reasoning || '';
              return `(${mQ}) [${mSc}${mMx}]: ${mR}`;
            }).join(' | ');
          } else {
            resolvedReasoning = matchingItems[0].reasoning || '';
          }
        } else if (breakdown && breakdown[idx]) {
          // Positional index fallback if question identifiers were not aligned
          const candidate = breakdown[idx];
          const sc = candidate.score_awarded ?? candidate.score;
          if (sc != null) {
            resolvedScore = allowsHalfMarks ? Math.round(parseFloat(sc) * 10) / 10 : Math.round(parseFloat(sc));
            resolvedReasoning = candidate.reasoning || '';
          }
        }

        const maxSc = parseFloat(rq.max_score || 10.0);

        return {
          question_number: qNum,
          prompt: rq.prompt || `Question ${qNum}`,
          model_answer: rq.model_answer || '',
          max_score: maxSc,
          score_awarded: resolvedScore != null ? resolvedScore : (isSubmissionUnfinished ? null : 0),
          reasoning: resolvedReasoning || (isSubmissionUnfinished ? 'AI evaluation in progress...' : 'Evaluated against rubric criteria.'),
          is_ai_graded: resolvedScore != null
        };
      });
    } else if (breakdown && breakdown.length > 0) {
      // Group raw breakdown items by main question
      const grouped = {};
      breakdown.forEach((bd, idx) => {
        const qRaw = bd.question_number || `Q${idx + 1}`;
        const mainQ = extractMainQKey(qRaw);
        if (!grouped[mainQ]) {
          grouped[mainQ] = {
            question_number: mainQ,
            prompt: bd.prompt || `Question ${mainQ}`,
            model_answer: bd.model_answer || '',
            max_score: 0,
            score_awarded: 0,
            reasoning_parts: []
          };
        }
        grouped[mainQ].max_score += parseFloat(bd.max_score || 10.0);
        grouped[mainQ].score_awarded += parseFloat(bd.score_awarded ?? bd.score ?? 0);
        if (bd.reasoning) grouped[mainQ].reasoning_parts.push(bd.reasoning);
      });

      return Object.values(grouped).map(g => ({
        question_number: g.question_number,
        prompt: g.prompt,
        model_answer: g.model_answer,
        max_score: g.max_score,
        score_awarded: allowsHalfMarks ? Math.round(g.score_awarded * 10) / 10 : Math.round(g.score_awarded),
        reasoning: g.reasoning_parts.join(' | '),
        is_ai_graded: true
      }));
    }
    return [];
  }, [rubricQuestions, breakdown, allowsHalfMarks, isSubmissionUnfinished]);

  // Sync questionScores when currentSub or effectiveQuestions changes
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
  }, [currentSub?.id, currentSub?.status, currentSub?.score, effectiveQuestions]);

  // Submissions list navigation
  const currentIndex = reviewSubmissions.findIndex(s => s.id === currentSub?.id);
  const prevSubmission = currentIndex > 0 ? reviewSubmissions[currentIndex - 1] : null;
  const nextSubmission = currentIndex < reviewSubmissions.length - 1 ? reviewSubmissions[currentIndex + 1] : null;

  const navigateToSubmission = (sub) => {
    if (!sub) return;
    setActiveSubmission(sub);
    navigate('/review', { state: { submission: sub } });
  };

  // Highlights synthesis & extraction
  let highlights = feedback.highlights || activeSubmissionObj?.highlights || [];
  if (highlights.length === 0 && effectiveQuestions.length > 0) {
    effectiveQuestions.forEach((item, idx) => {
      const qNum = item.question_number || `Q${idx + 1}`;
      const scoreAwarded = item.score_awarded ?? 0;
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
  if (isFlagged && rawFlagReasons.length === 0) {
    rawFlagReasons = ['⚠️ Flagged for Quality Audit: Score discrepancy or low AI confidence detected'];
  }
  rawFlagReasons = rawFlagReasons.filter(r => !r.toLowerCase().includes('override'));

  const conflictedQuestions = new Set();
  if (isFlagged) {
    rawFlagReasons.forEach(reason => {
      if (reason.toLowerCase().includes('discrepancy') || reason.toLowerCase().includes('conflict')) {
        const matches = reason.match(/\bQ\d+(?:\([a-z0-9]+\))?/gi);
        if (matches) {
          matches.forEach(m => conflictedQuestions.add(extractMainQKey(m)));
        }
      } else {
        const match = reason.match(/(?:on|question|in)\s+([A-Za-z0-9_(),\s]+?)(?::|\(|$)/i);
        if (match && match[1]) {
          const parts = match[1].split(/[,&]/);
          parts.forEach(p => {
            const clean = p.trim();
            if (clean.length > 0 && (clean.toLowerCase().startsWith('q') || /\d+/.test(clean))) {
              conflictedQuestions.add(extractMainQKey(clean));
            }
          });
        }
      }
    });
  }

  const totalMaxScore = useMemo(() => {
    if (activeAssignment?.rubric_data && activeAssignment.rubric_data.length > 0) {
      const sum = activeAssignment.rubric_data.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0);
      if (sum > 0) return sum;
    }
    if (effectiveQuestions.length > 0) {
      const sum = effectiveQuestions.reduce((sum, q) => sum + (parseFloat(q.max_score) || 0), 0);
      if (sum > 0) return sum;
    }
    return 20;
  }, [activeAssignment, effectiveQuestions]);

  const calculatedTotalFromQuestions = Object.values(questionScores).reduce((acc, v) => acc + (parseFloat(v) || 0), 0);

  // Per-question score steppers
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

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    const newScore = parseFloat(overrideScore);
    if (isNaN(newScore)) {
      alert('Please enter a valid numeric grade.');
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
          reasoning: q.reasoning || 'Manual grade adjustment by lecturer'
        };
      });

      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
        newScore,
        overrideComment || 'Grade overridden / adjusted by lecturer',
        updatedBreakdown
      );

      if (updated) {
        setOverrideScore(updated.score != null ? updated.score.toString() : newScore.toString());
      }
      alert(`Grade updated successfully! Final score is now ${newScore} / ${totalMaxScore}. Audit log recorded.`);
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
      const updatedBreakdown = effectiveQuestions.map((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        return {
          question_number: qKey,
          prompt: q.prompt,
          max_score: q.max_score,
          score_awarded: questionScores[qKey] != null ? questionScores[qKey] : (q.score_awarded ?? 0),
          reasoning: q.reasoning || 'Audited and approved by lecturer'
        };
      });

      const updated = await handleScoreOverride(
        activeSubmissionObj.id,
        currentScore,
        overrideComment || 'Audited and approved by lecturer',
        updatedBreakdown
      );
      if (updated) {
        setActiveSubmission(updated);
        setOverrideScore(updated.score != null ? updated.score.toString() : currentScore.toString());
      }
      alert('Grade approved successfully! Audit flag resolved and submission status updated to Graded & Approved.');
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
      alert('AI grading pipeline completed successfully!');
    } catch (err) {
      alert(`AI grading failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const renderHighlightedSnippet = (textSnippet, highlightsList) => {
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

        const matchIdx = part.toLowerCase().indexOf(quote.toLowerCase());
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

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {questionBlocks.map((block, bIdx) => {
          const matchHeader = block.trim().match(/^((?:Question|Q|Problem)\s+[A-Za-z0-9_()]+):?([\s\S]*)$/i);
          const headerTitle = matchHeader ? matchHeader[1] : null;
          const bodyContent = matchHeader ? matchHeader[2].trim() : block.trim();

          const mainKey = extractMainQKey(headerTitle || `Q${bIdx + 1}`);
          const matchedQuestion = effectiveQuestions.find(eq => extractMainQKey(eq.question_number) === mainKey);

          const isQConflicted = conflictedQuestions.has(mainKey);
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
                    📘 {headerTitle || `Question ${mainKey || bIdx + 1}`}
                  </span>
                  {isQConflicted && (
                    <span style={{ fontSize: '0.7rem', fontWeight: 700, backgroundColor: '#FEF3C7', color: '#B45309', padding: '0.1rem 0.4rem', borderRadius: '4px', border: '1px solid #FDE68A' }}>
                      ⚠️ Conflicted Question
                    </span>
                  )}
                </div>

                {matchedQuestion && (
                  matchedQuestion.score_awarded == null ? (
                    <span style={{
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      backgroundColor: 'rgba(59, 130, 246, 0.12)',
                      color: '#1d4ed8',
                      padding: '0.15rem 0.55rem',
                      borderRadius: '4px',
                      border: '1px solid rgba(59, 130, 246, 0.3)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      <Loader2 size={12} className="spin" /> Evaluating...
                    </span>
                  ) : (
                    <span style={{
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      backgroundColor: matchedQuestion.score_awarded > 0 ? 'var(--success-bg)' : 'var(--danger-bg)',
                      color: matchedQuestion.score_awarded > 0 ? 'var(--success)' : 'var(--danger)',
                      padding: '0.15rem 0.5rem',
                      borderRadius: '4px',
                      border: `1px solid ${matchedQuestion.score_awarded > 0 ? 'var(--success-border)' : 'var(--danger-border)'}`
                    }}>
                      Awarded: {matchedQuestion.score_awarded} / {matchedQuestion.max_score || 10} pts
                    </span>
                  )
                )}
              </div>

              {/* Student Response Content */}
              <div style={{ padding: '0.9rem 1rem', fontSize: '0.875rem', lineHeight: '1.65', color: 'var(--text-main)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-body)' }}>
                {isBodyEmpty ? (
                  <span style={{ color: 'var(--danger)', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <AlertTriangle size={14} color="var(--danger)" /> No response submitted for this question (-). 0 marks awarded.
                  </span>
                ) : (
                  renderHighlightedSnippet(bodyContent, highlightsList)
                )}
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
          Please choose a student submission from the Submissions List to review AI grading breakdown.
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
              title={prevSubmission ? `Previous: ${formatStudentName(prevSubmission.student_name, prevSubmission.student_id, prevSubmission.student_email)}` : 'First student'}
            >
              <ChevronLeft size={15} /> Prev
            </button>

            <span style={{ fontSize: '0.825rem', fontWeight: 700, color: 'var(--secondary)', padding: '0 0.65rem', minWidth: '110px', textAlign: 'center' }}>
              Student {currentIndex >= 0 ? `${currentIndex + 1} of ${reviewSubmissions.length}` : '—'}
            </span>

            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigateToSubmission(nextSubmission)}
              disabled={!nextSubmission}
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'flex', alignItems: 'center', gap: '0.25rem', opacity: !nextSubmission ? 0.4 : 1 }}
              title={nextSubmission ? `Next: ${formatStudentName(nextSubmission.student_name, nextSubmission.student_id, nextSubmission.student_email)}` : 'Last student'}
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

            {isSubmissionUnfinished ? (
              <span
                className="status-badge"
                style={{
                  backgroundColor: 'rgba(59, 130, 246, 0.12)',
                  color: '#1d4ed8',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  padding: '0.35rem 0.75rem',
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.45rem'
                }}
              >
                <Loader2 size={13} className="spin" /> AI Grading in Progress
              </span>
            ) : (
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
                {isFlagged ? '⚠️ Flagged for Audit' : '✓ Graded & Approved'}
              </span>
            )}
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
            {isSubmissionUnfinished ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#2563eb', fontSize: '0.95rem', fontWeight: 600 }}>
                <Loader2 size={15} className="spin" /> Evaluating...
              </span>
            ) : (
              <span style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)', lineHeight: 1 }}>
                {activeSubmissionObj.score != null ? activeSubmissionObj.score : '—'}
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 600 }}>{totalMaxScore ? ` / ${totalMaxScore}` : ''}</span>
              </span>
            )}
          </div>
        </div>

        {/* Row 3: SPECIFIC AUDIT & CONFLICT REASONS BANNER (If Flagged or Discrepancy Audit) */}
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
              {rawFlagReasons.map((reason, idx) => (
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
                    <span style={{ backgroundColor: '#FEF3C7', color: '#B45309', fontWeight: 700, fontSize: '0.725rem', padding: '0.15rem 0.45rem', borderRadius: '4px' }}>
                      Audit Alert
                    </span>
                    <span style={{ color: '#78350F', fontWeight: 600 }}>
                      {reason}
                    </span>
                  </div>
                </div>
              ))}
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
          {/* Card 1: Per-Question Score Overrides (Question by Question) */}
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
                {isSubmissionUnfinished ? 'Evaluating...' : `Sum: ${calculatedTotalFromQuestions} / ${totalMaxScore}`}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {isSubmissionUnfinished ? (
                <div style={{ padding: '1.25rem', backgroundColor: 'rgba(59, 130, 246, 0.08)', borderRadius: '8px', border: '1px solid rgba(59, 130, 246, 0.25)', textAlign: 'center' }}>
                  <Loader2 size={24} className="spin" color="#2563eb" style={{ margin: '0 auto 0.5rem auto' }} />
                  <p style={{ margin: '0 0 0.25rem 0', fontWeight: 600, color: '#1d4ed8', fontSize: '0.9rem' }}>
                    AI Grading In Progress
                  </p>
                  <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    Evaluation is actively underway in the background. Scores and rubric reasoning will populate here automatically.
                  </p>
                </div>
              ) : effectiveQuestions.length === 0 ? (
                <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-main)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
                  <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.825rem' }}>
                    {activeSubmissionObj.status === 'pending'
                      ? '⌛ Submission pending AI grading. Click "Run AI Grading" above.'
                      : 'No rubric breakdown available for this assignment.'}
                  </p>
                </div>
              ) : (
                effectiveQuestions.map((item, index) => {
                  const qKey = item.question_number || `Q${index + 1}`;
                  const mainKey = extractMainQKey(qKey);
                  const currentScoreVal = questionScores[qKey] != null ? questionScores[qKey] : (item.score_awarded ?? 0);
                  const maxSc = parseFloat(item.max_score || 10.0);
                  const isItemConflicted = conflictedQuestions.has(mainKey);

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
                            onClick={() => handleStepQuestionScore(qKey, maxSc, -stepIncrement)}
                            style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px', borderRadius: '4px' }}
                            title={`Decrease ${stepIncrement}`}
                          >
                            <Minus size={12} />
                          </button>

                          <input
                            type="number"
                            step={stepIncrement}
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
                            onClick={() => handleStepQuestionScore(qKey, maxSc, stepIncrement)}
                            style={{ padding: '0.15rem 0.35rem', minWidth: '22px', height: '26px', borderRadius: '4px' }}
                            title={`Increase ${stepIncrement}`}
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
                  Final Score (0 - {totalMaxScore})
                </label>
                <input
                  type="number"
                  step={stepIncrement}
                  min="0"
                  max={totalMaxScore}
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
              🔒 Overrides are recorded in audit logs with full delta traceability.
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
