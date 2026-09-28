import React, { createContext, useState, useEffect, useContext, useCallback } from 'react';
import { fetchAssignments, fetchSubmissions, fetchGradingStatus, fetchSubmissionDetail, gradeSubmission as apiGradeSubmission, gradeAllSubmissions as apiGradeAllSubmissions, overrideScore as apiOverrideScore, downloadGradesCSV, updateAssignment as apiUpdateAssignment } from '../api/client';

export const ACTIVE_GRADING_STATUSES = new Set(['processing', 'extracting_answers', 'retrieving_rubric', 'grading']);

export const AssignmentContext = createContext();

export const AssignmentProvider = ({ children }) => {
  const [assignments, setAssignments] = useState([]);
  const [currentAssignmentId, setCurrentAssignmentId] = useState('');
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isGradingActive, setIsGradingActive] = useState(false);
  const [activeGradingAssignments, setActiveGradingAssignments] = useState(new Set());
  const [isAssignmentCreationPending, setIsAssignmentCreationPending] = useState(false);
  const [error, setError] = useState(null);

  // Load assignments from FastAPI backend on mount
  const loadAssignments = useCallback(async () => {
    try {
      const data = await fetchAssignments();
      setAssignments(data);
      if (data && data.length > 0) {
        setCurrentAssignmentId(prev => (prev && data.some(a => a.id === prev)) ? prev : data[0].id);
      }
    } catch (err) {
      console.warn('[AssignmentContext] Failed to fetch from backend API:', err);
    }
  }, []);

  // Load submissions whenever currentAssignmentId changes with backend sync
  const loadSubmissions = useCallback(async (assignId, isSilent = true) => {
    const idToUse = assignId || currentAssignmentId;
    if (!idToUse) return;
    try {
      if (!isSilent) setLoading(true);
      const [subsData, statusData] = await Promise.all([
        fetchSubmissions(idToUse),
        fetchGradingStatus(idToUse).catch(() => ({ is_grading: false }))
      ]);
      setSubmissions(subsData);
      const isActuallyGrading = statusData.is_grading || subsData.some(s => ACTIVE_GRADING_STATUSES.has(s.status));
      if (isActuallyGrading) {
        setActiveGradingAssignments(prev => new Set(prev).add(idToUse));
        setIsGradingActive(true);
      } else {
        setActiveGradingAssignments(prev => {
          if (!prev.has(idToUse)) return prev;
          const next = new Set(prev);
          next.delete(idToUse);
          return next;
        });
        setIsGradingActive(false);
      }
    } catch (err) {
      console.warn(`[AssignmentContext] Failed to load submissions for ${idToUse}:`, err);
    } finally {
      if (!isSilent) setLoading(false);
    }
  }, [currentAssignmentId]);

  useEffect(() => {
    loadAssignments();
  }, [loadAssignments]);

  useEffect(() => {
    if (currentAssignmentId) {
      loadSubmissions(currentAssignmentId, false);
    }
  }, [currentAssignmentId, loadSubmissions]);

  // Global background polling: continues polling backend until grading is 100% complete
  useEffect(() => {
    if (!currentAssignmentId) return;

    let isMounted = true;

    const poll = async () => {
      try {
        const [subsData, statusData] = await Promise.all([
          fetchSubmissions(currentAssignmentId),
          fetchGradingStatus(currentAssignmentId).catch(() => ({ is_grading: false }))
        ]);
        if (!isMounted) return;
        setSubmissions(subsData);

        const isStillGrading = Boolean(statusData.is_grading || subsData.some(s => ACTIVE_GRADING_STATUSES.has(s.status)));

        if (isStillGrading) {
          setIsGradingActive(true);
          setActiveGradingAssignments(prev => new Set(prev).add(currentAssignmentId));
        } else {
          setIsGradingActive(false);
          setActiveGradingAssignments(prev => {
            if (!prev.has(currentAssignmentId)) return prev;
            const next = new Set(prev);
            next.delete(currentAssignmentId);
            return next;
          });
          await loadAssignments();
        }
      } catch (err) {
        console.warn('[AssignmentContext] Polling error:', err);
      }
    };

    const hasActiveSubs = submissions.some(s => ACTIVE_GRADING_STATUSES.has(s.status));
    const shouldPoll = activeGradingAssignments.has(currentAssignmentId) || isGradingActive || hasActiveSubs;

    if (!shouldPoll) return;

    const interval = setInterval(poll, 3000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [currentAssignmentId, activeGradingAssignments, isGradingActive, loadAssignments]);

  const triggerGradeSubmission = async (submissionId) => {
    try {
      setLoading(true);
      setIsGradingActive(true);
      setSubmissions(prev => prev.map(s => s.id === submissionId ? { ...s, status: 'processing' } : s));
      const updated = await apiGradeSubmission(submissionId);
      setSubmissions(prev => prev.map(s => s.id === submissionId ? updated : s));
      await loadAssignments();
      return updated;
    } catch (err) {
      console.error(`[AssignmentContext] Error grading submission ${submissionId}:`, err);
      if (currentAssignmentId) {
        loadSubmissions(currentAssignmentId, true);
      }
      throw err;
    } finally {
      setIsGradingActive(false);
      setLoading(false);
    }
  };

  const triggerGradeAll = async (assignmentId) => {
    const targetId = (typeof assignmentId === 'string' && assignmentId.trim()) ? assignmentId : currentAssignmentId;
    if (!targetId) return;
    try {
      setActiveGradingAssignments(prev => new Set(prev).add(targetId));
      setIsGradingActive(true);
      const res = await apiGradeAllSubmissions(targetId);
      // Immediately pull fresh backend state
      await loadSubmissions(targetId, true);
      return res;
    } catch (err) {
      console.error(`[AssignmentContext] Error initiating batch grading:`, err);
      setActiveGradingAssignments(prev => {
        const next = new Set(prev);
        next.delete(targetId);
        return next;
      });
      setIsGradingActive(false);
      if (targetId) {
        loadSubmissions(targetId, true);
      }
      throw err;
    }
  };

  const handleScoreOverride = async (submissionId, newScore, comment, updatedBreakdown) => {
    try {
      setLoading(true);
      const payload = { new_score: newScore, comment };
      if (updatedBreakdown) {
        payload.updated_breakdown = updatedBreakdown;
      }
      const updated = await apiOverrideScore(submissionId, payload);
      setSubmissions(prev => prev.map(s => s.id === submissionId ? updated : s));
      setActiveSubmission(updated);
      await loadAssignments();
      return updated;
    } catch (err) {
      console.error(`[AssignmentContext] Error overriding score:`, err);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const handleExportCSV = async (assignmentId) => {
    const idToUse = assignmentId || currentAssignmentId;
    if (!idToUse) {
      alert("No active assignment selected to export.");
      return;
    }
    try {
      setLoading(true);
      await downloadGradesCSV(idToUse);
    } catch (err) {
      console.error(`[AssignmentContext] Error exporting CSV:`, err);
      alert(`Export failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateAssignment = async (assignmentId, payload) => {
    const idToUse = assignmentId || currentAssignmentId;
    if (!idToUse) throw new Error("No assignment selected to update");
    try {
      setLoading(true);
      const updated = await apiUpdateAssignment(idToUse, payload);
      await loadAssignments();
      return updated;
    } catch (err) {
      console.error(`[AssignmentContext] Error updating assignment ${idToUse}:`, err);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const [activeSubmission, setActiveSubmission] = useState(null);

  const currentAssignment = assignments.find(a => a.id === currentAssignmentId) || assignments[0] || null;

  return (
    <AssignmentContext.Provider value={{
      assignments,
      currentAssignmentId,
      setCurrentAssignmentId,
      currentAssignment,
      submissions,
      activeSubmission,
      setActiveSubmission,
      loading,
      isGradingActive,
      activeGradingAssignments,
      isAssignmentCreationPending,
      setIsAssignmentCreationPending,
      error,
      loadAssignments,
      loadSubmissions,
      handleUpdateAssignment,
      triggerGradeSubmission,
      triggerGradeAll,
      gradeAll: triggerGradeAll,
      handleScoreOverride,
      handleExportCSV
    }}>
      {children}
    </AssignmentContext.Provider>
  );
};

export const useAssignment = () => useContext(AssignmentContext);
