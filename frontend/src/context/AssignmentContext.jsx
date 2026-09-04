import React, { createContext, useState, useEffect, useContext } from 'react';
import { fetchAssignments, fetchSubmissions, fetchSubmissionDetail, gradeSubmission as apiGradeSubmission, gradeAllSubmissions as apiGradeAllSubmissions, overrideScore as apiOverrideScore, downloadGradesCSV } from '../api/client';

export const AssignmentContext = createContext();

export const AssignmentProvider = ({ children }) => {
  const [assignments, setAssignments] = useState([]);
  const [currentAssignmentId, setCurrentAssignmentId] = useState('assign-101');
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Load assignments from FastAPI backend on mount
  const loadAssignments = async () => {
    try {
      setLoading(true);
      const data = await fetchAssignments();
      setAssignments(data);
      if (data.length > 0 && (!currentAssignmentId || !data.some(a => a.id === currentAssignmentId))) {
        setCurrentAssignmentId(data[0].id);
      }
    } catch (err) {
      console.warn('[AssignmentContext] Failed to fetch from backend API. Using local state fallback:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load submissions whenever currentAssignmentId changes
  const loadSubmissions = async (assignId) => {
    const idToUse = assignId || currentAssignmentId;
    if (!idToUse) return;
    try {
      setLoading(true);
      const data = await fetchSubmissions(idToUse);
      setSubmissions(data);
    } catch (err) {
      console.warn(`[AssignmentContext] Failed to load submissions for ${idToUse}:`, err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAssignments();
  }, []);

  useEffect(() => {
    if (currentAssignmentId) {
      loadSubmissions(currentAssignmentId);
    }
  }, [currentAssignmentId]);

  const triggerGradeSubmission = async (submissionId) => {
    try {
      setLoading(true);
      // Optimistically update status to 'processing' so any connected view immediately reflects the loading state
      setSubmissions(prev => prev.map(s => s.id === submissionId ? { ...s, status: 'processing' } : s));
      const updated = await apiGradeSubmission(submissionId);
      setSubmissions(prev => prev.map(s => s.id === submissionId ? updated : s));
      await loadAssignments(); // Refresh assignment average score
      return updated;
    } catch (err) {
      console.error(`[AssignmentContext] Error grading submission ${submissionId}:`, err);
      if (currentAssignmentId) {
        loadSubmissions(currentAssignmentId);
      }
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const triggerGradeAll = async (assignmentId) => {
    try {
      setLoading(true);
      const targetId = assignmentId || currentAssignmentId;
      // Optimistically mark pending submissions as 'processing'
      setSubmissions(prev => prev.map(s => (s.status === 'pending' || s.status === 'uploaded') ? { ...s, status: 'processing' } : s));
      const res = await apiGradeAllSubmissions(targetId);
      // Refresh submissions list after triggering background task
      setTimeout(() => loadSubmissions(targetId), 1500);
      return res;
    } catch (err) {
      console.error(`[AssignmentContext] Error initiating batch grading:`, err);
      const targetId = assignmentId || currentAssignmentId;
      if (targetId) {
        loadSubmissions(targetId);
      }
      throw err;
    } finally {
      setLoading(false);
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
      error,
      loadAssignments,
      loadSubmissions,
      triggerGradeSubmission,
      triggerGradeAll,
      handleScoreOverride,
      handleExportCSV
    }}>
      {children}
    </AssignmentContext.Provider>
  );
};

export const useAssignment = () => useContext(AssignmentContext);
