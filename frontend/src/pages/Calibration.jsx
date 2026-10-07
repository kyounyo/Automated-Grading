import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload, BookOpen, CheckCircle2, ChevronRight, ArrowRight,
  Sparkles, Loader2, Target, Info, AlertTriangle, RefreshCw,
  Edit3, Plus, Minus, FileText, Check, Save, X, Award, ShieldAlert,
  FileSpreadsheet, CheckCircle, HelpCircle, Trash2
} from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import {
  fetchCalibrationStatus,
  updateCalibrationSettings,
  saveCalibrationExample,
  deleteCalibrationExample,
  importGradedCalibrationFile,
  previewCalibrationFile,
  downloadCalibrationTemplate
} from '../api/client';

/* ─── tiny helper ─── */
const StepBadge = ({ n, done }) => (
  <div style={{
    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
    backgroundColor: done ? '#16A34A' : 'var(--primary)',
    color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '0.8rem', fontWeight: 800
  }}>
    {done ? <CheckCircle2 size={14} /> : n}
  </div>
);

const Card = ({ children, style = {} }) => (
  <div className="card-panel" style={{ padding: '1.5rem 1.75rem', ...style }}>
    {children}
  </div>
);


/* ─── Main Calibration Component ─── */
const Calibration = () => {
  const navigate = useNavigate();
  const {
    currentAssignmentId,
    currentAssignment,
    submissions,
    loadSubmissions,
    handleUpdateAssignment,
    handleScoreOverride,
    triggerGradeAll
  } = useAssignment();

  const [calStatus, setCalStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [targetSamples, setTargetSamples] = useState(3);
  const [savingSampleSize, setSavingSampleSize] = useState(false);

  // Method choice: 'studio' (grade in system) | 'upload' (upload spreadsheet)
  const [calMethod, setCalMethod] = useState('studio');

  // Selected Calibration Paper for Inline Studio
  const [selectedSampleId, setSelectedSampleId] = useState(null);

  // Inline Marking Studio Card State per question
  const [calCardState, setCalCardState] = useState({});
  const [expandedAnswers, setExpandedAnswers] = useState({});
  const [savingAllCal, setSavingAllCal] = useState(false);
  const [savedSampleIds, setSavedSampleIds] = useState(new Set());

  // Upload & Smart Preview State
  const [importFile, setImportFile] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  // Quick navigation / grade trigger state
  const [startingGrading, setStartingGrading] = useState(false);

  const calSamples = useMemo(() => {
    const all = submissions || [];
    if (all.length === 0) return [];

    // Submissions explicitly flagged as calibration sample
    const tagged = all.filter(s => s.is_calibration_sample);

    // If we have enough or more tagged than targetSamples, show the first targetSamples
    if (tagged.length >= targetSamples) {
      return tagged.slice(0, targetSamples);
    }

    // Otherwise, seamlessly supplement with student submissions to fulfill targetSamples
    const taggedIds = new Set(tagged.map(s => s.id));
    const extra = all.filter(s => !taggedIds.has(s.id)).slice(0, targetSamples - tagged.length);
    return [...tagged, ...extra];
  }, [submissions, targetSamples]);

  const gradedCalSamples = useMemo(() => {
    return calSamples.filter(s =>
      s.status === 'graded' || s.status === 'approved' || s.status === 'flagged' || s.score != null
    );
  }, [calSamples]);

  // Auto-select paper #1 if none selected or if selected sample is out of range
  useEffect(() => {
    if (calSamples.length > 0) {
      if (!selectedSampleId || !calSamples.some(s => s.id === selectedSampleId)) {
        setSelectedSampleId(calSamples[0].id);
      }
    }
  }, [calSamples, selectedSampleId]);

  const loadStatus = useCallback(async () => {
    if (!currentAssignmentId) return;
    try {
      setLoading(true);
      const data = await fetchCalibrationStatus(currentAssignmentId);
      setCalStatus(data);
      if (data?.calibration_sample_size != null) {
        setTargetSamples(data.calibration_sample_size);
      }
    } catch (e) {
      console.warn('Could not load calibration status:', e);
    } finally {
      setLoading(false);
    }
  }, [currentAssignmentId]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    if (currentAssignment?.calibration_sample_size != null) {
      setTargetSamples(currentAssignment.calibration_sample_size);
    }
  }, [currentAssignment?.calibration_sample_size]);

  // Active sample paper in the studio
  const activeSample = useMemo(() => {
    if (!selectedSampleId) return calSamples[0] || null;
    return calSamples.find(s => s.id === selectedSampleId) || calSamples[0] || null;
  }, [calSamples, selectedSampleId]);

  const activeSampleIndex = useMemo(() => {
    if (!activeSample) return -1;
    return calSamples.findIndex(s => s.id === activeSample.id);
  }, [calSamples, activeSample]);

  const nextCalSample = useMemo(() => {
    if (activeSampleIndex >= 0 && activeSampleIndex < calSamples.length - 1) {
      return calSamples[activeSampleIndex + 1];
    }
    return null;
  }, [calSamples, activeSampleIndex]);

  // Questions breakdown for the active sample
  const rubricQuestions = currentAssignment?.rubric_data || [];
  const effectiveQuestions = useMemo(() => {
    if (rubricQuestions && rubricQuestions.length > 0) {
      return rubricQuestions.map((rq, idx) => {
        const qNum = rq.question_number || `Q${idx + 1}`;
        const bdMatch = activeSample?.feedback?.breakdown?.find(b => (b.question_number || '').toUpperCase() === qNum.toUpperCase()) || {};
        return {
          question_number: qNum,
          prompt: rq.prompt || rq.text || `Question ${qNum}`,
          model_answer: rq.model_answer || rq.modelAnswer || '',
          max_score: parseFloat(rq.max_score || rq.maxMark || bdMatch.max_score || 10),
          score_awarded: bdMatch.score_awarded ?? bdMatch.score ?? null,
          reasoning: bdMatch.reasoning || ''
        };
      });
    } else if (activeSample?.feedback?.breakdown && activeSample.feedback.breakdown.length > 0) {
      return activeSample.feedback.breakdown.map((bd, idx) => ({
        question_number: bd.question_number || `Q${idx + 1}`,
        prompt: bd.prompt || `Question ${bd.question_number || idx + 1}`,
        model_answer: bd.model_answer || '',
        max_score: parseFloat(bd.max_score || 10),
        score_awarded: bd.score_awarded ?? bd.score ?? null,
        reasoning: bd.reasoning || ''
      }));
    }
    return [];
  }, [rubricQuestions, activeSample]);

  // Helper to extract student answer completely for a given question without arbitrary truncation
  const extractStudentAnswer = (rawText, qKey, allQKeys = []) => {
    if (!rawText) return '';
    const rawClean = rawText.trim();
    if (!rawClean) return '';

    const cleanQ = String(qKey || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
    const numMatch = cleanQ.match(/\d+/);
    const numOnly = numMatch ? numMatch[0] : cleanQ;

    const lines = rawText.split('\n');

    // 1. Target question matching patterns
    // Matches headers like: "Question Q9:", "Question 9:", "Q9:", "Q9", "### Question Q9", "**Question 9:**", "Problem 9:", "9."
    const targetPatterns = [
      new RegExp(`^[#*_\\s>\\[\\(]*(?:Question|Problem|Part|Item|Task)\\s*[#\\.\\-\\:]*\\s*(?:Q\\s*)?${numOnly}\\b`, 'i'),
      new RegExp(`^[#*_\\s>\\[\\(]*Q\\s*[#\\.\\-\\:]*\\s*${numOnly}\\b`, 'i'),
      new RegExp(`^[#*_\\s>\\[\\(]*${cleanQ}\\b`, 'i'),
      new RegExp(`^[#*_\\s>\\[\\(]*${numOnly}[\\.\\:\\)]\\s+`, 'i'),
      new RegExp(`\\b(?:Question|Problem)\\s+(?:Q\\s*)?${numOnly}\\b`, 'i')
    ];

    let startIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (targetPatterns.some(p => p.test(line))) {
        startIdx = i;
        break;
      }
    }

    // Fallback: If not found and only 1 question exists, entire text is the answer
    if (startIdx === -1) {
      if (allQKeys && allQKeys.length === 1) {
        return rawClean;
      }
      for (let i = 0; i < lines.length; i++) {
        const stripped = lines[i].replace(/[^A-Za-z0-9]/g, '').toUpperCase();
        if (stripped.includes(cleanQ)) {
          startIdx = i;
          break;
        }
      }
    }

    // If still not found, return full text without arbitrary slicing
    if (startIdx === -1) {
      return rawClean;
    }

    // 2. Build patterns for other questions to know where to stop
    const otherPatterns = [];
    if (allQKeys && allQKeys.length > 1) {
      allQKeys.forEach(otherKey => {
        if (!otherKey || String(otherKey).trim().toUpperCase() === String(qKey).trim().toUpperCase()) return;
        const otherClean = String(otherKey).replace(/[^A-Za-z0-9]/g, '').toUpperCase();
        const oNumMatch = otherClean.match(/\d+/);
        if (oNumMatch) {
          const oNum = oNumMatch[0];
          otherPatterns.push(new RegExp(`^[#*_\\s>\\[\\(]*(?:Question|Problem|Part|Item|Task)\\s*[#\\.\\-\\:]*\\s*(?:Q\\s*)?${oNum}\\b`, 'i'));
          otherPatterns.push(new RegExp(`^[#*_\\s>\\[\\(]*Q\\s*[#\\.\\-\\:]*\\s*${oNum}\\b`, 'i'));
          otherPatterns.push(new RegExp(`^[#*_\\s>\\[\\(]*${oNum}[\\.\\:\\)]\\s+`, 'i'));
        }
        otherPatterns.push(new RegExp(`^[#*_\\s>\\[\\(]*${otherClean}\\b`, 'i'));
        otherPatterns.push(new RegExp(`\\b(?:Question|Problem)\\s+(?:Q\\s*)?${otherClean}\\b`, 'i'));
      });
    }

    const genericNextPattern = /^[#*_\s>\[\(]*(?:Question|Problem|Task)\s*[#\.\-\:]*\s*(?:Q\s*)?(\d+)\b/i;
    const genericQPattern = /^[#*_\s>\[\(]*Q\s*[#\.\-\\:]*\s*(\d+)\b/i;

    // 3. Extract lines starting from startIdx
    const firstLine = lines[startIdx].trim();
    const collected = [];

    // Strip header prefix from first line, e.g. "Question Q9: Melissa: 6..." -> "Melissa: 6..."
    const headerStripPattern = new RegExp(`^[#*_\\s>\\[\\(]*(?:Question|Problem|Part|Item|Task)?\\s*[#\\.\\-\\:]*\\s*(?:Q\\s*)?${numOnly}(?:[A-Za-z])?[\\:\\.\\)\\-\\]\\*\\_]*\\s*(.*)$`, 'i');
    const headerMatch = firstLine.match(headerStripPattern);

    if (headerMatch) {
      const remainder = headerMatch[1].trim();
      if (remainder) {
        collected.push(remainder);
      }
    } else {
      collected.push(firstLine);
    }

    for (let j = startIdx + 1; j < lines.length; j++) {
      const lineTrim = lines[j].trim();

      // Check if line marks start of another specific question
      const isOtherQ = otherPatterns.some(p => p.test(lineTrim));
      if (isOtherQ) break;

      // Check generic next question header with different number
      const mGen = lineTrim.match(genericNextPattern) || lineTrim.match(genericQPattern);
      if (mGen && mGen[1] !== numOnly) {
        break;
      }

      collected.push(lines[j]);
    }

    return collected.join('\n').trim();
  };

  // Sync state whenever activeSample changes
  const activeSampleIdRef = useRef(null);
  useEffect(() => {
    if (!activeSample) return;
    const isDifferentSample = activeSampleIdRef.current !== activeSample.id;
    activeSampleIdRef.current = activeSample.id;

    const rawText = activeSample.raw_text || activeSample.extracted_text || '';
    const allQKeys = effectiveQuestions.map((q, idx) => q.question_number || `Q${idx + 1}`);

    setCalCardState(prev => {
      const next = {};
      effectiveQuestions.forEach((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        const defaultStudentAnswer = extractStudentAnswer(rawText, qKey, allQKeys);
        const existing = isDifferentSample ? null : prev[qKey];
        next[qKey] = {
          score: existing?.score != null ? existing.score : (q.score_awarded != null ? q.score_awarded : q.max_score),
          anchorType: existing?.anchorType || 'full_credit',
          feedback: existing?.feedback !== undefined ? existing.feedback : (q.reasoning || ''),
          studentText: defaultStudentAnswer,
          saving: false,
          saveSuccess: false,
          saveError: null
        };
      });
      return next;
    });
  }, [activeSample?.id, activeSample?.raw_text, effectiveQuestions.length]);

  const updateCalCard = (qKey, updates) => {
    setCalCardState(prev => ({
      ...prev,
      [qKey]: { ...prev[qKey], ...updates }
    }));
  };

  const toggleExpandAnswer = (qKey) => {
    setExpandedAnswers(prev => ({ ...prev, [qKey]: !prev[qKey] }));
  };

  // Save single question calibration exemplar
  const handleSaveExemplar = async (qKey, qObj) => {
    if (!currentAssignmentId || !activeSample) return;
    const card = calCardState[qKey] || {};
    const studentText = (card.studentText || '').trim();
    const scoreVal = card.score != null ? parseFloat(card.score) : (qObj.score_awarded ?? 0);
    const maxSc = qObj.max_score || 10;
    const feedbackText = (card.feedback || '').trim();
    const anchor = (scoreVal >= maxSc * 0.8) ? 'full_credit' : (scoreVal <= maxSc * 0.3) ? 'common_error' : 'partial_credit';

    if (!studentText) {
      alert(`Please provide the student response snippet for ${qKey} before saving.`);
      return;
    }

    updateCalCard(qKey, { saving: true, saveError: null, saveSuccess: false });

    try {
      await saveCalibrationExample(currentAssignmentId, {
        submission_id: activeSample.id,
        question_number: qKey,
        student_text: studentText,
        examiner_score: scoreVal,
        max_score: maxSc,
        examiner_feedback: feedbackText || `Exemplar baseline for ${qKey}`,
        anchor_type: anchor
      });

      // Persistently retain saved state so user knows the AI received it
      updateCalCard(qKey, { saving: false, saveSuccess: true, saveError: null });
      await loadStatus();
    } catch (err) {
      updateCalCard(qKey, { saving: false, saveError: err.message, saveSuccess: false });
      alert(`Could not save exemplar for ${qKey}: ${err.message}`);
    }
  };

  // 1-Click: Save all marks AND automatically register all question exemplars for this calibration sample paper!
  const handleSaveAllCalibrationMarks = async () => {
    if (!activeSample || !currentAssignmentId) return;
    try {
      setSavingAllCal(true);
      const updatedBreakdown = effectiveQuestions.map((q, idx) => {
        const qKey = q.question_number || `Q${idx + 1}`;
        const card = calCardState[qKey] || {};
        const scoreVal = card.score != null ? parseFloat(card.score) : (q.score_awarded ?? 0);
        return {
          question_number: qKey,
          prompt: q.prompt,
          max_score: q.max_score,
          score_awarded: scoreVal,
          reasoning: card.feedback || 'Lecturer calibration baseline score'
        };
      });

      const totalCalculated = updatedBreakdown.reduce((sum, item) => sum + (parseFloat(item.score_awarded) || 0), 0);
      const roundedTotal = Math.round(totalCalculated * 10) / 10;

      // 1. Save confirmed paper marks in database
      await handleScoreOverride(
        activeSample.id,
        roundedTotal,
        'Lecturer confirmed calibration sample grade',
        updatedBreakdown
      );

      // 2. Automatically register/update EVERY question as a calibration exemplar in 1 click
      let registeredCount = 0;
      for (let idx = 0; idx < effectiveQuestions.length; idx++) {
        const q = effectiveQuestions[idx];
        const qKey = q.question_number || `Q${idx + 1}`;
        const card = calCardState[qKey] || {};
        const studentText = (card.studentText || '').trim();
        const scoreVal = card.score != null ? parseFloat(card.score) : (q.score_awarded ?? 0);
        const maxSc = q.max_score || 10;
        const feedbackText = (card.feedback || '').trim();
        const anchor = (scoreVal >= maxSc * 0.8) ? 'full_credit' : (scoreVal <= maxSc * 0.3) ? 'common_error' : 'partial_credit';

        if (studentText) {
          try {
            await saveCalibrationExample(currentAssignmentId, {
              submission_id: activeSample.id,
              question_number: qKey,
              student_text: studentText,
              examiner_score: scoreVal,
              max_score: maxSc,
              examiner_feedback: feedbackText || `Exemplar baseline for ${qKey}`,
              anchor_type: anchor
            });
            registeredCount++;
            updateCalCard(qKey, { saveSuccess: true, saveError: null });
          } catch (exErr) {
            console.warn(`Could not auto-register exemplar for ${qKey}:`, exErr);
          }
        }
      }

      // 3. Mark current sample paper as fully saved & calibrated
      setSavedSampleIds(prev => new Set([...prev, activeSample.id]));

      // 4. Synchronize status & submissions
      await loadStatus();
      if (loadSubmissions) {
        await loadSubmissions(currentAssignmentId, true);
      }
    } catch (err) {
      alert(`Could not save paper marks: ${err.message}`);
    } finally {
      setSavingAllCal(false);
    }
  };

  // Flexible Sample Size updater (1 to 50)
  const handleUpdateSampleSize = async (newVal) => {
    if (!currentAssignmentId || savingSampleSize) return;
    const size = Math.max(1, Math.min(50, parseInt(newVal) || 3));
    setTargetSamples(size);
    try {
      setSavingSampleSize(true);
      await updateCalibrationSettings(currentAssignmentId, {
        calibration_sample_size: size,
        calibration_enabled: true
      });
      if (handleUpdateAssignment) {
        await handleUpdateAssignment(currentAssignmentId, {
          calibration_sample_size: size,
          calibration_enabled: true
        }).catch(() => {});
      }
      await loadStatus();
      if (loadSubmissions) {
        await loadSubmissions(currentAssignmentId, true);
      }
    } catch (err) {
      alert(`Could not update sample size: ${err.message}`);
    } finally {
      setSavingSampleSize(false);
    }
  };


  // Smart Header File Picker & Instant Preview
  const handleFileSelect = async (file) => {
    if (!file || !currentAssignmentId) return;
    setImportFile(file);
    setPreviewError(null);
    setPreviewData(null);
    setImportResult(null);
    setPreviewLoading(true);

    try {
      const fd = new FormData();
      fd.append('file', file);
      const data = await previewCalibrationFile(currentAssignmentId, fd);
      setPreviewData(data);
    } catch (err) {
      console.error('Spreadsheet preview error:', err);
      setPreviewError(err.message || 'Failed to inspect calibration spreadsheet.');
    } finally {
      setPreviewLoading(false);
    }
  };

  // All active calibrated exemplars currently in the system from database
  const activeSavedExemplars = useMemo(() => {
    if (!calStatus?.questions) return [];
    const list = [];
    calStatus.questions.forEach(q => {
      if (Array.isArray(q.examples)) {
        q.examples.forEach(ex => {
          list.push({
            ...ex,
            question_number: ex.question_number || q.question_number
          });
        });
      }
    });
    return list;
  }, [calStatus]);

  // Confirm Import
  const handleImport = async () => {
    if (!importFile || !currentAssignmentId) return;
    try {
      setImporting(true);
      const fd = new FormData();
      fd.append('file', importFile);
      const result = await importGradedCalibrationFile(currentAssignmentId, fd);
      setImportResult(result);
      // Keep preview data visible and mark as successfully imported
      setPreviewData(prev => prev ? { ...prev, isImported: true } : null);
      await loadStatus();
      if (loadSubmissions) {
        await loadSubmissions(currentAssignmentId, true);
      }
    } catch (e) {
      alert(`Import failed: ${e.message}`);
    } finally {
      setImporting(false);
    }
  };

  // Delete an individual calibrated exemplar
  const handleDeleteExample = async (exampleId) => {
    if (!window.confirm('Are you sure you want to remove this calibration exemplar?')) return;
    try {
      await deleteCalibrationExample(currentAssignmentId, exampleId);
      await loadStatus();
    } catch (err) {
      alert(`Could not delete example: ${err.message}`);
    }
  };

  // "Go to Submissions & Grade" Action Handler
  const handleGoToSubmissionsAndGrade = () => {
    setStartingGrading(true);
    navigate('/submissions', { state: { startGrading: true } });
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

  const calibrated = calStatus?.total_calibrated_examples || 0;
  const isReady = calibrated >= targetSamples;
  const assignmentName = currentAssignment
    ? `${currentAssignment.course_code ? currentAssignment.course_code + ': ' : ''}${currentAssignment.title}`
    : 'Current Assignment';

  const totalMaxScore = useMemo(() => {
    return effectiveQuestions.reduce((sum, q) => sum + (parseFloat(q.max_score) || 0), 0);
  }, [effectiveQuestions]);

  const calculatedStudioTotal = useMemo(() => {
    return Object.values(calCardState).reduce((acc, v) => acc + (parseFloat(v?.score) || 0), 0);
  }, [calCardState]);

  // Lookup map of saved calibration examples keyed by `${submission_id}_${question_number}`
  const savedExemplarsMap = useMemo(() => {
    if (!calStatus?.questions) return {};
    const map = {};
    for (const q of calStatus.questions) {
      const qClean = (q.question_number || '').trim().toUpperCase();
      if (q.examples && Array.isArray(q.examples)) {
        for (const ex of q.examples) {
          if (ex.submission_id) {
            map[`${ex.submission_id}_${qClean}`] = ex;
          }
        }
      }
    }
    return map;
  }, [calStatus]);

  // Determines whether the currently active sample paper has all marks & exemplars registered
  const isPaperFullySaved = useMemo(() => {
    if (!activeSample) return false;
    if (savedSampleIds.has(activeSample.id)) return true;
    if (activeSample.score != null || activeSample.status === 'graded' || activeSample.status === 'approved') return true;
    if (effectiveQuestions.length > 0 && effectiveQuestions.every(q => {
      const qClean = (q.question_number || '').trim().toUpperCase();
      return Boolean(savedExemplarsMap[`${activeSample.id}_${qClean}`]);
    })) {
      return true;
    }
    return false;
  }, [activeSample, savedSampleIds, effectiveQuestions, savedExemplarsMap]);

  if (!currentAssignmentId) {
    return (
      <div style={{ maxWidth: 640, margin: '4rem auto', textAlign: 'center' }}>
        <Target size={48} color="var(--primary)" style={{ opacity: 0.5, marginBottom: '1rem' }} />
        <h3 style={{ margin: '0 0 0.5rem', color: 'var(--secondary)' }}>No Assignment Selected</h3>
        <p style={{ color: 'var(--text-muted)' }}>Select an assignment from the dropdown above to set up calibration.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem', paddingBottom: '3rem' }}>

      {/* ── Header ── */}
      <div>
        <h2 style={{ margin: 0, fontSize: '1.45rem', fontWeight: 800, color: 'var(--secondary)' }}>
          🎯 Calibration Setup
        </h2>
        <p style={{ margin: '0.3rem 0 0', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          {assignmentName} · Teach the AI to match your marking style before grading the whole class.
        </p>
      </div>

      {/* ── Progress strip ── */}
      {!loading && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '0', backgroundColor: 'var(--surface)',
          border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden'
        }}>
          {[
            { label: 'Choose method', done: true },
            { label: 'Establish benchmarks', done: calibrated > 0 },
            { label: 'Ready to grade', done: isReady },
          ].map((step, i, arr) => (
            <React.Fragment key={i}>
              <div style={{
                flex: 1, padding: '0.75rem 1rem',
                backgroundColor: step.done ? 'var(--primary-light)' : 'transparent',
                display: 'flex', alignItems: 'center', gap: '0.55rem'
              }}>
                <StepBadge n={i + 1} done={step.done} />
                <span style={{ fontSize: '0.825rem', fontWeight: 600, color: step.done ? 'var(--primary-dark)' : 'var(--text-muted)' }}>
                  {step.label}
                </span>
              </div>
              {i < arr.length - 1 && (
                <ChevronRight size={16} color="var(--border)" style={{ flexShrink: 0 }} />
              )}
            </React.Fragment>
          ))}
        </div>
      )}


      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '2rem', color: 'var(--text-muted)' }}>
          <Loader2 size={20} className="spin" /> Loading calibration status…
        </div>
      )}

      {/* ── 1. CHOOSE CALIBRATION METHOD (Prominently at the top) ── */}
      {!loading && (
        <Card>
          <div style={{ marginBottom: '1rem' }}>
            <h3 style={{ margin: '0 0 0.3rem', fontSize: '1.05rem', fontWeight: 800, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <StepBadge n={1} done={calibrated > 0} />
              Choose How You Want to Calibrate
            </h3>
            <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--text-muted)', marginLeft: '2.35rem' }}>
              Select your preferred calibration workflow. You can grade benchmark papers directly in our marking studio or upload an existing spreadsheet.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginLeft: '2.35rem' }}>
            {/* Method A: Grade in this system */}
            <button
              type="button"
              onClick={() => {
                setCalMethod('studio');
                setPreviewData(null);
                setPreviewError(null);
              }}
              style={{
                padding: '1.2rem',
                borderRadius: '10px',
                textAlign: 'left',
                cursor: 'pointer',
                border: calMethod === 'studio' ? '2.5px solid var(--primary)' : '1px solid var(--border)',
                backgroundColor: calMethod === 'studio' ? 'var(--primary-light)' : 'var(--surface)',
                boxShadow: calMethod === 'studio' ? '0 4px 12px rgba(79, 70, 229, 0.12)' : 'none',
                transition: 'all 0.18s ease',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.6rem'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: '8px',
                    backgroundColor: calMethod === 'studio' ? 'var(--primary)' : '#e0e7ff',
                    color: calMethod === 'studio' ? '#fff' : 'var(--primary)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                  }}>
                    <BookOpen size={18} />
                  </div>
                  <strong style={{ fontSize: '0.95rem', color: 'var(--secondary)' }}>
                    Grade in this system
                  </strong>
                </div>
              </div>

              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Mark benchmark papers directly in our interactive studio. Choose any sample size and save exemplars per question.
              </p>

              <span style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--primary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                {calSamples.length > 0 ? `${calSamples.length} student papers set aside` : 'Flexible Marking Studio'} <ArrowRight size={13} />
              </span>
            </button>

            {/* Method B: Upload spreadsheet */}
            <button
              type="button"
              onClick={() => {
                setCalMethod('upload');
              }}
              style={{
                padding: '1.2rem',
                borderRadius: '10px',
                textAlign: 'left',
                cursor: 'pointer',
                border: calMethod === 'upload' ? '2.5px solid #4f46e5' : '1px solid var(--border)',
                backgroundColor: calMethod === 'upload' ? 'rgba(99, 102, 241, 0.08)' : 'var(--surface)',
                boxShadow: calMethod === 'upload' ? '0 4px 12px rgba(99, 102, 241, 0.12)' : 'none',
                transition: 'all 0.18s ease',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.6rem'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: '8px',
                    backgroundColor: calMethod === 'upload' ? '#4f46e5' : '#ede9fe',
                    color: calMethod === 'upload' ? '#fff' : '#4f46e5',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                  }}>
                    <Upload size={18} />
                  </div>
                  <strong style={{ fontSize: '0.95rem', color: 'var(--secondary)' }}>
                    Upload calibrated Excel / CSV
                  </strong>
                </div>
              </div>

              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Already have marked papers? Upload your spreadsheet with smart header detection. Feedback is optional.
              </p>

              <span style={{ fontSize: '0.775rem', fontWeight: 700, color: '#4f46e5', display: 'flex', alignItems: 'center', gap: 4 }}>
                Header-Sensitive Excel / CSV <ArrowRight size={13} />
              </span>
            </button>
          </div>
        </Card>
      )}

      {/* ── METHOD 1: GRADE IN THIS SYSTEM ── */}
      {!loading && calMethod === 'studio' && (
        <>
          {/* Flexible Sample Size Stepper (ONLY shown for grade in this system) */}
          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <Target size={18} color="var(--primary)" />
                  <span style={{ fontWeight: 800, fontSize: '0.95rem', color: 'var(--secondary)' }}>
                    Target Calibration Sample Size
                  </span>
                  <span style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    color: 'var(--primary)',
                    backgroundColor: 'var(--primary-light)',
                    padding: '0.15rem 0.55rem',
                    borderRadius: '999px',
                    border: '1px solid var(--border)'
                  }}>
                    {targetSamples} paper{targetSamples === 1 ? '' : 's'}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  Select any number of student papers for calibration exemplar marking (e.g. 1, 2, 3, 4, 5, 6, 7, 8... up to 50).
                  {savingSampleSize && <span style={{ marginLeft: 8, color: 'var(--primary)', fontWeight: 600 }}>Saving changes…</span>}
                </p>
              </div>

              {/* Flexible Stepper: Minus, Direct Numeric Input, Plus */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.3rem',
                  border: '1.5px solid var(--primary)',
                  borderRadius: '8px',
                  padding: '3px 8px',
                  backgroundColor: '#fff',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.06)'
                }}>
                  <button
                    type="button"
                    onClick={() => handleUpdateSampleSize(Math.max(1, targetSamples - 1))}
                    disabled={savingSampleSize || targetSamples <= 1}
                    style={{
                      width: '28px',
                      height: '28px',
                      borderRadius: '5px',
                      border: '1px solid var(--border)',
                      backgroundColor: targetSamples <= 1 ? '#f3f4f6' : 'var(--bg-main)',
                      cursor: targetSamples <= 1 ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: targetSamples <= 1 ? 'var(--text-dim)' : 'var(--secondary)'
                    }}
                    title="Decrease sample size"
                  >
                    <Minus size={14} />
                  </button>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={targetSamples}
                    onChange={(e) => {
                      const v = parseInt(e.target.value);
                      if (!isNaN(v) && v >= 1 && v <= 50) {
                        handleUpdateSampleSize(v);
                      }
                    }}
                    disabled={savingSampleSize}
                    style={{
                      width: '45px',
                      height: '28px',
                      textAlign: 'center',
                      fontWeight: 800,
                      fontSize: '0.95rem',
                      border: 'none',
                      background: 'none',
                      outline: 'none',
                      color: 'var(--secondary)'
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => handleUpdateSampleSize(Math.min(50, targetSamples + 1))}
                    disabled={savingSampleSize || targetSamples >= 50}
                    style={{
                      width: '28px',
                      height: '28px',
                      borderRadius: '5px',
                      border: '1px solid var(--border)',
                      backgroundColor: targetSamples >= 50 ? '#f3f4f6' : 'var(--bg-main)',
                      cursor: targetSamples >= 50 ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: targetSamples >= 50 ? 'var(--text-dim)' : 'var(--secondary)'
                    }}
                    title="Increase sample size"
                  >
                    <Plus size={14} />
                  </button>
                </div>
              </div>
            </div>
          </Card>

          {/* If no submissions uploaded yet */}
          {calSamples.length === 0 && (
            <Card style={{ textAlign: 'center', padding: '2.5rem 1.5rem' }}>
              <FileText size={36} color="var(--primary)" style={{ opacity: 0.6, marginBottom: '0.75rem' }} />
              <h4 style={{ margin: '0 0 0.4rem', color: 'var(--secondary)', fontSize: '1.05rem' }}>
                No Student Papers Available to Mark Yet
              </h4>
              <p style={{ margin: '0 0 1.25rem', color: 'var(--text-muted)', fontSize: '0.83rem', maxWidth: 460, marginLeft: 'auto', marginRight: 'auto' }}>
                Please upload your student submissions in the Bulk Upload page first, or switch to "Upload Calibrated Excel / CSV" above.
              </p>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => navigate('/bulk-upload')}
                style={{ fontSize: '0.825rem', padding: '0.45rem 1.1rem' }}
              >
                Go to Bulk Upload
              </button>
            </Card>
          )}

          {/* INLINE CALIBRATION MARKING STUDIO with Sleek Top Paper Switcher */}
          {activeSample && (
            <div id="calibration-marking-studio">
              <Card style={{
                border: '2px solid var(--primary)',
                backgroundColor: 'var(--surface)',
                boxShadow: '0 4px 14px rgba(79, 70, 229, 0.09)'
              }}>
                {/* Header & Clean Paper Switcher Bar */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderBottom: '1px solid var(--border)',
                  paddingBottom: '0.85rem',
                  marginBottom: '1rem',
                  flexWrap: 'wrap',
                  gap: '0.75rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
                    {/* Previous Paper */}
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => {
                        if (activeSampleIndex > 0) {
                          setSelectedSampleId(calSamples[activeSampleIndex - 1].id);
                        }
                      }}
                      disabled={activeSampleIndex <= 0}
                      style={{ padding: '0.35rem 0.65rem', fontSize: '0.78rem' }}
                      title="Previous sample paper"
                    >
                      ◀ Prev
                    </button>

                    <span style={{
                      fontSize: '0.78rem',
                      fontWeight: 800,
                      padding: '0.25rem 0.65rem',
                      borderRadius: '6px',
                      backgroundColor: '#4f46e5',
                      color: '#fff'
                    }}>
                      Paper #{activeSampleIndex + 1} of {calSamples.length}
                    </span>

                    {/* Next Paper */}
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => {
                        if (activeSampleIndex < calSamples.length - 1) {
                          setSelectedSampleId(calSamples[activeSampleIndex + 1].id);
                        }
                      }}
                      disabled={activeSampleIndex >= calSamples.length - 1}
                      style={{ padding: '0.35rem 0.65rem', fontSize: '0.78rem' }}
                      title="Next sample paper"
                    >
                      Next ▶
                    </button>

                    {/* Quick Jump Dropdown */}
                    <select
                      value={activeSample?.id || ''}
                      onChange={(e) => setSelectedSampleId(e.target.value)}
                      style={{
                        padding: '0.3rem 0.6rem',
                        borderRadius: '6px',
                        border: '1px solid var(--border)',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        color: 'var(--secondary)',
                        backgroundColor: '#fff'
                      }}
                    >
                      {calSamples.map((s, idx) => (
                        <option key={s.id} value={s.id}>
                          Paper #{idx + 1}: {formatStudentName(s.student_name, s.student_id, s.student_email)} {s.score != null ? `(${s.score} pts)` : '(Pending)'}
                        </option>
                      ))}
                    </select>

                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      (ID: {activeSample.student_id})
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                    <span style={{
                      fontSize: '0.85rem',
                      fontWeight: 800,
                      color: '#4f46e5',
                      backgroundColor: 'rgba(99, 102, 241, 0.1)',
                      padding: '0.3rem 0.75rem',
                      borderRadius: '6px',
                      border: '1px solid rgba(99, 102, 241, 0.3)'
                    }}>
                      Total: {Math.round(calculatedStudioTotal * 10) / 10} / {totalMaxScore} pts
                    </span>
                  </div>
                </div>

                {/* 1-Click Calibration Tip */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.65rem 0.95rem',
                  backgroundColor: '#F0FDF4',
                  border: '1px solid #BBF7D0',
                  borderRadius: '6px',
                  fontSize: '0.8rem',
                  color: '#166534',
                  gap: '0.5rem'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Sparkles size={15} style={{ flexShrink: 0, color: '#16A34A' }} />
                    <span>
                      <strong>1-Click Quick Calibration:</strong> Adjust marks per question below, then click <strong>"Save All Marks & Register Exemplars"</strong> at the bottom to register all questions at once.
                    </span>
                  </div>
                </div>

                {/* Questions List */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  {effectiveQuestions.map((q, idx) => {
                    const qKey = q.question_number || `Q${idx + 1}`;
                    const cleanQKey = qKey.trim().toUpperCase();
                    const card = calCardState[qKey] || {};
                    const currentScoreVal = card.score != null ? card.score : (q.score_awarded ?? q.max_score);
                    const maxSc = q.max_score || 10;
                    const isExpanded = Boolean(expandedAnswers[qKey]);

                    const qStatusObj = calStatus?.questions?.find(qs => qs.question_number.toUpperCase() === cleanQKey);
                    const isQuestionCalibrated = (qStatusObj?.sample_count || 0) > 0;
                    const isExemplarSaved = Boolean(savedExemplarsMap[`${activeSample?.id}_${cleanQKey}`]) || Boolean(card.saveSuccess);

                    return (
                      <div
                        key={qKey}
                        style={{
                          padding: '1.1rem',
                          borderRadius: '8px',
                          backgroundColor: 'var(--bg-main)',
                          border: isExemplarSaved ? '1.5px solid #10b981' : isQuestionCalibrated ? '1px solid rgba(99, 102, 241, 0.35)' : '1px solid var(--border)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.75rem',
                          transition: 'border 0.2s ease'
                        }}
                      >
                        {/* Header */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
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
                            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                              Max: {maxSc} pts
                            </span>
                            {isExemplarSaved && (
                              <span style={{
                                fontSize: '0.72rem',
                                fontWeight: 700,
                                padding: '0.15rem 0.5rem',
                                borderRadius: '4px',
                                backgroundColor: '#ECFDF5',
                                color: '#059669',
                                border: '1px solid #A7F3D0',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '3px'
                              }}>
                                <Check size={11} /> Saved for this student
                              </span>
                            )}
                            {isQuestionCalibrated && !isExemplarSaved && (
                              <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', backgroundColor: 'rgba(16, 185, 129, 0.1)', color: '#059669', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                                ✓ {qStatusObj.sample_count} Exemplar{qStatusObj.sample_count === 1 ? '' : 's'} (v{qStatusObj.version})
                              </span>
                            )}
                          </div>

                          <button
                            type="button"
                            onClick={() => toggleExpandAnswer(qKey)}
                            style={{
                              background: 'none',
                              border: 'none',
                              fontSize: '0.775rem',
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
                        <div style={{ fontSize: '0.85rem', color: 'var(--secondary)', fontWeight: 600, lineHeight: '1.45' }}>
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

                        {/* Student Response Display (Read-Only) */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                              Student Answer for {qKey}:
                            </span>
                            <span style={{
                              fontSize: '0.68rem',
                              fontWeight: 600,
                              color: 'var(--text-muted)',
                              backgroundColor: 'rgba(100, 116, 139, 0.12)',
                              padding: '0.1rem 0.45rem',
                              borderRadius: '4px'
                            }}>
                              Submitted Answer (Read-only)
                            </span>
                          </div>
                          <textarea
                            readOnly
                            rows={Math.min(7, Math.max(3, (card.studentText || '').split('\n').length + 1))}
                            className="input-field"
                            value={card.studentText || ''}
                            placeholder="No student response found for this question."
                            style={{
                              fontSize: '0.82rem',
                              padding: '0.55rem 0.65rem',
                              resize: 'vertical',
                              backgroundColor: 'var(--surface)',
                              color: 'var(--text-main)',
                              cursor: 'default',
                              lineHeight: '1.5',
                              border: '1px solid var(--border)',
                              opacity: card.studentText ? 1 : 0.7
                            }}
                          />
                        </div>

                        {/* Scoring Controls: Only - and + Stepper */}
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          flexWrap: 'wrap',
                          gap: '0.5rem',
                          padding: '0.55rem 0.75rem',
                          backgroundColor: 'var(--surface)',
                          borderRadius: '6px',
                          border: '1px solid var(--border)'
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
                            <span style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--secondary)' }}>
                              Examiner Score:
                            </span>

                            {/* Stepper Input: Minus, Number, Plus */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
                              <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => updateCalCard(qKey, { score: Math.max(0, Math.round(((currentScoreVal || 0) - 0.5) * 10) / 10) })}
                                style={{ width: '24px', height: '24px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <Minus size={12} />
                              </button>
                              <input
                                type="number"
                                step="0.5"
                                min="0"
                                max={maxSc}
                                value={currentScoreVal}
                                onChange={(e) => updateCalCard(qKey, { score: Math.max(0, Math.min(maxSc, parseFloat(e.target.value) || 0)) })}
                                style={{
                                  width: '48px',
                                  textAlign: 'center',
                                  fontSize: '0.85rem',
                                  fontWeight: 800,
                                  padding: '0.15rem 0.2rem',
                                  border: '1.5px solid var(--border)',
                                  borderRadius: '4px'
                                }}
                              />
                              <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => updateCalCard(qKey, { score: Math.min(maxSc, Math.round(((currentScoreVal || 0) + 0.5) * 10) / 10) })}
                                style={{ width: '24px', height: '24px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <Plus size={12} />
                              </button>
                            </div>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              / {maxSc} pts
                            </span>
                          </div>
                        </div>

                        {/* Feedback for this student respond (optional) */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                              Feedback for this student respond (optional):
                            </span>
                            <span style={{ fontSize: '0.72rem', color: 'var(--primary)', fontStyle: 'italic' }}>
                              Good to let AI know why you give this mark
                            </span>
                          </div>
                          <textarea
                            rows={2}
                            className="input-field"
                            value={card.feedback || ''}
                            onChange={(e) => updateCalCard(qKey, { feedback: e.target.value })}
                            placeholder="It is good to let AI to know why you give this mark..."
                            style={{ fontSize: '0.78rem', padding: '0.45rem', resize: 'vertical' }}
                          />
                        </div>

                        {/* Action Button: Save Exemplar */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '0.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                          <div>
                            {isExemplarSaved ? (
                              <span style={{
                                fontSize: '0.75rem',
                                color: '#059669',
                                fontWeight: 700,
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '5px',
                                backgroundColor: '#ECFDF5',
                                padding: '0.2rem 0.55rem',
                                borderRadius: '4px',
                                border: '1px solid #A7F3D0'
                              }}>
                                <Check size={13} /> Active in AI Calibration ({currentScoreVal}/{maxSc} pts)
                              </span>
                            ) : card.saveError ? (
                              <span style={{ fontSize: '0.75rem', color: '#dc2626', fontWeight: 600 }}>
                                ⚠️ {card.saveError}
                              </span>
                            ) : (
                              <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                                Ready to register with score {currentScoreVal}/{maxSc} pts
                              </span>
                            )}
                          </div>

                          <button
                            type="button"
                            className="btn"
                            onClick={() => handleSaveExemplar(qKey, q)}
                            disabled={card.saving}
                            style={{
                              fontSize: '0.78rem',
                              padding: '0.35rem 0.85rem',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.35rem',
                              backgroundColor: isExemplarSaved ? '#059669' : '#4f46e5',
                              borderColor: isExemplarSaved ? '#059669' : '#4f46e5',
                              color: '#ffffff',
                              fontWeight: 600,
                              borderRadius: '6px',
                              cursor: 'pointer'
                            }}
                            title="Click to update or re-save this question exemplar"
                          >
                            {card.saving ? (
                              <Loader2 size={13} className="spin" />
                            ) : isExemplarSaved ? (
                              <Check size={13} />
                            ) : (
                              <Target size={13} />
                            )}
                            {card.saving ? 'Saving...' : isExemplarSaved ? '✓ Exemplar Saved' : 'Save as Calibration Exemplar'}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Bottom Actions for Active Sample Paper */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.75rem',
                  marginTop: '1.25rem',
                  paddingTop: '1rem',
                  borderTop: '1px solid var(--border)'
                }}>
                  <div>
                    <strong style={{ fontSize: '0.9rem', color: 'var(--secondary)' }}>
                      Paper Score: {Math.round(calculatedStudioTotal * 10) / 10} / {totalMaxScore} pts
                    </strong>
                    <p style={{ margin: '0.1rem 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Confirm all marks for this paper or proceed to the next calibration benchmark.
                    </p>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn"
                      onClick={handleSaveAllCalibrationMarks}
                      disabled={savingAllCal}
                      style={{
                        fontSize: '0.825rem',
                        padding: '0.45rem 1.15rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.45rem',
                        backgroundColor: isPaperFullySaved ? '#059669' : '#4f46e5',
                        borderColor: isPaperFullySaved ? '#059669' : '#4f46e5',
                        color: '#ffffff',
                        fontWeight: 600,
                        borderRadius: '6px',
                        cursor: 'pointer'
                      }}
                    >
                      {savingAllCal ? (
                        <>
                          <Loader2 size={14} className="spin" />
                          <span>Saving All Marks & Registering Exemplars...</span>
                        </>
                      ) : isPaperFullySaved ? (
                        <>
                          <CheckCircle2 size={14} />
                          <span>✓ All Marks & Exemplars Saved ({Math.round(calculatedStudioTotal * 10) / 10}/{totalMaxScore} pts)</span>
                        </>
                      ) : (
                        <>
                          <Save size={14} />
                          <span>Save All Marks & Register Exemplars</span>
                        </>
                      )}
                    </button>

                    {nextCalSample && (
                      <button
                        type="button"
                        className="btn btn-outline"
                        onClick={() => {
                          setSelectedSampleId(nextCalSample.id);
                          setTimeout(() => {
                            document.getElementById('calibration-marking-studio')?.scrollIntoView({ behavior: 'smooth' });
                          }, 100);
                        }}
                        style={{ fontSize: '0.825rem', padding: '0.45rem 0.9rem', display: 'flex', alignItems: 'center', gap: '0.35rem', fontWeight: 600 }}
                      >
                        Next Paper <ChevronRight size={14} />
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            </div>
          )}
        </>
      )}

      {/* ── METHOD 2: UPLOAD CALIBRATED EXCEL / CSV WITH SMART HEADER DETECTION ── */}
      {!loading && calMethod === 'upload' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 800, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <FileSpreadsheet size={18} color="#4f46e5" />
                Upload Calibrated Spreadsheet
              </h3>
              <p style={{ margin: '0.3rem 0 0', fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Our header-sensitive scanner automatically matches your columns (e.g. <code>question</code>, <code>answer / response</code>, <code>score / marks</code>). <strong>Feedback is completely optional.</strong>
              </p>
            </div>

            <button
              type="button"
              onClick={() => downloadCalibrationTemplate(currentAssignmentId)}
              style={{
                background: 'none', border: 'none', color: 'var(--primary)',
                fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline'
              }}
            >
              Download sample template (optional)
            </button>
          </div>

          {/* Upload Dropzone */}
          <div style={{
            border: '2px dashed #cbd5e1',
            borderRadius: '10px',
            padding: '1.75rem',
            textAlign: 'center',
            backgroundColor: '#f8fafc',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.65rem'
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: '50%', backgroundColor: '#ede9fe',
              color: '#4f46e5', display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
              <Upload size={22} />
            </div>

            <div>
              <label style={{
                cursor: 'pointer',
                fontWeight: 700,
                fontSize: '0.875rem',
                color: '#4f46e5',
                textDecoration: 'underline'
              }}>
                Choose Excel or CSV file
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFileSelect(f);
                  }}
                />
              </label>
              <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)', marginLeft: 6 }}>
                or drag and drop here
              </span>
            </div>

            <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-dim)' }}>
              Supports .xlsx, .xls, and .csv · Header names are detected flexibly
            </p>
          </div>

          {/* Scanning / Loading Spinner */}
          {previewLoading && (
            <div style={{
              marginTop: '1rem', padding: '1rem', backgroundColor: '#f1f5f9',
              borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '0.65rem',
              color: 'var(--secondary)', fontSize: '0.85rem', fontWeight: 600
            }}>
              <Loader2 size={16} className="spin" color="#4f46e5" />
              Scanning spreadsheet headers and extracting preview examples…
            </div>
          )}

          {/* Preview Error */}
          {previewError && (
            <div style={{
              marginTop: '1rem', padding: '0.85rem 1rem', backgroundColor: '#fef2f2',
              border: '1px solid #fecaca', borderRadius: '8px', color: '#b91c1c',
              fontSize: '0.825rem', display: 'flex', alignItems: 'center', gap: '0.5rem'
            }}>
              <AlertTriangle size={16} style={{ flexShrink: 0 }} />
              <div>
                <strong>Could not read file:</strong> {previewError}
              </div>
            </div>
          )}

          {/* EXTRACTED EXAMPLES PREVIEW CARD */}
          {previewData && (
            <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Detected Headers Row */}
              <div style={{
                padding: '0.85rem 1rem', backgroundColor: '#f8fafc',
                border: '1px solid var(--border)', borderRadius: '8px'
              }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.45rem' }}>
                  Smart Column Detection:
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: '#e0e7ff', color: '#3730a3', fontWeight: 600 }}>
                    Question: <strong>{previewData.columns_detected.question_number}</strong>
                  </span>
                  <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: '#e0e7ff', color: '#3730a3', fontWeight: 600 }}>
                    Answer: <strong>{previewData.columns_detected.student_response}</strong>
                  </span>
                  <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: '#e0e7ff', color: '#3730a3', fontWeight: 600 }}>
                    Score: <strong>{previewData.columns_detected.examiner_score}</strong>
                  </span>
                  <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: '#f3f4f6', color: '#475569', fontWeight: 600 }}>
                    Feedback: <strong>{previewData.has_feedback ? previewData.columns_detected.examiner_feedback : 'Optional (None detected)'}</strong>
                  </span>
                  <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', borderRadius: '4px', backgroundColor: '#f3f4f6', color: '#475569', fontWeight: 600 }}>
                    Student ID: <strong>{previewData.columns_detected.student_id}</strong>
                  </span>
                </div>
              </div>

              {/* Extracted / Imported Examples Table */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 800, color: 'var(--secondary)' }}>
                      {previewData.isImported ? 'Imported Calibration Examples' : 'Extracted Examples Preview'} ({previewData.preview_examples.length} samples shown)
                    </h4>
                    {previewData.isImported && (
                      <span style={{
                        fontSize: '0.72rem', fontWeight: 700, padding: '0.15rem 0.55rem',
                        borderRadius: '20px', backgroundColor: '#dcfce7', color: '#15803d',
                        display: 'inline-flex', alignItems: 'center', gap: '0.25rem'
                      }}>
                        <CheckCircle size={12} /> Active in System
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                    Total: {previewData.total_rows} rows found across {previewData.distinct_questions.length} questions
                  </span>
                </div>

                <div style={{
                  border: '1px solid var(--border)',
                  borderRadius: '8px',
                  overflow: 'hidden',
                  backgroundColor: '#fff'
                }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid var(--border)' }}>
                        <th style={{ padding: '0.6rem 0.75rem', width: 40 }}>#</th>
                        <th style={{ padding: '0.6rem 0.75rem', width: 70 }}>Question</th>
                        <th style={{ padding: '0.6rem 0.75rem', width: 110 }}>Student</th>
                        <th style={{ padding: '0.6rem 0.75rem' }}>Student Answer (Preview)</th>
                        <th style={{ padding: '0.6rem 0.75rem', width: 85, textAlign: 'center' }}>Score</th>
                        <th style={{ padding: '0.6rem 0.75rem', width: 180 }}>Feedback (Optional)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewData.preview_examples.map((ex, idx) => (
                        <tr key={idx} style={{ borderBottom: idx < previewData.preview_examples.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                          <td style={{ padding: '0.55rem 0.75rem', color: 'var(--text-dim)', fontWeight: 700 }}>
                            {idx + 1}
                          </td>
                          <td style={{ padding: '0.55rem 0.75rem' }}>
                            <span style={{
                              fontWeight: 800, fontSize: '0.75rem', padding: '0.15rem 0.45rem',
                              borderRadius: '4px', backgroundColor: '#e0e7ff', color: '#3730a3'
                            }}>
                              {ex.question_number}
                            </span>
                          </td>
                          <td style={{ padding: '0.55rem 0.75rem', color: 'var(--secondary)', fontWeight: 600 }}>
                            {ex.student_id}
                          </td>
                          <td style={{ padding: '0.55rem 0.75rem', color: 'var(--text-main)', lineHeight: 1.45 }}>
                            {ex.student_text || <em style={{ color: 'var(--text-dim)' }}>(No text provided)</em>}
                          </td>
                          <td style={{ padding: '0.55rem 0.75rem', textAlign: 'center' }}>
                            <span style={{ fontWeight: 800, color: '#16a34a' }}>
                              {ex.examiner_score}
                            </span>
                            <span style={{ color: 'var(--text-dim)', fontSize: '0.72rem' }}>
                              /{ex.max_score}
                            </span>
                          </td>
                          <td style={{ padding: '0.55rem 0.75rem', color: ex.has_custom_feedback ? 'var(--text-main)' : 'var(--text-dim)', fontStyle: ex.has_custom_feedback ? 'normal' : 'italic' }}>
                            {ex.examiner_feedback}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '0.75rem' }}>
                {previewData.isImported ? (
                  <div style={{
                    width: '100%',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    backgroundColor: '#f0fdf4',
                    padding: '0.75rem 1rem',
                    borderRadius: '8px',
                    border: '1px solid #bbf7d0'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#15803d', fontWeight: 700, fontSize: '0.85rem' }}>
                      <CheckCircle2 size={18} color="#16a34a" />
                      <span>All {previewData.total_rows} examples successfully imported and active in AI calibration!</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                      <button
                        type="button"
                        className="btn btn-outline"
                        onClick={() => {
                          setImportFile(null);
                          setPreviewData(null);
                          setPreviewError(null);
                          setImportResult(null);
                        }}
                        style={{ fontSize: '0.8rem', padding: '0.45rem 0.9rem' }}
                      >
                        Upload Another Spreadsheet
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleGoToSubmissionsAndGrade}
                        disabled={startingGrading}
                        style={{
                          fontSize: '0.825rem',
                          padding: '0.45rem 1.25rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.45rem',
                          backgroundColor: '#16a34a',
                          borderColor: '#16a34a'
                        }}
                      >
                        {startingGrading ? (
                          <>
                            <Loader2 size={14} className="spin" /> Starting AI Grading…
                          </>
                        ) : (
                          <>
                            <Sparkles size={14} /> Start AI Grading Class <ArrowRight size={14} />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => {
                        setImportFile(null);
                        setPreviewData(null);
                        setPreviewError(null);
                      }}
                      disabled={importing}
                      style={{ fontSize: '0.8rem', padding: '0.45rem 0.9rem' }}
                    >
                      Choose Different File
                    </button>

                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleImport}
                      disabled={importing}
                      style={{
                        fontSize: '0.825rem',
                        padding: '0.45rem 1.25rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.45rem',
                        backgroundColor: '#4f46e5',
                        borderColor: '#4f46e5'
                      }}
                    >
                      {importing ? (
                        <>
                          <Loader2 size={14} className="spin" /> Importing…
                        </>
                      ) : (
                        <>
                          <Sparkles size={14} /> Confirm & Import {previewData.total_rows} Examples
                        </>
                      )}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}

          {/* ACTIVE SAVED EXEMPLARS IN DATABASE (Visible when not viewing an unimported file preview) */}
          {!previewData && activeSavedExemplars.length > 0 && (
            <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                  <h4 style={{ margin: 0, fontSize: '0.925rem', fontWeight: 800, color: 'var(--secondary)' }}>
                    Active Calibration Exemplars in System ({activeSavedExemplars.length} saved)
                  </h4>
                  <span style={{
                    fontSize: '0.725rem', fontWeight: 700, padding: '0.2rem 0.6rem',
                    borderRadius: '20px', backgroundColor: '#dcfce7', color: '#15803d',
                    display: 'inline-flex', alignItems: 'center', gap: '0.3rem'
                  }}>
                    <CheckCircle size={12} /> Active in AI Prompts
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleGoToSubmissionsAndGrade}
                  disabled={startingGrading}
                  style={{
                    fontSize: '0.8rem',
                    padding: '0.4rem 1rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    backgroundColor: '#16a34a',
                    borderColor: '#16a34a'
                  }}
                >
                  {startingGrading ? (
                    <><Loader2 size={13} className="spin" /> Starting AI Grading…</>
                  ) : (
                    <><Sparkles size={13} /> Start AI Grading Class <ArrowRight size={13} /></>
                  )}
                </button>
              </div>

              <div style={{
                border: '1px solid var(--border)',
                borderRadius: '8px',
                overflow: 'hidden',
                backgroundColor: '#fff'
              }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid var(--border)' }}>
                      <th style={{ padding: '0.6rem 0.75rem', width: 40 }}>#</th>
                      <th style={{ padding: '0.6rem 0.75rem', width: 75 }}>Question</th>
                      <th style={{ padding: '0.6rem 0.75rem' }}>Student Response / Answer</th>
                      <th style={{ padding: '0.6rem 0.75rem', width: 90, textAlign: 'center' }}>Score</th>
                      <th style={{ padding: '0.6rem 0.75rem', width: 220 }}>Feedback (Optional)</th>
                      <th style={{ padding: '0.6rem 0.75rem', width: 60, textAlign: 'center' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeSavedExemplars.map((ex, idx) => (
                      <tr key={ex.id || idx} style={{ borderBottom: idx < activeSavedExemplars.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                        <td style={{ padding: '0.55rem 0.75rem', color: 'var(--text-dim)', fontWeight: 700 }}>
                          {idx + 1}
                        </td>
                        <td style={{ padding: '0.55rem 0.75rem' }}>
                          <span style={{
                            fontWeight: 800, fontSize: '0.75rem', padding: '0.15rem 0.45rem',
                            borderRadius: '4px', backgroundColor: '#e0e7ff', color: '#3730a3'
                          }}>
                            {ex.question_number}
                          </span>
                        </td>
                        <td style={{ padding: '0.55rem 0.75rem', color: 'var(--text-main)', lineHeight: 1.45 }}>
                          {ex.student_text || <em style={{ color: 'var(--text-dim)' }}>(No text provided)</em>}
                        </td>
                        <td style={{ padding: '0.55rem 0.75rem', textAlign: 'center' }}>
                          <span style={{ fontWeight: 800, color: '#16a34a' }}>
                            {ex.examiner_score}
                          </span>
                          <span style={{ color: 'var(--text-dim)', fontSize: '0.72rem' }}>
                            /{ex.max_score}
                          </span>
                        </td>
                        <td style={{ padding: '0.55rem 0.75rem', color: ex.examiner_feedback ? 'var(--text-main)' : 'var(--text-dim)', fontStyle: ex.examiner_feedback ? 'normal' : 'italic' }}>
                          {ex.examiner_feedback || '(None provided)'}
                        </td>
                        <td style={{ padding: '0.55rem 0.75rem', textAlign: 'center' }}>
                          <button
                            type="button"
                            title="Remove this exemplar"
                            onClick={() => handleDeleteExample(ex.id)}
                            style={{
                              background: 'none', border: 'none', cursor: 'pointer',
                              color: '#ef4444', padding: '0.25rem', borderRadius: '4px'
                            }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Success Result Alert */}
          {importResult && (
            <div style={{
              marginTop: '1.25rem', padding: '0.85rem 1.15rem', backgroundColor: '#EAF7EE',
              border: '1px solid #A7E0B9', borderRadius: '8px', fontSize: '0.85rem',
              color: '#16A34A', display: 'flex', alignItems: 'center', gap: '0.55rem', fontWeight: 600
            }}>
              <CheckCircle size={18} />
              {importResult.message || `Import successful — ${importResult.imported || 0} calibration examples added.`}
            </div>
          )}
        </Card>
      )}


      {/* ── STEP 3: READY TO GRADE WHOLE CLASS ── */}
      <Card style={{ backgroundColor: calibrated > 0 ? 'var(--primary-light)' : 'var(--surface)', borderColor: 'var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              {calibrated > 0 ? (
                <>
                  <CheckCircle2 size={18} color="#16A34A" />
                  <span>🚀 AI Calibration Active ({calibrated} exemplar{calibrated !== 1 ? 's' : ''} saved)</span>
                </>
              ) : (
                <>
                  <Target size={18} color="var(--primary)" />
                  <span>🎯 Ready to grade</span>
                </>
              )}
            </div>
            <p style={{ margin: '0.25rem 0 0', fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {calibrated > 0
                ? `The AI will use your ${calibrated} calibration exemplar${calibrated !== 1 ? 's' : ''} to guide grading across all student submissions in your exact marking style.`
                : 'Complete your calibration benchmarks above to calibrate AI grading to your standards, or proceed directly to grading.'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigate('/submissions')}
              style={{ fontSize: '0.85rem', padding: '0.5rem 1rem' }}
            >
              View Submissions
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleGoToSubmissionsAndGrade}
              disabled={startingGrading}
              style={{ fontSize: '0.85rem', padding: '0.5rem 1.25rem', display: 'flex', alignItems: 'center', gap: '0.45rem' }}
            >
              {startingGrading ? (
                <>
                  <Loader2 size={15} className="spin" /> Starting AI Grading…
                </>
              ) : (
                <>
                  <Sparkles size={15} />
                  <span>{calibrated > 0 ? 'Go to Submissions & Grade with Calibration' : 'Grade Whole Class'}</span>
                </>
              )}
            </button>
          </div>
        </div>
      </Card>

      {/* Refresh */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          className="btn btn-outline"
          onClick={loadStatus}
          disabled={loading}
          style={{ fontSize: '0.775rem', padding: '0.3rem 0.7rem', display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-muted)' }}
        >
          <RefreshCw size={13} /> Refresh status
        </button>
      </div>
    </div>
  );
};

export default Calibration;
