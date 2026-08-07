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
