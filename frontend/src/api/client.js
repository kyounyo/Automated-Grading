const API_BASE_URL = 'http://localhost:8000/api';

export async function fetchAssignments() {
  const response = await fetch(`${API_BASE_URL}/assignments`);
  if (!response.ok) throw new Error('Failed to fetch assignments');
  return await response.json();
}

export async function fetchAssignmentDetail(id) {
  const response = await fetch(`${API_BASE_URL}/assignments/${id}`);
  if (!response.ok) throw new Error('Failed to fetch assignment detail');
  return await response.json();
}

export async function createAssignment(payload) {
  const response = await fetch(`${API_BASE_URL}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error('Failed to create assignment');
  return await response.json();
}

export async function fetchSubmissions(assignmentId) {
  const response = await fetch(`${API_BASE_URL}/assignments/${assignmentId}/submissions`);
  if (!response.ok) throw new Error('Failed to fetch submissions');
  return await response.json();
}

export async function fetchSubmissionDetail(id) {
  const response = await fetch(`${API_BASE_URL}/submissions/${id}`);
  if (!response.ok) throw new Error('Failed to fetch submission details');
  return await response.json();
}

export async function gradeSubmission(submissionId) {
  const response = await fetch(`${API_BASE_URL}/submissions/${submissionId}/grade`, {
    method: 'POST'
  });
  if (!response.ok) throw new Error('Failed to grade submission');
  return await response.json();
}

export async function gradeAllSubmissions(assignmentId) {
  const response = await fetch(`${API_BASE_URL}/assignments/${assignmentId}/grade-all`, {
    method: 'POST'
  });
  if (!response.ok) throw new Error('Failed to start batch grading');
  return await response.json();
}

export async function overrideScore(submissionId, payload) {
  const response = await fetch(`${API_BASE_URL}/submissions/${submissionId}/override`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error('Failed to override score');
  return await response.json();
}

export async function uploadSubmissionFile(formData) {
  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: formData
  });
  if (!response.ok) throw new Error('Failed to upload submission file');
  return await response.json();
}

export async function parseRubricFile(formData) {
  const response = await fetch(`${API_BASE_URL}/assignments/parse-rubric-file`, {
    method: 'POST',
    body: formData
  });
  if (!response.ok) throw new Error('Failed to parse rubric file');
  return await response.json();
}

export async function fetchVectorStore(assignmentId) {
  const response = await fetch(`${API_BASE_URL}/assignments/${assignmentId}/vector-store`);
  if (!response.ok) throw new Error('Failed to fetch vector store');
  return await response.json();
}

export async function downloadGradesCSV(assignmentId) {
  const response = await fetch(`${API_BASE_URL}/assignments/${assignmentId}/export-csv`);
  if (!response.ok) throw new Error('Failed to download CSV grade export');
  const blob = await response.blob();
  const contentDisp = response.headers.get('content-disposition');
  let fileName = `Grades_Export.csv`;
  if (contentDisp && contentDisp.includes('filename=')) {
    const match = contentDisp.match(/filename=["']?([^"']+)["']?/);
    if (match && match[1]) fileName = match[1];
  }
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function getQCSettings() {
  const response = await fetch(`${API_BASE_URL}/assignments/qc-settings`);
  if (!response.ok) return { enable_random_qc: true, qc_audit_rate: 0.1 };
  return await response.json();
}

export async function updateQCSettings(settings) {
  const response = await fetch(`${API_BASE_URL}/assignments/qc-settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  });
  if (!response.ok) throw new Error('Failed to update QC settings');
  return await response.json();
}

export async function uploadBulkSubmissions(assignmentId, formData) {
  if (assignmentId && !formData.has('assignment_id')) {
    formData.append('assignment_id', assignmentId);
  }
  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: formData
  });
  if (!response.ok) {
    let errorDetail = 'Failed to upload submissions';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errorDetail;
    } catch (_) {}
    throw new Error(errorDetail);
  }
  return await response.json();
}

export async function triggerGradeAll(assignmentId) {
  return await gradeAllSubmissions(assignmentId);
}

export async function previewSubmissions(formData) {
  const response = await fetch(`${API_BASE_URL}/upload/preview-submissions`, {
    method: 'POST',
    body: formData
  });
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'Failed to preview submissions');
  }
  return await response.json();
}

