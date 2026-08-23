import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, FileText, CheckCircle2, AlertCircle, Play, Trash2, ArrowRight, Loader2, Sparkles, Download, Plus } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { uploadSubmissionFile } from '../api/client';

const BulkUpload = () => {
  const navigate = useNavigate();
  const { currentAssignmentId, setCurrentAssignmentId, assignments = [], triggerGradeAll, loadSubmissions } = useAssignment();

  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]); // Local staged files { id, file, name, size, status: 'Staged' | 'Uploaded' }
  const [uploadStatus, setUploadStatus] = useState('');

  const downloadSubmissionsTemplate = () => {
    const csvContent = "data:text/csv;charset=utf-8,"
      + "Student_ID,question_no,Response\n"
      + "30720842,6,-\n"
      + "30881447,6,\"(a) Advantages: May be biodegradable - do not need removal. Provides longer release duration. Disadvantages: Limited to non-acid labile. (b) In situ gelling attributes: Systems contain solvent...\"\n"
      + "30883350,6,\"(a) Advantages: Reduces administration frequency. Injectable system no surgery required. Disadvantages: Complex manufacturing process...\"\n"
      + "30720842,8,\"(a) Disagree: Lyophilization is not necessary if drug is stable in solution...\"\n"
      + "30881447,8,\"(a) Disagree: Stable in solution (b) Agree: Hydrophobic parts associate...\"\n"
      + "30883350,8,\"(a) Disagree (b) Agree: Protein structure tertiary bonds can be disrupted...\"\n";

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "AutoGrade_Student_Submissions_Template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  // Stage files in local UI state without uploading to backend
  const handleStageFiles = (filesArray) => {
    const newEntries = [];
    const existingKeys = new Set(selectedFiles.map(f => `${f.name}-${f.size}`));

    for (let i = 0; i < filesArray.length; i++) {
      const file = filesArray[i];
      const key = `${file.name}-${(file.size / 1024).toFixed(1)} KB`;
      if (!existingKeys.has(key)) {
        newEntries.push({
          id: `staged-${Date.now()}-${i}-${Math.random().toString(36).substr(2, 5)}`,
          file: file,
          name: file.name,
          size: (file.size / 1024).toFixed(1) + ' KB',
          status: 'Ready to Upload'
        });
        existingKeys.add(key);
      }
    }

    setSelectedFiles(prev => [...prev, ...newEntries]);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleStageFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileInput = (e) => {
    e.stopPropagation();
    if (e.target.files && e.target.files.length > 0) {
      handleStageFiles(Array.from(e.target.files));
      e.target.value = '';
    }
  };

  const handleRemoveFile = (id) => {
    setSelectedFiles(prev => prev.filter(f => f.id !== id));
  };

  // Upload staged files to PostgreSQL / S3 backend
  const uploadStagedFilesToBackend = async () => {
    const unuploaded = selectedFiles.filter(f => f.status !== 'Uploaded' && f.file);
    if (unuploaded.length === 0) return true;

    setUploadStatus(`Uploading ${unuploaded.length} submission file(s) to system...`);
    setIsProcessing(true);

    try {
      for (let i = 0; i < unuploaded.length; i++) {
        const item = unuploaded[i];
        const studentId = `STU${8900 + i + Math.floor(Math.random() * 100)}`;
        const studentName = item.name.split('.')[0].replace(/_/g, ' ');

        const formData = new FormData();
        formData.append('file', item.file);
        formData.append('assignment_id', currentAssignmentId || 'assign-101');
        formData.append('student_id', studentId);
        formData.append('student_name', studentName);

        setUploadStatus(`Uploading (${i + 1}/${unuploaded.length}): ${item.name}...`);
        await uploadSubmissionFile(formData);

        setSelectedFiles(prev => prev.map(f => f.id === item.id ? { ...f, status: 'Uploaded' } : f));
      }

      await loadSubmissions(currentAssignmentId);
      setUploadStatus('');
      return true;
    } catch (err) {
      console.error('Upload error:', err);
      alert(`Upload error: ${err.message}`);
      setUploadStatus('');
      return false;
    } finally {
      setIsProcessing(false);
    }
  };

  const handleConfirmUploadOnly = async () => {
    const success = await uploadStagedFilesToBackend();
    if (success) {
      alert('All student submissions successfully uploaded and saved to the database! You can now start AI batch grading whenever you are ready.');
    }
  };

  const handleStartGrading = async () => {
    try {
      setIsProcessing(true);
      // Upload any un-uploaded staged files first
      const hasUnuploaded = selectedFiles.some(f => f.status !== 'Uploaded' && f.file);
      if (hasUnuploaded) {
        const success = await uploadStagedFilesToBackend();
        if (!success) return;
      }

      setUploadStatus('Launching Multi-Agent AI Auto-Grading Batch...');
      await triggerGradeAll(currentAssignmentId);
      alert('Batch AI grading job launched asynchronously! Redirecting to Submissions list...');
      navigate('/submissions');
    } catch (err) {
      alert(`Batch grading failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
      setUploadStatus('');
    }
  };

  const unuploadedCount = selectedFiles.filter(f => f.status !== 'Uploaded').length;
  const uploadedCount = selectedFiles.filter(f => f.status === 'Uploaded').length;

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(16, 185, 129, 0.05) 100%)' }}>
        <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <UploadCloud size={26} color="var(--primary)" /> Bulk Upload Student Submissions
        </h2>
        <p style={{ margin: '0.4rem 0 0 0', color: 'var(--text-muted)' }}>
          Select or drop student submission files (PDF, DOCX, XLSX, CSV). Review your selected files before confirming upload or launching AI grading.
        </p>
      </div>

      {/* Target Assignment Selector */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
        <label className="label" style={{ fontSize: '1rem', marginBottom: '0.5rem', fontWeight: 600 }}>
          Target Assignment (ChromaDB Reference Context):
        </label>
        <select
          className="input-field"
          style={{ padding: '0.6rem 1rem', fontSize: '0.95rem', fontWeight: 600, color: 'var(--primary-dark)', backgroundColor: '#fff', border: '2px solid var(--primary)' }}
          value={currentAssignmentId}
          onChange={(e) => setCurrentAssignmentId(e.target.value)}
        >
          {assignments.length > 0 ? (
            assignments.map(a => (
              <option key={a.id} value={a.id}>{a.course_code ? `${a.course_code}: ` : ''}{a.title}</option>
            ))
          ) : (
            <option value="">No Assignments Created Yet</option>
          )}
        </select>
      </div>

      {/* Drag & Drop Box with Excel Encouragement & Template Download */}
      <div className="glass-panel" style={{ padding: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
            <span className="status-badge" style={{ backgroundColor: 'rgba(16, 185, 129, 0.12)', color: 'var(--success)', fontWeight: 600 }}>
              Recommended: Excel (.xlsx / .csv)
            </span>
            <span style={{ color: 'var(--text-muted)' }}>
              | PDF (.pdf) and Word (.docx) student submission papers are also supported
            </span>
          </div>

          <button
            type="button"
            className="btn btn-outline"
            onClick={downloadSubmissionsTemplate}
            style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem' }}
          >
            <Download size={15} color="var(--primary)" /> Download Student Submissions Excel Template (.csv)
          </button>
        </div>

        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => document.getElementById('bulkFileInput').click()}
          style={{
            border: `2px dashed ${isDragging ? 'var(--primary)' : 'var(--border)'}`,
            borderRadius: '16px',
            padding: '3rem 2rem',
            textAlign: 'center',
            backgroundColor: isDragging ? 'var(--primary-light)' : 'rgba(244, 247, 249, 0.5)',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            boxShadow: isDragging ? '0 0 20px rgba(0, 96, 156, 0.15)' : 'none'
          }}
        >
          <input
            id="bulkFileInput"
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.csv,.txt"
            onClick={(e) => e.stopPropagation()}
            onChange={handleFileInput}
            style={{ display: 'none' }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
            <div style={{
              width: '64px',
              height: '64px',
              borderRadius: '50%',
              backgroundColor: 'var(--primary-light)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              {isProcessing ? <Loader2 size={32} color="var(--primary)" className="spin" /> : <UploadCloud size={32} color="var(--primary)" />}
            </div>

            <div>
              <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--secondary)' }}>
                Drag & Drop Student Submissions Here
              </h3>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                Select files to stage them. Files will <strong style={{ color: 'var(--primary)' }}>NOT</strong> be submitted to the system until you confirm below.
              </p>
            </div>
          </div>
        </div>

        {uploadStatus && (
          <div style={{ marginTop: '1rem', color: 'var(--primary)', fontWeight: 600, fontSize: '0.9rem', textAlign: 'center' }}>
            {uploadStatus}
          </div>
        )}
      </div>

      {/* Selected File List */}
      {selectedFiles.length > 0 && (
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <CheckCircle2 size={20} color="var(--success)" /> Selected Submissions ({selectedFiles.length})
              </h3>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {uploadedCount > 0 && `${uploadedCount} uploaded to database, `}{unuploadedCount} ready to confirm
              </span>
            </div>
            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
              <button 
                type="button"
                className="btn btn-outline" 
                onClick={() => document.getElementById('bulkFileInput').click()} 
                style={{ fontSize: '0.85rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem', backgroundColor: '#fff', border: '1px solid var(--primary)', color: 'var(--primary-dark)', fontWeight: 600 }}
              >
                <Plus size={16} color="var(--primary)" /> Add More Files
              </button>
              <button className="btn btn-outline" onClick={() => setSelectedFiles([])} style={{ fontSize: '0.85rem' }}>
                Clear All
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {selectedFiles.map(file => (
              <div key={file.id} className="flex-between" style={{ padding: '0.75rem 1rem', background: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <FileText size={18} color="var(--primary)" />
                  <div>
                    <strong style={{ fontSize: '0.9rem', color: 'var(--secondary)' }}>{file.name}</strong>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginLeft: '0.75rem' }}>{file.size}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <span
                    className="status-badge"
                    style={{
                      backgroundColor: file.status === 'Uploaded' ? 'var(--success-bg)' : 'rgba(0, 96, 156, 0.1)',
                      color: file.status === 'Uploaded' ? 'var(--success)' : 'var(--primary)',
                      fontWeight: 600
                    }}
                  >
                    {file.status}
                  </span>
                  <button onClick={() => handleRemoveFile(file.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)' }} title="Remove file">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer Action Section */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '2rem' }}>
        <button className="btn btn-outline" onClick={() => navigate('/')}>
          Cancel
        </button>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {/* Option A: Explicit Confirm Upload without grading */}
          <button
            type="button"
            className="btn btn-outline"
            onClick={handleConfirmUploadOnly}
            disabled={selectedFiles.length === 0 || isProcessing || unuploadedCount === 0}
            style={{
              padding: '0.65rem 1.25rem',
              fontSize: '0.9rem',
              fontWeight: 600,
              backgroundColor: '#fff',
              border: '1.5px solid var(--primary)',
              color: 'var(--primary-dark)'
            }}
          >
            {isProcessing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} color="var(--primary)" />}
            Confirm Upload Only ({unuploadedCount})
          </button>

          {/* Option B: Confirm Upload & Start AI Auto-Grading Batch */}
          <button
            className="btn btn-primary"
            onClick={handleStartGrading}
            disabled={selectedFiles.length === 0 || isProcessing}
            style={{ padding: '0.65rem 1.5rem', fontSize: '0.95rem' }}
          >
            {isProcessing ? <Loader2 size={18} className="spin" /> : <Sparkles size={18} />}
            {isProcessing ? 'Processing...' : 'Confirm Upload & Start AI Batch'} <ArrowRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default BulkUpload;
