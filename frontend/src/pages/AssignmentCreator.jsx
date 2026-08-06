import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, Plus, Trash2, CheckCircle2, FileText, Settings2, Sparkles, ArrowRight, Loader2, FileCheck, AlertTriangle, Download } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { createAssignment, parseRubricFile } from '../api/client';

const AssignmentCreator = () => {
  const navigate = useNavigate();
  const { loadAssignments, setCurrentAssignmentId } = useAssignment();

  // Form State initialized clean/empty for user input
  const [assignmentTitle, setAssignmentTitle] = useState('');
  const [courseCode, setCourseCode] = useState('');
  const [auditPercentage, setAuditPercentage] = useState(5);
  const [confidenceThreshold, setConfidenceThreshold] = useState(75);
  const [rubricFiles, setRubricFiles] = useState([]);
  const [rubricWarning, setRubricWarning] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Question List State starting with a blank question
  const [questions, setQuestions] = useState([
    { id: 1, text: '', maxMark: 50, modelAnswer: '' }
  ]);

  const downloadExcelTemplate = () => {
    const csvContent = "data:text/csv;charset=utf-8," 
      + "question_n,question,answer,max_mark\n"
      + "6,\"(a) Polymer-based injectable modified release systems come in a range of formats. One format is a polymer microsphere. Describe in point form the advantages and disadvantages... (5 marks)  (b) A rival technology to microspheres is 'in situ gelling' polymer systems... (5 marks)\",\"(a) Advantages: May be biodegradable. Disadvantages: Limited to non-acid labile. (b) Attributes: Systems contain a solvent...\",10\n"
      + "8,\"Consider the following five statements, answering whether you (1) agree or disagree and (2) provide a brief reason for your answer. (a) Lyophilization (b) Protein structure (c) Antibody-drug (d) Light sensitivity (e) Co-solvents\",\"(a) 1 mark for disagree (b) 1 mark for agree (c) 1 mark for disagree (d) 1 mark for disagree (e) 1 mark for agree\",10\n";
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "AutoGrade_Rubric_Template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const processRubricFiles = async (filesArray) => {
    const validFiles = filesArray.slice(0, 3);
    setRubricFiles(validFiles);
    setRubricWarning(null);
    setIsParsing(true);
    try {
      const formData = new FormData();
      validFiles.forEach(file => {
        formData.append('files', file);
      });

      const res = await parseRubricFile(formData);

      if (res.rubric_warning) {
        setRubricWarning(res.rubric_warning);
      }

      if (res.parsed_questions && res.parsed_questions.length > 0) {
        setQuestions([...res.parsed_questions]);
      } else if (res.extracted_text) {
        const lines = res.extracted_text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        const parsedQuestions = [];
        let qCount = 1;

        for (let i = 0; i < lines.length; i += 2) {
          parsedQuestions.push({
            id: qCount,
            question_number: `Q${qCount}`,
            text: lines[i] || `Question ${qCount}`,
            maxMark: 10,
            modelAnswer: lines[i+1] || `Extracted criteria: ${lines[i]}`
          });
          qCount++;
          if (qCount > 10) break;
        }

        if (parsedQuestions.length > 0) {
          setQuestions(parsedQuestions);
        }
      }
    } catch (err) {
      console.warn("Rubric files parsing error:", err);
    } finally {
      setIsParsing(false);
    }
  };

  const handleAddQuestion = () => {
    const newId = questions.length + 1;
    setQuestions([
      ...questions,
      { id: newId, question_number: `Q${newId}`, text: '', maxMark: 50, modelAnswer: '' }
    ]);
  };

  const handleRemoveQuestion = (id) => {
    if (questions.length > 1) {
      setQuestions(questions.filter(q => q.id !== id));
    }
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processRubricFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processRubricFiles(Array.from(e.target.files));
    }
  };

  // Strict Validation Checks for Step 1 and Step 2
  const isStep1Valid = Boolean(courseCode.trim() && assignmentTitle.trim());
  const isStep2Valid = Boolean(rubricFiles.length > 0);
  const isFormValid = isStep1Valid && isStep2Valid;

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!isStep1Valid) {
      alert("⚠️ Step 1 Incomplete: Please fill in the Course Code and Assignment Title before creating the assignment.");
      return;
    }

    if (!isStep2Valid) {
      alert("⚠️ Step 2 Incomplete: Please upload at least one Questions, Marking Rubric or Answer Scheme file before creating the assignment.");
      return;
    }

    try {
      setIsSaving(true);
      const rubricData = questions.map((q, idx) => ({
        question_number: q.question_number || `Q${idx + 1}`,
        max_score: parseFloat(q.maxMark || 10),
        prompt: q.text || `Question ${idx + 1}`,
        model_answer: q.modelAnswer || q.text
      }));

      const payload = {
        title: assignmentTitle.trim(),
        course_code: courseCode.trim(),
        rubric_data: rubricData,
        model_answer: ""
      };

      const created = await createAssignment(payload);
      await loadAssignments();
      setCurrentAssignmentId(created.id);

      alert(`Assignment '${created.title}' created in PostgreSQL and indexed into ChromaDB!`);
      navigate('/bulk-upload');
    } catch (err) {
      alert(`Failed to create assignment: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(16, 185, 129, 0.05) 100%)' }}>
        <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <Sparkles size={24} color="var(--primary)" /> Create Assignment & Upload Marking Scheme
        </h2>
        <p style={{ margin: '0.4rem 0 0 0', color: 'var(--text-muted)' }}>
          Complete Step 1 & Step 2 below to parse questions and index ChromaDB vector context.
        </p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {/* Section 1: Basic Details */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <h3 style={{ marginBottom: '1.25rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" /> 1. Assignment Details <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>*Required</span>
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
            <div>
              <label className="label">Course Code *</label>
              <input
                type="text"
                className="input-field"
                value={courseCode}
                onChange={(e) => setCourseCode(e.target.value)}
                placeholder="Enter course code (e.g. PHR1021)..."
                required
              />
            </div>
            <div>
              <label className="label">Assignment Title *</label>
              <input
                type="text"
                className="input-field"
                value={assignmentTitle}
                onChange={(e) => setAssignmentTitle(e.target.value)}
                placeholder="Enter assignment title..."
                required
              />
            </div>
          </div>
        </div>

        {/* Section 2: Rubric File Drop Box */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <h3 style={{ margin: '0 0 0.4rem 0', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <UploadCloud size={20} color="var(--primary)" /> 2. Upload Questions, Marking Rubric & Answer Scheme <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>*Required</span>
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                <span className="status-badge" style={{ backgroundColor: 'rgba(16, 185, 129, 0.12)', color: 'var(--success)', fontWeight: 600 }}>
                  Recommended: Excel (.xlsx / .csv)
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  | PDF (.pdf) and Word (.docx) are also supported
                </span>
              </div>
            </div>

            <button 
              type="button" 
              className="btn btn-outline" 
              onClick={downloadExcelTemplate}
              style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem' }}
            >
              <Download size={15} color="var(--primary)" /> Download Excel Rubric Template (.csv)
            </button>
          </div>

          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleFileDrop}
            style={{
              border: `2px dashed ${isDragging ? 'var(--primary)' : !isStep2Valid ? 'var(--warning)' : 'var(--border)'}`,
              borderRadius: '12px',
              padding: '2rem 1.5rem',
              textAlign: 'center',
              backgroundColor: isDragging ? 'var(--primary-light)' : 'rgba(244, 247, 249, 0.5)',
              cursor: 'pointer'
            }}
            onClick={() => document.getElementById('rubricFileInput').click()}
          >
            <input
              id="rubricFileInput"
              type="file"
              multiple
              accept=".xlsx,.csv,.pdf,.docx,.txt"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            {isParsing ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: 'var(--primary)' }}>
                <Loader2 size={32} className="spin" />
                <div style={{ textAlign: 'left' }}>
                  <h4 style={{ margin: 0, color: 'var(--primary-dark)' }}>Extracting {rubricFiles.length} File(s)...</h4>
                  <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)' }}>Merging questions and rubrics into fields below</p>
                </div>
              </div>
            ) : rubricFiles.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', color: 'var(--success)' }}>
                <CheckCircle2 size={32} />
                <h4 style={{ margin: 0, color: 'var(--text-main)' }}>{rubricFiles.length} File(s) Attached</h4>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  {rubricFiles.map((f, i) => (
                    <span key={i} className="status-badge" style={{ backgroundColor: 'var(--success-bg)', color: 'var(--success)' }}>
                      📄 {f.name} ({(f.size/1024).toFixed(1)} KB)
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <div>
                <UploadCloud size={40} color="var(--primary)" style={{ marginBottom: '0.5rem', opacity: 0.8 }} />
                <h4 style={{ margin: '0 0 0.25rem 0', color: 'var(--secondary)' }}>
                  Drag & Drop Questions, Marking Rubric & Answer Scheme Files Here *
                </h4>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                  Supports XLSX, CSV, PDF, DOCX or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Click to Browse</span>
                </p>
              </div>
            )}
          </div>

          {/* Missing Rubric Warning Banner */}
          {rubricWarning && (
            <div style={{ marginTop: '1rem', padding: '1rem 1.25rem', backgroundColor: 'rgba(245, 158, 11, 0.08)', borderLeft: '4px solid var(--warning)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <AlertTriangle size={22} color="var(--warning)" style={{ flexShrink: 0 }} />
              <div>
                <h4 style={{ margin: 0, color: 'var(--warning)', fontSize: '0.95rem' }}>Marking Rubric Warning</h4>
                <p style={{ margin: '0.2rem 0 0 0', fontSize: '0.875rem', color: 'var(--text-main)' }}>
                  {rubricWarning}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Section 3: Question Builder */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileCheck size={20} color="var(--primary)" /> 3. Extracted Question & Model Answer Breakdown
            </h3>
            <button type="button" className="btn btn-outline" onClick={handleAddQuestion} style={{ fontSize: '0.85rem' }}>
              <Plus size={16} /> Add Question
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {questions.map((q, idx) => (
              <div key={q.id} style={{ background: 'var(--bg-main)', border: '1px solid var(--border)', borderRadius: '10px', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <span style={{ fontWeight: 700, color: 'var(--primary)', fontSize: '0.95rem' }}>Question {q.question_number || `Q${idx + 1}`}</span>
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
                  <label className="label">Question Prompt / Criteria Description</label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="Enter question prompt..."
                    value={q.text}
                    onChange={(e) => {
                      const val = e.target.value;
                      setQuestions(questions.map(item => item.id === q.id ? { ...item, text: val } : item));
                    }}
                  />
                </div>

                <div>
                  <label className="label">Model Answer & Marking Criteria (For ChromaDB Vector Search)</label>
                  <textarea
                    rows={3}
                    className="input-field"
                    style={{ resize: 'vertical' }}
                    placeholder="Enter marking criteria allocation and model answer key points..."
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

        {/* Section 4: Human-in-the-Loop Safeguards */}
        <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
          <h3 style={{ marginBottom: '1rem', color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Settings2 size={20} color="var(--primary)" /> 4. Human-in-the-Loop Safeguards
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
                Randomly flags {auditPercentage}% of auto-approved papers for quality assurance.
              </p>
            </div>

            <div>
              <label className="label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Low Confidence Boundary Threshold</span>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{confidenceThreshold}%</span>
              </label>
              <input
                type="range"
                min="50"
                max="95"
                step="5"
                value={confidenceThreshold}
                onChange={(e) => setConfidenceThreshold(e.target.value)}
                style={{ width: '100%', accentColor: 'var(--primary)' }}
              />
              <p style={{ fontSize: '0.8rem', marginTop: '0.4rem', color: 'var(--text-muted)' }}>
                Flags papers for manual review when AI evaluation confidence is under {confidenceThreshold}%.
              </p>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', marginBottom: '2rem' }}>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/')}>
            Cancel
          </button>
          <button 
            type="submit" 
            className="btn btn-primary" 
            disabled={isSaving || isParsing || !isFormValid} 
            style={{ padding: '0.625rem 1.5rem', fontSize: '0.95rem', opacity: !isFormValid ? 0.6 : 1, cursor: !isFormValid ? 'not-allowed' : 'pointer' }}
          >
            {isSaving ? 'Creating...' : 'Create Assignment & Index Rubric'} <ArrowRight size={18} />
          </button>
        </div>
      </form>
    </div>
  );
};

export default AssignmentCreator;
