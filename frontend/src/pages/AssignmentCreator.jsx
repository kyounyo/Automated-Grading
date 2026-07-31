import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, Plus, Trash2, CheckCircle2, FileText, Settings2, Sparkles, ArrowRight } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const AssignmentCreator = () => {
  const navigate = useNavigate();
  const { availableAssignments } = useAssignment();

  // Form State
  const [assignmentTitle, setAssignmentTitle] = useState('NLP102 - Sentiment Analysis Quiz');
  const [courseCode, setCourseCode] = useState('FIT3143');
  const [totalMarks, setTotalMarks] = useState(100);
  const [auditPercentage, setAuditPercentage] = useState(5);
  const [borderlineThreshold, setBorderlineThreshold] = useState(50);
  const [rubricFile, setRubricFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  // Question List State
  const [questions, setQuestions] = useState([
    { id: 1, text: 'Q1. Explain the difference between Vader Sentiment and BERT fine-tuning.', maxMark: 20, modelAnswer: 'Vader is lexicon and rule-based; BERT is a contextual deep neural model.' },
    { id: 2, text: 'Q2. How does tokenization affect sentiment classification in noisy social media text?', maxMark: 20, modelAnswer: 'Subword tokenization (BPE) handles out-of-vocabulary words and emojis effectively.' }
  ]);

  const handleAddQuestion = () => {
    const newId = questions.length + 1;
    setQuestions([
      ...questions,
      { id: newId, text: `Q${newId}. Write the question prompt here...`, maxMark: 20, modelAnswer: 'Write the ideal model answer or grading rubric points here...' }
    ]);
  };

  const handleRemoveQuestion = (id) => {
    setQuestions(questions.filter(q => q.id !== id));
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setRubricFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setRubricFile(e.target.files[0]);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    alert('Assignment created successfully! Redirecting to Bulk Upload...');
    navigate('/bulk-upload');
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(226, 67, 1, 0.05) 100%)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Sparkles size={24} color="var(--primary)" /> Create Assignment & Marking Scheme
          </h2>
          <p style={{ margin: '0.4rem 0 0 0', color: 'var(--text-muted)' }}>
            Configure questions, upload your official marking rubric, and adjust AI grading safeguards.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={handleSubmit}>
          Save & Proceed <ArrowRight size={18} />
        </button>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {/* Section 1: Basic Information */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <h3 style={{ marginBottom: '1.25rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" /> 1. Basic Details
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1.25rem' }}>
            <div>
              <label className="label">Course Code / Unit</label>
              <input
                type="text"
                className="input-field"
                value={courseCode}
                onChange={(e) => setCourseCode(e.target.value)}
                placeholder="e.g. FIT3143"
                required
              />
            </div>
            <div>
              <label className="label">Assignment Title</label>
              <input
                type="text"
                className="input-field"
                value={assignmentTitle}
                onChange={(e) => setAssignmentTitle(e.target.value)}
                placeholder="e.g. Quiz 1 - Tokenization"
                required
              />
            </div>
            <div>
              <label className="label">Total Max Score</label>
              <input
                type="number"
                className="input-field"
                value={totalMarks}
                onChange={(e) => setTotalMarks(e.target.value)}
                required
              />
            </div>
          </div>
        </div>

        {/* Section 2: Rubric Document Drop Box */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <h3 style={{ marginBottom: '0.5rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <UploadCloud size={20} color="var(--primary)" /> 2. Upload Reference Marking Scheme / Rubric
          </h3>
          <p style={{ fontSize: '0.875rem', marginBottom: '1rem', color: 'var(--text-muted)' }}>
            Upload your official marking scheme document (PDF, Word, or Excel). The AI pipeline will extract criteria automatically.
          </p>

          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleFileDrop}
            style={{
              border: `2px dashed ${isDragging ? 'var(--primary)' : 'var(--border)'}`,
              borderRadius: '12px',
              padding: '2.5rem 1.5rem',
              textAlign: 'center',
              backgroundColor: isDragging ? 'var(--primary-light)' : 'rgba(244, 247, 249, 0.5)',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
            onClick={() => document.getElementById('rubricFileInput').click()}
          >
            <input
              id="rubricFileInput"
              type="file"
              accept=".pdf,.docx,.doc,.xlsx"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            {rubricFile ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: 'var(--success)' }}>
                <CheckCircle2 size={32} />
                <div style={{ textAlign: 'left' }}>
                  <h4 style={{ margin: 0, color: 'var(--text-main)' }}>{rubricFile.name}</h4>
                  <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)' }}>{(rubricFile.size / 1024).toFixed(1)} KB — Ready for extraction</p>
                </div>
              </div>
            ) : (
              <div>
                <UploadCloud size={48} color="var(--primary)" style={{ marginBottom: '0.75rem', opacity: 0.8 }} />
                <h4 style={{ margin: '0 0 0.25rem 0', color: 'var(--secondary)' }}>
                  Drag & Drop Marking Scheme File Here
                </h4>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                  Supports PDF, DOCX, XLSX up to 25MB or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Browse File</span>
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Section 3: Question Builder */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileText size={20} color="var(--primary)" /> 3. Question & Answer Scheme Breakdown
            </h3>
            <button type="button" className="btn btn-outline" onClick={handleAddQuestion} style={{ fontSize: '0.85rem' }}>
              <Plus size={16} /> Add Question
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {questions.map((q, idx) => (
              <div key={q.id} style={{ background: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '10px', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <span style={{ fontWeight: 700, color: 'var(--primary)', fontSize: '0.95rem' }}>Question {idx + 1}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="label" style={{ margin: 0 }}>Max Mark:</span>
                      <input
                        type="number"
                        className="input-field"
                        style={{ width: '70px', padding: '0.3rem 0.5rem' }}
                        value={q.maxMark}
                        onChange={(e) => {
                          const val = e.target.value;
                          setQuestions(questions.map(item => item.id === q.id ? { ...item, maxMark: val } : item));
                        }}
                      />
                    </div>
                    {questions.length > 1 && (
                      <button type="button" onClick={() => handleRemoveQuestion(q.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)' }}>
                        <Trash2 size={18} />
                      </button>
                    )}
                  </div>
                </div>

                <div style={{ marginBottom: '0.75rem' }}>
                  <label className="label">Question Prompt</label>
                  <input
                    type="text"
                    className="input-field"
                    value={q.text}
                    onChange={(e) => {
                      const val = e.target.value;
                      setQuestions(questions.map(item => item.id === q.id ? { ...item, text: val } : item));
                    }}
                  />
                </div>

                <div>
                  <label className="label">Model Answer / Key Points for AI</label>
                  <textarea
                    rows={2}
                    className="input-field"
                    style={{ resize: 'vertical' }}
                    value={q.modelAnswer}
                    onChange={(e) => {
                      const val = e.target.value;
                      setQuestions(questions.map(item => item.id === q.id ? { ...item, modelAnswer: val } : item));
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Section 4: AI Safeguards & Audit Settings */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <h3 style={{ marginBottom: '1rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Settings2 size={20} color="var(--primary)" /> 4. Human-in-the-Loop Audit Policy
          </h3>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
            <div>
              <label className="label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Random Quality Audit Sampling Rate</span>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{auditPercentage}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="20"
                value={auditPercentage}
                onChange={(e) => setAuditPercentage(e.target.value)}
                style={{ width: '100%', accentColor: 'var(--primary)' }}
              />
              <p style={{ fontSize: '0.8rem', marginTop: '0.4rem', color: 'var(--text-muted)' }}>
                Randomly flags {auditPercentage}% of auto-approved papers for human verification.
              </p>
            </div>

            <div>
              <label className="label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Borderline Score Review Boundary</span>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>±{borderlineThreshold}% boundary</span>
              </label>
              <input
                type="range"
                min="40"
                max="60"
                value={borderlineThreshold}
                onChange={(e) => setBorderlineThreshold(e.target.value)}
                style={{ width: '100%', accentColor: 'var(--primary)' }}
              />
              <p style={{ fontSize: '0.8rem', marginTop: '0.4rem', color: 'var(--text-muted)' }}>
                Flags submissions close to passing boundaries ({borderlineThreshold}%) for manual lecturer sign-off.
              </p>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', marginBottom: '2rem' }}>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/')}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" style={{ padding: '0.625rem 1.5rem', fontSize: '0.95rem' }}>
            Save & Continue to Bulk Upload <ArrowRight size={18} />
          </button>
        </div>
      </form>
    </div>
  );
};

export default AssignmentCreator;
