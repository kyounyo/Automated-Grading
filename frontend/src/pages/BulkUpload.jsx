import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, CheckCircle2, FileText, Trash2, ArrowRight, Loader2, Plus, Download, Users, UserCheck, ChevronDown, ChevronUp, FileSpreadsheet, Sparkles, Sliders, Info, AlertTriangle } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { uploadBulkSubmissions, triggerGradeAll, previewSubmissions } from '../api/client';

const TOLERANCE_STEPS = [
  { val: 0.0, label: 'Strict (0%)', desc: 'Flags any paper if the two AI evaluators have any score difference at all.' },
  { val: 0.05, label: 'High Precision (5%)', desc: 'Flags papers if the two AI scores differ by more than 5% of total marks.' },
  { val: 0.10, label: 'Balanced (10%)', desc: 'Recommended default. Small differences (≤10%) pass automatically; larger discrepancies require your review.' },
  { val: 0.20, label: 'Relaxed (20%)', desc: 'Grants AI more latitude. Only large score discrepancies (>20%) will be flagged for review.' }
];

const BulkUpload = () => {
  const navigate = useNavigate();
  const { assignments, currentAssignmentId, setCurrentAssignmentId, currentAssignment, loadSubmissions, loadAssignments, submissions, handleUpdateAssignment } = useAssignment();

  const [toleranceVal, setToleranceVal] = useState(0.10);
  const [savingTolerance, setSavingTolerance] = useState(false);

  useEffect(() => {
    if (currentAssignment?.tolerance_rate != null) {
      setToleranceVal(currentAssignment.tolerance_rate);
    }
  }, [currentAssignment?.tolerance_rate]);

  const handleToleranceChange = async (newVal) => {
    setToleranceVal(newVal);
    if (!currentAssignmentId) return;
    try {
      setSavingTolerance(true);
      await handleUpdateAssignment(currentAssignmentId, { tolerance_rate: newVal });
    } catch (e) {
      console.warn('Failed to update tolerance rate:', e);
    } finally {
      setSavingTolerance(false);
    }
  };

  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  };

  const handleFileInput = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
    }
  };

  const [extractedStudents, setExtractedStudents] = useState([]);
  const [showAllStudents, setShowAllStudents] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);

  const addFiles = async (files) => {
    const rawList = Array.from(files);
    const newFiles = rawList.map((file, idx) => ({
      id: Date.now() + idx,
      file,
      name: file.name,
      size: (file.size / (1024 * 1024)).toFixed(2) + ' MB',
      status: 'Ready'
    }));

    setSelectedFiles(prev => [...prev, ...newFiles]);

    // Automatically trigger instant extraction for preview
    try {
      setIsExtracting(true);
      const combined = [...selectedFiles.map(f => f.file).filter(Boolean), ...rawList];
      const formData = new FormData();
      combined.forEach(f => formData.append('files', f));
      const res = await previewSubmissions(formData);
      if (res && res.students) {
        setExtractedStudents(res.students);
      }
    } catch (err) {
      console.warn('Could not extract preview:', err);
    } finally {
      setIsExtracting(false);
    }
  };

  const handleRemoveFile = (id) => {
    setSelectedFiles(prev => {
      const remaining = prev.filter(f => f.id !== id);
      if (remaining.length === 0) {
        setExtractedStudents([]);
      }
      return remaining;
    });
  };

  const downloadSubmissionsTemplate = () => {
    const csvContent = "data:text/csv;charset=utf-8,"
      + "student_id,student_name,question_number,response_text\n"
      + "STU_001,John Doe,6,\"(a) Polymer microspheres offer biodegradable sustained release. Disadvantages: limited to non-acid labile APIs. (b) In situ gelling contains solvents that precipitate in vivo.\"\n"
      + "STU_001,John Doe,8,\"(a) Disagree: Lyophilization reduces moisture. (b) Agree: Hydrogen bonds maintain secondary structure. (c) Disagree. (d) Disagree. (e) Agree.\"\n"
      + "STU_002,Jane Smith,6,\"(a) Microspheres provide extended systemic exposure. (b) In situ gelling polymers transition from liquid to gel depot.\"\n"
      + "STU_002,Jane Smith,8,\"(a) Disagree: Lyophilization removes water. (b) Agree: Secondary structure is stabilized by H-bonds. (c) Disagree. (d) Disagree. (e) Agree.\"\n";

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "AutoGrade_Submissions_Template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const uploadStagedFilesToBackend = async () => {
    if (selectedFiles.length === 0) return false;
    const filesToUpload = selectedFiles.filter(f => f.status !== 'Uploaded' && f.file).map(f => f.file);
    if (filesToUpload.length === 0) return true;

    try {
      setIsProcessing(true);
      setUploadStatus(`Uploading ${filesToUpload.length} student submission file(s)...`);

      const formData = new FormData();
      filesToUpload.forEach(file => {
        formData.append('files', file);
      });

      const res = await uploadBulkSubmissions(currentAssignmentId, formData);

      setSelectedFiles(prev =>
        prev.map(f => ({
          ...f,
          status: 'Uploaded'
        }))
      );

      // Refresh global context so Dashboard and Submissions reflect the new upload immediately
      await loadSubmissions(currentAssignmentId);
      await loadAssignments();

      setUploadStatus(`✅ Successfully uploaded ${res.uploaded_count || filesToUpload.length} submission(s)!`);
      return true;
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
      setUploadStatus('Upload failed.');
      return false;
    } finally {
      setIsProcessing(false);
    }
  };

  const handleConfirmUploadOnly = async () => {
    if (!currentAssignmentId) {
      alert('Please select a target assignment first.');
      return;
    }
    const success = await uploadStagedFilesToBackend();
    if (success) {
      alert('Files uploaded and registered in the database! You can proceed to Calibration or Submissions List.');
    }
  };

  const handleProceedToCalibration = async () => {
    if (!currentAssignmentId) {
      alert('Please select a target assignment first.');
      return;
    }

    try {
      setIsProcessing(true);
      const hasUnuploaded = selectedFiles.some(f => f.status !== 'Uploaded' && f.file);
      if (hasUnuploaded) {
        const success = await uploadStagedFilesToBackend();
        if (!success) return;
      }
      navigate('/calibration');
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleProceedToSubmissions = async () => {
    if (!currentAssignmentId) {
      alert('Please select a target assignment first.');
      return;
    }

    try {
      setIsProcessing(true);
      const hasUnuploaded = selectedFiles.some(f => f.status !== 'Uploaded' && f.file);
      if (hasUnuploaded) {
        const success = await uploadStagedFilesToBackend();
        if (!success) return;
      }
      navigate('/submissions');
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const selectedAssignment = assignments.find(a => String(a.id) === String(currentAssignmentId));
  const rubricQuestions = selectedAssignment?.rubric_data || [];
  const totalMaxMarks = rubricQuestions.length > 0
    ? rubricQuestions.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0)
    : 20;

  const unuploadedCount = selectedFiles.filter(f => f.status !== 'Uploaded').length;
  const uploadedCount = selectedFiles.filter(f => f.status === 'Uploaded').length;

  return (
    <div style={{ maxWidth: '1240px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* 1. Header (Unboxed, Minimalist, No Icon) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.5rem', fontWeight: 800 }}>
            Submissions Upload
          </h2>
          <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.825rem' }}>
            Upload student submissions (Excel .xlsx, .csv or PDF files). Once uploaded, proceed to calibration or directly to the submissions list.
          </p>
        </div>
      </div>


      {/* 2. SIDE-BY-SIDE SECTION: Step 1 (Target Assignment) + Step 2 (Upload Student Submissions) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.35fr', gap: '1.25rem', alignItems: 'stretch' }}>

        {/* Column 1: Step 1 Target Assignment */}
        <div className="card-panel" style={{ padding: '1.35rem 1.6rem', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', minHeight: '235px' }}>
          <h3 style={{ marginBottom: '1.15rem', color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <FileText size={18} color="var(--primary)" /> 1. Target Assignment <span style={{ color: 'var(--danger)', fontSize: '0.775rem', fontWeight: 600 }}>*Required</span>
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label className="label" style={{ fontSize: '0.825rem', marginBottom: '0.35rem' }}>Select Assignment *</label>
              <select
                className="input-field"
                style={{ padding: '0.55rem 0.85rem', fontSize: '0.875rem', fontWeight: 600, color: 'var(--primary-dark)', backgroundColor: '#fff', border: '1px solid var(--border)' }}
                value={currentAssignmentId}
                onChange={(e) => setCurrentAssignmentId(e.target.value)}
              >
                {assignments.length > 0 ? (
                  assignments.map(a => (
                    <option key={a.id} value={a.id}>{a.course_code ? `[${a.course_code}] ` : ''}{a.title}</option>
                  ))
                ) : (
                  <option value="">No Assignments Created Yet</option>
                )}
              </select>
            </div>

            <div style={{ padding: '0.65rem 0.85rem', backgroundColor: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Total Assignments: <strong style={{ color: 'var(--primary)' }}>{assignments.length}</strong> loaded. Submissions will be associated with this assignment.
            </div>
          </div>
        </div>

        {/* Column 2: Step 2 Upload Submissions (Tabbed: Ungraded vs Pre-Graded) */}
        <div className="card-panel" style={{ padding: '1.35rem 1.6rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '235px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <UploadCloud size={18} color="var(--primary)" /> 2. Upload Submissions <span style={{ color: 'var(--danger)', fontSize: '0.775rem', fontWeight: 600 }}>*Required</span>
              </h3>

              <button
                type="button"
                className="btn btn-outline"
                onClick={downloadSubmissionsTemplate}
                style={{ fontSize: '0.75rem', padding: '0.25rem 0.65rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
              >
                <Download size={13} color="var(--primary)" /> Template (.csv)
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>

              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => document.getElementById('bulkFileInput').click()}
                style={{
                  border: `2px dashed ${isDragging ? 'var(--primary)' : 'var(--border)'}`,
                  borderRadius: '8px',
                  padding: '1.35rem 1.15rem',
                  textAlign: 'center',
                  backgroundColor: isDragging ? 'var(--primary-light)' : 'var(--bg-main)',
                  cursor: 'pointer',
                  flex: 1,
                  minHeight: '140px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all var(--transition-fast)'
                }}
              >
                <input
                  id="bulkFileInput"
                  type="file"
                  multiple
                  accept=".xlsx,.xls,.csv,.pdf"
                  onClick={(e) => e.stopPropagation()}
                  onChange={handleFileInput}
                  style={{ display: 'none' }}
                />

                {isProcessing || isExtracting ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', color: 'var(--primary)' }}>
                    <Loader2 size={24} className="spin" />
                    <div style={{ textAlign: 'left' }}>
                      <h4 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--primary-dark)' }}>Extracting {selectedFiles.length} File(s)...</h4>
                      <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-muted)' }}>Parsing student submission datasets</p>
                    </div>
                  </div>
                ) : selectedFiles.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--success)' }}>
                      <CheckCircle2 size={20} />
                      <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-main)' }}>
                        {selectedFiles.length} File(s) Attached
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                      {selectedFiles.map((f, i) => (
                        <span
                          key={f.id || i}
                          className="status-badge"
                          style={{
                            backgroundColor: 'var(--success-bg)',
                            color: 'var(--success)',
                            fontSize: '0.75rem',
                            padding: '0.2rem 0.5rem',
                            border: '1px solid var(--success-border)'
                          }}
                        >
                          📄 {f.name} ({f.size})
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveFile(f.id);
                            }}
                            title="Remove file"
                            style={{ cursor: 'pointer', fontWeight: 700, marginLeft: '0.35rem', color: 'var(--danger)' }}
                          >
                            ✕
                          </span>
                        </span>
                      ))}
                    </div>

                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        document.getElementById('bulkFileInput').click();
                      }}
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.6rem', marginTop: '0.2rem' }}
                    >
                      <Plus size={13} color="var(--primary)" /> Add More
                    </button>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.35rem' }}>
                    <UploadCloud size={28} color="var(--primary)" style={{ marginBottom: '0.15rem', opacity: 0.8 }} />
                    <h4 style={{ margin: '0 0 0.15rem 0', fontSize: '0.875rem', color: 'var(--secondary)', fontWeight: 700 }}>
                      Drag & drop Student Submission files here
                    </h4>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0 }}>
                      Supports <strong>.xlsx, .csv, .pdf</strong> or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Browse files</span>
                    </p>
                  </div>
                )}
              </div>

              {uploadStatus && (
                <div style={{ marginTop: '0.65rem', color: 'var(--primary)', fontWeight: 600, fontSize: '0.8rem', textAlign: 'center' }}>
                  {uploadStatus}
                </div>
              )}
            </div>
          </div>
        </div>

      </div>


      {/* Staged Submissions List */}
      {selectedFiles.length > 0 && (
        <div className="card-panel" style={{ padding: '1.35rem 1.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <CheckCircle2 size={18} color="var(--success)" /> Staged Submissions ({selectedFiles.length})
              </h3>
              <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>
                {uploadedCount > 0 && `${uploadedCount} uploaded to database, `}{unuploadedCount} ready to confirm
              </span>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => document.getElementById('bulkFileInput').click()}
                style={{ fontSize: '0.775rem', padding: '0.3rem 0.65rem' }}
              >
                <Plus size={14} color="var(--primary)" /> Add More Files
              </button>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setSelectedFiles([])}
                style={{ fontSize: '0.775rem', padding: '0.3rem 0.65rem', color: 'var(--danger)' }}
              >
                Clear All
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.65rem' }}>
            {selectedFiles.map(file => (
              <div
                key={file.id}
                className="card-secondary"
                style={{ padding: '0.6rem 0.85rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                  <FileText size={16} color="var(--primary)" style={{ flexShrink: 0 }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {file.name}
                    </div>
                    <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>{file.size}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                  <span
                    className="status-badge"
                    style={{
                      backgroundColor: file.status === 'Uploaded' ? 'var(--success-bg)' : 'var(--primary-light)',
                      color: file.status === 'Uploaded' ? 'var(--success)' : 'var(--primary-dark)',
                      fontSize: '0.725rem',
                      padding: '0.15rem 0.45rem',
                      fontWeight: 600
                    }}
                  >
                    {file.status}
                  </span>
                  <button onClick={() => handleRemoveFile(file.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', padding: '0.2rem' }} title="Remove file">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Extracted Student Submissions Preview (First 3 students with expand option) */}
      {extractedStudents.length > 0 && (
        <div className="card-panel" style={{ padding: '1.35rem 1.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <UserCheck size={18} color="var(--primary)" /> Extracted Student Submissions ({extractedStudents.length})
              </h3>
              <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>
                Showing {showAllStudents ? `all ${extractedStudents.length}` : `first ${Math.min(3, extractedStudents.length)}`} extracted student response{extractedStudents.length === 1 ? '' : 's'}
              </span>
            </div>

            {extractedStudents.length > 3 && (
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setShowAllStudents(!showAllStudents)}
                style={{ fontSize: '0.775rem', padding: '0.35rem 0.75rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
              >
                {showAllStudents ? (
                  <><ChevronUp size={14} /> Show First 3 Only</>
                ) : (
                  <><ChevronDown size={14} /> View All {extractedStudents.length} Students</>
                )}
              </button>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            {(showAllStudents ? extractedStudents : extractedStudents.slice(0, 3)).map((student, idx) => (
              <div
                key={idx}
                className="card-secondary"
                style={{
                  padding: '0.9rem 1.15rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.5rem',
                  border: '1px solid var(--border)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{
                      backgroundColor: 'var(--primary-light)',
                      color: 'var(--primary-dark)',
                      fontWeight: 700,
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.55rem',
                      borderRadius: '4px',
                      border: '1px solid #BDDAEE'
                    }}>
                      ID: {student.student_id}
                    </span>
                    <strong style={{ fontSize: '0.9rem', color: 'var(--secondary)' }}>
                      {(() => {
                        const name = student.student_name;
                        const id = student.student_id;
                        const email = student.student_email;
                        if (name && !name.includes('@') && name !== 'N/A' && !name.startsWith('Student STU')) return name;
                        const candidate = (name && name.includes('@')) ? name : (email && email.includes('@') ? email : null);
                        if (candidate) {
                          const prefix = candidate.split('@')[0];
                          const cleaned = prefix.split(/[._\s\-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
                          if (cleaned) return cleaned;
                        }
                        return name && name !== 'N/A' ? name : `Student ${id || ''}`.trim();
                      })()}
                    </strong>
                    {student.student_email && student.student_email !== 'N/A' && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        ({student.student_email})
                      </span>
                    )}
                  </div>

                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', backgroundColor: '#fff', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}>
                    📄 {student.file_name}
                  </span>
                </div>

                <div
                  style={{
                    fontSize: '0.825rem',
                    color: 'var(--text-main)',
                    lineHeight: '1.5',
                    backgroundColor: 'var(--surface)',
                    padding: '0.65rem 0.85rem',
                    borderRadius: '6px',
                    border: '1px solid var(--border)',
                    maxHeight: '120px',
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-body)'
                  }}
                >
                  {student.text || '<Empty student response>'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Acceptable Mark Difference (Tolerance Setting) */}
      <div className="card-panel" style={{ padding: '1.25rem 1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '0.95rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Sliders size={16} color="var(--primary)" /> AI Discrepancy Tolerance
          </h3>
          <span style={{
            fontSize: '0.75rem',
            fontWeight: 700,
            color: 'var(--primary)',
            backgroundColor: 'var(--primary-light)',
            padding: '0.2rem 0.65rem',
            borderRadius: '999px',
            border: '1px solid var(--border)'
          }}>
            {toleranceVal === 0 ? 'Strict (0%)' : toleranceVal <= 0.05 ? 'High Precision (5%)' : toleranceVal <= 0.10 ? 'Balanced (10%)' : 'Relaxed (20%)'}
          </span>
        </div>

        <p style={{ margin: '0 0 0.85rem 0', fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
          The maximum score difference allowed between the two AI agents before a paper is flagged for your review.
        </p>

        <div style={{ maxWidth: '480px' }}>
          {(() => {
            const curIdx = TOLERANCE_STEPS.findIndex(s => Math.abs(s.val - toleranceVal) < 0.01);
            const activeStep = TOLERANCE_STEPS[curIdx >= 0 ? curIdx : 2];
            return (
              <>
                <input
                  type="range"
                  min={0}
                  max={3}
                  step={1}
                  value={curIdx >= 0 ? curIdx : 2}
                  onChange={(e) => handleToleranceChange(TOLERANCE_STEPS[parseInt(e.target.value)].val)}
                  disabled={savingTolerance || !currentAssignmentId}
                  style={{ width: '100%', accentColor: 'var(--primary)', cursor: 'pointer', height: '6px' }}
                />

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.4rem' }}>
                  {TOLERANCE_STEPS.map((step, idx) => (
                    <span
                      key={idx}
                      style={{
                        fontSize: '0.72rem',
                        fontWeight: Math.abs(step.val - toleranceVal) < 0.01 ? 700 : 500,
                        color: Math.abs(step.val - toleranceVal) < 0.01 ? 'var(--primary)' : 'var(--text-muted)',
                        textAlign: idx === 0 ? 'left' : idx === TOLERANCE_STEPS.length - 1 ? 'right' : 'center',
                        flex: 1
                      }}
                    >
                      {step.label}
                    </span>
                  ))}
                </div>

                <div style={{
                  marginTop: '0.65rem',
                  fontSize: '0.76rem',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem'
                }}>
                  <Info size={13} color="var(--primary)" style={{ flexShrink: 0 }} />
                  <span>
                    {toleranceVal === 0
                      ? 'Flag if AI graders differ at all (0% tolerance).'
                      : `Auto-approves differences within ±${(toleranceVal * 100).toFixed(0)}%; flags larger disagreements.`}
                  </span>
                  {savingTolerance && <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Saving…</span>}
                </div>
              </>
            );
          })()}
        </div>
      </div>

      {/* 5. Bottom Submission Bar */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginBottom: '1.5rem', alignItems: 'center' }}>
        <button
          type="button"
          className="btn btn-outline"
          onClick={handleConfirmUploadOnly}
          disabled={isProcessing || selectedFiles.length === 0}
          style={{ fontSize: '0.85rem' }}
        >
          {isProcessing ? 'Processing...' : 'Upload Files Only'}
        </button>

        {currentAssignment?.calibration_enabled ? (
          <>
            <button
              type="button"
              className="btn btn-outline"
              onClick={handleProceedToSubmissions}
              disabled={isProcessing || !currentAssignmentId}
              style={{ fontSize: '0.85rem' }}
            >
              Skip to Submissions List →
            </button>

            <button
              type="button"
              className="btn btn-primary"
              onClick={handleProceedToCalibration}
              disabled={isProcessing || !currentAssignmentId}
              style={{
                padding: '0.55rem 1.4rem',
                fontSize: '0.875rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
                backgroundColor: 'var(--primary)',
                boxShadow: '0 2px 6px rgba(59, 130, 196, 0.3)'
              }}
            >
              {isProcessing ? (
                <><Loader2 size={15} className="spin" /> Uploading...</>
              ) : (
                <>Next: Calibration (Step 3) <ArrowRight size={15} /></>
              )}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleProceedToSubmissions}
            disabled={isProcessing || !currentAssignmentId}
            style={{
              padding: '0.55rem 1.4rem',
              fontSize: '0.875rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.45rem',
              backgroundColor: 'var(--primary)',
              boxShadow: '0 2px 6px rgba(59, 130, 196, 0.3)'
            }}
          >
            {isProcessing ? (
              <><Loader2 size={15} className="spin" /> Uploading...</>
            ) : (
              <>Next: Submissions List (Step 3) <ArrowRight size={15} /></>
            )}
          </button>
        )}
      </div>

    </div>
  );
};

export default BulkUpload;
