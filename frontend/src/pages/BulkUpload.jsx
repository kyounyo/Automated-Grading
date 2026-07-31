import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, FileText, CheckCircle2, AlertCircle, Play, Trash2, ArrowRight, Loader2 } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const BulkUpload = () => {
  const navigate = useNavigate();
  const { currentAssignmentId, setCurrentAssignmentId, availableAssignments = [] } = useAssignment();
  
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([
    { id: '1', name: 'student_32918824_submission.pdf', size: '1.2 MB', status: 'Ready for AI' },
    { id: '2', name: 'student_32918825_submission.pdf', size: '850 KB', status: 'Ready for AI' },
    { id: '3', name: 'student_32918826_submission.pdf', size: '1.5 MB', status: 'Ready for AI' },
    { id: '4', name: 'student_32918827_submission.pdf', size: '920 KB', status: 'Ready for AI' },
    { id: '5', name: 'student_32918828_submission.pdf', size: '1.1 MB', status: 'Ready for AI' },
    { id: '6', name: 'student_32918829_submission.pdf', size: '1.4 MB', status: 'Ready for AI' }
  ]);

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
      const newFiles = Array.from(e.dataTransfer.files).map((file, idx) => ({
        id: Date.now() + '-' + idx,
        name: file.name,
        size: (file.size / 1024).toFixed(1) + ' KB',
        status: 'Ready for AI'
      }));
      setUploadedFiles(prev => [...prev, ...newFiles]);
    }
  };

  const handleFileInput = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files).map((file, idx) => ({
        id: Date.now() + '-' + idx,
        name: file.name,
        size: (file.size / 1024).toFixed(1) + ' KB',
        status: 'Ready for AI'
      }));
      setUploadedFiles(prev => [...prev, ...newFiles]);
    }
  };

  const handleRemoveFile = (id) => {
    setUploadedFiles(uploadedFiles.filter(f => f.id !== id));
  };

  const handleStartGrading = () => {
    setIsProcessing(true);
    setTimeout(() => {
      setIsProcessing(false);
      alert('Batch AI grading completed! Redirecting to Dashboard metrics...');
      navigate('/');
    }, 2000);
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(16, 185, 129, 0.05) 100%)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <UploadCloud size={26} color="var(--primary)" /> Bulk Upload Student Submissions
          </h2>
          <p style={{ margin: '0.4rem 0 0 0', color: 'var(--text-muted)' }}>
            Upload student PDF or text submissions to run automated AI grading and rubric evaluation.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="btn btn-outline" onClick={() => setUploadedFiles([])}>
            Clear Files
          </button>
          <button
            className="btn btn-primary"
            onClick={handleStartGrading}
            disabled={uploadedFiles.length === 0 || isProcessing}
            style={{ padding: '0.625rem 1.25rem', fontSize: '0.95rem' }}
          >
            {isProcessing ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
            {isProcessing ? 'Grading Batch...' : 'Start AI Auto-Grading'}
          </button>
        </div>
      </div>

      {/* Target Assignment Selector Drop Box */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
        <label className="label" style={{ fontSize: '1rem', marginBottom: '0.5rem', fontWeight: 600 }}>
          Select Target Assignment:
        </label>
        <select
          className="input-field"
          style={{ padding: '0.6rem 1rem', fontSize: '0.95rem', fontWeight: 600, color: 'var(--primary-dark)', backgroundColor: '#fff', border: '2px solid var(--primary)' }}
          value={currentAssignmentId}
          onChange={(e) => setCurrentAssignmentId(e.target.value)}
        >
          {availableAssignments.map(assignment => (
            <option key={assignment.id} value={assignment.id}>{assignment.title}</option>
          ))}
        </select>
      </div>

      {/* Drag & Drop Box */}
      <div className="glass-panel" style={{ padding: '2rem' }}>
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => document.getElementById('bulkFileInput').click()}
          style={{
            border: `2px dashed ${isDragging ? 'var(--primary)' : 'var(--border)'}`,
            borderRadius: '16px',
            padding: '3.5rem 2rem',
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
            accept=".pdf,.docx,.txt,.zip"
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
              <UploadCloud size={36} color="var(--primary)" />
            </div>

            <div>
              <h3 style={{ margin: '0 0 0.4rem 0', color: 'var(--secondary)' }}>
                Drag & Drop Student Submissions Here
              </h3>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                Supports batch uploading of <strong>PDFs, DOCX, ZIP</strong> files or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Click to Browse</span>
              </p>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
              <span className="status-badge" style={{ backgroundColor: 'var(--bg-main)', color: 'var(--text-muted)' }}>.PDF</span>
              <span className="status-badge" style={{ backgroundColor: 'var(--bg-main)', color: 'var(--text-muted)' }}>.DOCX</span>
              <span className="status-badge" style={{ backgroundColor: 'var(--bg-main)', color: 'var(--text-muted)' }}>.ZIP</span>
            </div>
          </div>
        </div>
      </div>

      {/* Uploaded File Queue List */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" /> Uploaded Queue ({uploadedFiles.length} files)
          </h3>
          <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            Total Size: ~{(uploadedFiles.length * 1.1).toFixed(1)} MB
          </span>
        </div>

        {uploadedFiles.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-main)', borderRadius: '10px' }}>
            <AlertCircle size={32} style={{ opacity: 0.5, marginBottom: '0.5rem' }} />
            <p style={{ margin: 0 }}>No files added yet. Drop student submission files above to get started.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {uploadedFiles.map((file) => (
              <div
                key={file.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.875rem 1.25rem',
                  background: 'var(--bg-main)',
                  border: '1px solid var(--border)',
                  borderRadius: '10px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <FileText size={22} color="var(--primary)" />
                  <div>
                    <h4 style={{ margin: 0, fontSize: '0.925rem', color: 'var(--text-main)' }}>{file.name}</h4>
                    <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>{file.size}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                  <span style={{
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    padding: '0.25rem 0.6rem',
                    borderRadius: '6px',
                    backgroundColor: 'var(--success-bg)',
                    color: 'var(--success)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem'
                  }}>
                    <CheckCircle2 size={14} /> {file.status}
                  </span>

                  <button
                    onClick={() => handleRemoveFile(file.id)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', transition: 'color 0.2s' }}
                    title="Remove file"
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action Footer */}
      {uploadedFiles.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', marginBottom: '2rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleStartGrading}
            disabled={isProcessing}
            style={{ padding: '0.75rem 1.75rem', fontSize: '1rem' }}
          >
            {isProcessing ? 'Grading Batch...' : 'Run AutoGrade+ Batch'} <ArrowRight size={20} />
          </button>
        </div>
      )}
    </div>
  );
};

export default BulkUpload;
