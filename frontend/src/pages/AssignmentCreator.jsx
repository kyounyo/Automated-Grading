import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, Plus, Trash2, CheckCircle2, FileText, Sparkles, ArrowRight, Loader2, FileCheck, AlertTriangle, Download } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { createAssignment, parseRubricFile } from '../api/client';

const AssignmentCreator = () => {
  const navigate = useNavigate();
  const { loadAssignments, setCurrentAssignmentId } = useAssignment();

  // Form State initialized clean/empty for user input
  const [assignmentTitle, setAssignmentTitle] = useState('');
  const [courseCode, setCourseCode] = useState('');
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

  const processRubricFiles = async (filesArray, isAppend = false) => {
    let newFiles = Array.from(filesArray);
    let combinedFiles = isAppend ? [...rubricFiles, ...newFiles] : newFiles;

    // Deduplicate by file name and size
    const uniqueMap = new Map();
    combinedFiles.forEach(f => uniqueMap.set(`${f.name}-${f.size}`, f));
    const validFiles = Array.from(uniqueMap.values()).slice(0, 5);

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

      const questionsList = res.parsed_questions || res.extracted_questions || [];
      if (questionsList.length > 0) {
        const mappedQuestions = questionsList.map((q, idx) => ({
          id: Date.now() + idx,
          question_number: q.question_number || (q.number ? `Q${q.number}` : `Q${idx + 1}`),
          text: q.text || q.prompt || q.question || '',
          maxMark: q.maxMark != null ? q.maxMark : (q.max_score != null ? q.max_score : 10),
          modelAnswer: q.modelAnswer || q.model_answer || q.answer || ''
        }));
        setQuestions(mappedQuestions);
      }
    } catch (err) {
      alert(`Error parsing rubric files: ${err.message}`);
    } finally {
      setIsParsing(false);
    }
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processRubricFiles(e.dataTransfer.files, false);
    }
  };

  const handleFileSelect = (e, isAppend = false) => {
    if (e.target.files && e.target.files.length > 0) {
      processRubricFiles(e.target.files, isAppend);
    }
  };

  const handleAddQuestion = () => {
    const nextQNum = questions.length + 1;
    setQuestions([
      ...questions,
      { id: Date.now(), question_number: `Q${nextQNum}`, text: '', maxMark: 10, modelAnswer: '' }
    ]);
  };

  const handleRemoveQuestion = (id) => {
    if (questions.length > 1) {
      setQuestions(questions.filter(q => q.id !== id));
    }
  };

  const handleRemoveRubricFile = (indexToRemove, e) => {
    e.stopPropagation();
    const updated = rubricFiles.filter((_, idx) => idx !== indexToRemove);
    if (updated.length > 0) {
      processRubricFiles(updated, false);
    } else {
      setRubricFiles([]);
      setRubricWarning(null);
      setQuestions([
        { id: Date.now(), question_number: 'Q1', text: '', maxMark: 10, modelAnswer: '' }
      ]);
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
    <div style={{ maxWidth: '1240px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* 1. Header (Unboxed Minimalist) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.5rem', fontWeight: 800 }}>
            Create Assignment
          </h2>
          <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.825rem' }}>
            Complete Step 1 & Step 2 below to parse questions, rubrics & answer schemes. Modify parsed components in Step 3 if necessary.
          </p>
        </div>

        {/* Quick Actions in Header to save bottom space */}
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/')} style={{ fontSize: '0.8rem', padding: '0.4rem 0.85rem' }}>
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="btn btn-primary"
            disabled={isSaving || isParsing || !isFormValid}
            style={{ fontSize: '0.8rem', padding: '0.4rem 1rem', opacity: !isFormValid ? 0.6 : 1, cursor: !isFormValid ? 'not-allowed' : 'pointer' }}
          >
            {isSaving ? 'Creating...' : 'Create & Index Rubric'} <ArrowRight size={14} />
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

        {/* 2. SIDE-BY-SIDE SECTION: Step 1 (Details) + Step 2 (Upload Rubrics) */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.35fr', gap: '1.25rem', alignItems: 'stretch' }}>

          {/* Column 1: Step 1 Assignment Details */}
          <div className="card-panel" style={{ padding: '1.35rem 1.6rem', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', minHeight: '235px' }}>
            <h3 style={{ marginBottom: '1.15rem', color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              <FileText size={18} color="var(--primary)" /> 1. Assignment Details <span style={{ color: 'var(--danger)', fontSize: '0.775rem', fontWeight: 600 }}>*Required</span>
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label className="label" style={{ fontSize: '0.825rem', marginBottom: '0.35rem' }}>Course Code *</label>
                <input
                  type="text"
                  className="input-field"
                  style={{ padding: '0.55rem 0.85rem', fontSize: '0.875rem' }}
                  value={courseCode}
                  onChange={(e) => setCourseCode(e.target.value)}
                  placeholder="e.g. PHR1021"
                  required
                />
              </div>

              <div>
                <label className="label" style={{ fontSize: '0.825rem', marginBottom: '0.35rem' }}>Assignment Title *</label>
                <input
                  type="text"
                  className="input-field"
                  style={{ padding: '0.55rem 0.85rem', fontSize: '0.875rem' }}
                  value={assignmentTitle}
                  onChange={(e) => setAssignmentTitle(e.target.value)}
                  placeholder="e.g. Pharmacokinetics Assignment 1"
                  required
                />
              </div>
            </div>
          </div>

          {/* Column 2: Step 2 Upload Marking Rubric & Answer Scheme */}
          <div className="card-panel" style={{ padding: '1.35rem 1.6rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '235px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                  <UploadCloud size={18} color="var(--primary)" /> 2. Upload Marking Scheme <span style={{ color: 'var(--danger)', fontSize: '0.775rem', fontWeight: 600 }}>*Required</span>
                </h3>

                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={downloadExcelTemplate}
                  style={{ fontSize: '0.775rem', padding: '0.3rem 0.7rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                >
                  <Download size={14} color="var(--primary)" /> Template (.csv)
                </button>
              </div>

              {/* Full-Height Clean Drop Zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
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
                onClick={() => document.getElementById('rubricFileInput').click()}
              >
                <input
                  id="rubricFileInput"
                  type="file"
                  multiple
                  accept=".xlsx,.xls,.csv,.pdf"
                  onChange={handleFileSelect}
                  style={{ display: 'none' }}
                />

                {isParsing ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', color: 'var(--primary)' }}>
                    <Loader2 size={24} className="spin" />
                    <div style={{ textAlign: 'left' }}>
                      <h4 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--primary-dark)' }}>Extracting {rubricFiles.length} File(s)...</h4>
                      <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-muted)' }}>Parsing questions & answer keys</p>
                    </div>
                  </div>
                ) : rubricFiles.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--success)' }}>
                      <CheckCircle2 size={20} />
                      <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-main)' }}>{rubricFiles.length} File(s) Attached</span>
                    </div>

                    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                      {rubricFiles.map((f, i) => (
                        <span
                          key={i}
                          className="status-badge"
                          style={{
                            backgroundColor: 'var(--success-bg)',
                            color: 'var(--success)',
                            fontSize: '0.75rem',
                            padding: '0.2rem 0.5rem',
                            border: '1px solid var(--success-border)'
                          }}
                        >
                          📄 {f.name} ({(f.size / 1024).toFixed(1)} KB)
                          <span
                            onClick={(e) => handleRemoveRubricFile(i, e)}
                            title="Remove file"
                            style={{ cursor: 'pointer', fontWeight: 700, marginLeft: '0.3rem', color: 'var(--danger)' }}
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
                        document.getElementById('addMoreRubricFileInput').click();
                      }}
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.6rem', marginTop: '0.2rem' }}
                    >
                      <Plus size={13} color="var(--primary)" /> Add More
                    </button>
                    <input
                      id="addMoreRubricFileInput"
                      type="file"
                      multiple
                      accept=".xlsx,.xls,.csv,.pdf"
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => handleFileSelect(e, true)}
                      style={{ display: 'none' }}
                    />
                  </div>
                ) : (
                  <div>
                    <UploadCloud size={28} color="var(--primary)" style={{ marginBottom: '0.25rem', opacity: 0.8 }} />
                    <h4 style={{ margin: '0 0 0.2rem 0', fontSize: '0.875rem', color: 'var(--secondary)', fontWeight: 700 }}>
                      Drag & drop Questions, Rubric or Answer Scheme files here
                    </h4>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0 }}>
                      Supports <strong>.xlsx, .csv, .pdf</strong> or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Browse files</span>
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Warning Banner */}
            {rubricWarning && (
              <div style={{ marginTop: '0.65rem', padding: '0.5rem 0.75rem', backgroundColor: 'var(--warning-bg)', border: '1px solid var(--warning-border)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <AlertTriangle size={16} color="var(--warning)" style={{ flexShrink: 0 }} />
                <p style={{ margin: 0, fontSize: '0.775rem', color: 'var(--warning)' }}>
                  {rubricWarning}
                </p>
              </div>
            )}
          </div>

        </div>

        {/* 3. Section 3: Question Builder (Side-by-Side Question Prompt & Model Answer Columns) */}
        <div className="card-panel" style={{ padding: '1.35rem 1.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.15rem' }}>
            <div>
              <h3 style={{ margin: 0, color: 'var(--secondary)', fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <FileCheck size={18} color="var(--primary)" /> 3. Extracted Questions & Model Answers ({questions.length} Items)
              </h3>
              <p style={{ margin: '0.2rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.775rem' }}>
                Review and fine-tune parsed criteria. AutoGrade+ uses model answers to index criteria into ChromaDB.
              </p>
            </div>
            
            <button type="button" className="btn btn-outline" onClick={handleAddQuestion} style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
              <Plus size={14} /> Add Question
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            {questions.map((q, idx) => (
              <div
                key={q.id}
                className="card-secondary"
                style={{ padding: '0.85rem 1.1rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}
              >
                {/* Question Header Bar */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontWeight: 800, color: 'var(--primary-dark)', fontSize: '0.875rem' }}>
                      Question {q.question_number || `Q${idx + 1}`}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <span style={{ fontSize: '0.775rem', fontWeight: 600, color: 'var(--text-muted)' }}>Max Mark:</span>
                      <input
                        type="number"
                        className="input-field"
                        style={{ width: '60px', padding: '0.25rem 0.45rem', fontSize: '0.8rem', textAlign: 'center' }}
                        value={q.maxMark}
                        onChange={(e) => {
                          const val = e.target.value;
                          setQuestions(questions.map(item => item.id === q.id ? { ...item, maxMark: val } : item));
                        }}
                      />
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>pts</span>
                    </div>

                    {questions.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveQuestion(q.id)}
                        title="Remove question"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', display: 'flex', alignItems: 'center', padding: '0.2rem' }}
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </div>

                {/* 2-Column Side-by-Side: Prompt on Left (50%), Model Answer on Right (50%) */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.85rem' }}>
                  <div>
                    <label className="label" style={{ fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                      Question Prompt / Criteria Description
                    </label>
                    <textarea
                      rows={3}
                      className="input-field"
                      style={{ resize: 'vertical', fontSize: '0.8rem', lineHeight: '1.4', padding: '0.45rem 0.65rem' }}
                      placeholder="Enter question prompt or criteria..."
                      value={q.text}
                      onChange={(e) => {
                        const val = e.target.value;
                        setQuestions(questions.map(item => item.id === q.id ? { ...item, text: val } : item));
                      }}
                    />
                  </div>

                  <div>
                    <label className="label" style={{ fontSize: '0.75rem', marginBottom: '0.2rem' }}>
                      Model Answer & Marking Allocation (ChromaDB Key)
                    </label>
                    <textarea
                      rows={3}
                      className="input-field"
                      style={{ resize: 'vertical', fontSize: '0.8rem', lineHeight: '1.4', padding: '0.45rem 0.65rem' }}
                      placeholder="Enter marking rubric keywords, key points and mark allocations..."
                      value={q.modelAnswer}
                      onChange={(e) => {
                        const val = e.target.value;
                        setQuestions(questions.map(item => item.id === q.id ? { ...item, modelAnswer: val } : item));
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom Submission Bar */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginBottom: '1.5rem' }}>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/')} style={{ fontSize: '0.85rem' }}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSaving || isParsing || !isFormValid}
            style={{ padding: '0.5rem 1.35rem', fontSize: '0.875rem', opacity: !isFormValid ? 0.6 : 1, cursor: !isFormValid ? 'not-allowed' : 'pointer' }}
          >
            {isSaving ? 'Creating...' : 'Create Assignment & Index Rubric'} <ArrowRight size={15} />
          </button>
        </div>
      </form>
    </div>
  );
};

export default AssignmentCreator;
