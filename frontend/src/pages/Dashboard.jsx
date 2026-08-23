import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, CheckCircle2, AlertTriangle, Clock, Play, ArrowRight, Sparkles, Layers, Download } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const Dashboard = () => {
  const navigate = useNavigate();
  const { currentAssignment, currentAssignmentId, submissions = [], gradeAll, loading, handleExportCSV } = useAssignment();

  const onExportCSVClick = () => {
    handleExportCSV(currentAssignment?.id || currentAssignmentId);
  };

  const totalSubmissions = submissions.length;
  const gradedApproved = submissions.filter(s => s.status === 'graded' || s.status === 'approved').length;
  const flaggedCount = submissions.filter(s => s.status === 'flagged').length;
  const pendingCount = submissions.filter(s => s.status === 'pending' || s.status === 'uploaded').length;

  // Separate graded submissions from unassessed submissions
  const gradedSubs = submissions.filter(s => s.score != null && (s.status === 'graded' || s.status === 'approved' || s.status === 'flagged'));
  const unassessedSubs = submissions.filter(s => s.score == null || s.status === 'pending' || s.status === 'uploaded' || s.status === 'extracting_answers' || s.status === 'retrieving_rubric' || s.status === 'grading');

  const totalRubricMax = (currentAssignment?.rubric_data && currentAssignment.rubric_data.length > 0)
    ? currentAssignment.rubric_data.reduce((acc, item) => acc + (parseFloat(item.max_score || item.maxMark) || 0), 0)
    : null;

  const maxMark = totalRubricMax || 20;
  const b1 = maxMark * 0.25;
  const b2 = maxMark * 0.50;
  const b3 = maxMark * 0.75;

  const fmt = (v) => (v % 1 === 0 ? Math.round(v) : v.toFixed(1));

  const scoreDistribution = [
    { range: 'Unassessed', count: unassessedSubs.length },
    { range: `0 - ${fmt(b1)} pts`, count: gradedSubs.filter(s => s.score <= b1).length },
    { range: `${fmt(b1 + 0.1)} - ${fmt(b2)} pts`, count: gradedSubs.filter(s => s.score > b1 && s.score <= b2).length },
    { range: `${fmt(b2 + 0.1)} - ${fmt(b3)} pts`, count: gradedSubs.filter(s => s.score > b2 && s.score <= b3).length },
    { range: `${fmt(b3 + 0.1)} - ${fmt(maxMark)} pts`, count: gradedSubs.filter(s => s.score > b3).length },
  ];

  // Class Average calculated strictly from graded papers
  const totalScoreSum = gradedSubs.reduce((acc, curr) => acc + curr.score, 0);
  const averageScore = gradedSubs.length > 0 ? (totalScoreSum / gradedSubs.length).toFixed(1) : '0.0';
  const averageDisplay = gradedSubs.length > 0
    ? (totalRubricMax ? `${averageScore} / ${totalRubricMax} marks` : `${averageScore} marks`)
    : (totalRubricMax ? `0.0 / ${totalRubricMax} marks` : 'N/A');

  // Extract Whole Question Breakdown Analytics (aggregating subparts Q6(a), Q6(b) -> Q6)
  const getParentQuestionKey = (qNum) => {
    if (!qNum) return 'Q1';
    const match = String(qNum).match(/(?:Question\s*|Q)?\s*(\d+)/i);
    return match ? `Q${match[1]}` : String(qNum);
  };

  const parentQuestionMap = {};

  // First seed max scores from rubric_data
  if (currentAssignment?.rubric_data && currentAssignment.rubric_data.length > 0) {
    currentAssignment.rubric_data.forEach((r, idx) => {
      const rawKey = r.question_number || r.criterion || `Q${idx + 1}`;
      const pKey = getParentQuestionKey(rawKey);
      const maxSc = parseFloat(r.max_score || r.maxMark || 5.0);

      if (!parentQuestionMap[pKey]) {
        parentQuestionMap[pKey] = {
          question_number: pKey,
          max_score: 0.0,
          studentScores: {}
        };
      }
      parentQuestionMap[pKey].max_score += maxSc;
    });
  }

  // Accumulate scores awarded per student for each parent question
  gradedSubs.forEach(sub => {
    const breakdown = sub.feedback?.breakdown || [];
    const studentQuestionTotals = {};

    breakdown.forEach((item, idx) => {
      if (item && typeof item === 'object') {
        const rawKey = item.question_number || `Q${idx + 1}`;
        const pKey = getParentQuestionKey(rawKey);
        const maxSc = parseFloat(item.max_score || 5.0);
        const awarded = parseFloat(item.score_awarded || 0.0);

        if (!parentQuestionMap[pKey]) {
          parentQuestionMap[pKey] = {
            question_number: pKey,
            max_score: 0.0,
            studentScores: {}
          };
        }
        
        if (!currentAssignment?.rubric_data || currentAssignment.rubric_data.length === 0) {
          parentQuestionMap[pKey].max_score += maxSc;
        }

        studentQuestionTotals[pKey] = (studentQuestionTotals[pKey] || 0.0) + awarded;
      }
    });

    Object.entries(studentQuestionTotals).forEach(([pKey, totalAwarded]) => {
      if (parentQuestionMap[pKey]) {
        parentQuestionMap[pKey].studentScores[sub.id] = totalAwarded;
      }
    });
  });

  const questionAnalyticsList = Object.values(parentQuestionMap).map(q => {
    const scores = Object.values(q.studentScores);
    const count = scores.length;
    const avg = count > 0 ? (scores.reduce((a, b) => a + b, 0) / count) : 0;
    const minScore = count > 0 ? Math.min(...scores) : 0;
    const maxScoreAchieved = count > 0 ? Math.max(...scores) : 0;
    const percentage = q.max_score > 0 ? (avg / q.max_score) * 100 : 0;

    return {
      question_number: q.question_number,
      avgScore: avg.toFixed(1),
      max_score: q.max_score,
      percentage: Math.round(percentage),
      minScore: minScore.toFixed(1),
      maxScoreAchieved: maxScoreAchieved.toFixed(1),
      count
    };
  });

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Premium Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(16, 185, 129, 0.05) 100%)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Sparkles size={24} color="var(--primary)" /> Evaluation Overview
          </h2>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn btn-outline"
            onClick={onExportCSVClick}
            disabled={totalSubmissions === 0}
            style={{ backgroundColor: '#fff', border: '1px solid var(--border)', color: 'var(--primary-dark)', padding: '0.6rem 1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}
          >
            <Download size={18} color="var(--primary)" /> Export Grades (CSV)
          </button>
          <button className="btn btn-primary" onClick={gradeAll} disabled={loading || totalSubmissions === 0 || unassessedSubs.length === 0} style={{ padding: '0.6rem 1.25rem' }}>
            <Play size={18} /> Grade All Pending Submissions
          </button>
        </div>
      </div>

      {/* Active Assignment Info Panel */}
      <div className="glass-panel" style={{ backgroundColor: '#fff', borderLeft: '4px solid var(--primary)', padding: '1.25rem 1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: '0 0 0.4rem 0', color: 'var(--primary-dark)', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" /> {currentAssignment?.title || 'No Active Assignment'}
          </h3>
          <p style={{ margin: 0, color: 'var(--text-main)', fontSize: '0.9rem', display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
            <span>Course Code: <strong style={{ color: 'var(--primary)' }}>{currentAssignment?.course_code || 'N/A'}</strong></span>
            {currentAssignment?.due_date && <span>Due Date: <strong>{currentAssignment.due_date}</strong></span>}
          </p>
        </div>
        <button className="btn btn-outline" onClick={() => navigate('/assignment-creator')} style={{ fontSize: '0.85rem' }}>
          + New Assignment
        </button>
      </div>

      {/* Metric Cards Grid - 4 Organized Boxes in 1 Single Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.25rem' }}>
        {/* Card 1: Total Submissions */}
        <div 
          className="glass-panel" 
          onClick={() => navigate('/submissions', { state: { filter: 'all' } })}
          style={{ 
            padding: '1.25rem 1.5rem', 
            borderRadius: '12px', 
            borderTop: '4px solid var(--primary)', 
            backgroundColor: '#fff', 
            display: 'flex', 
            flexDirection: 'column', 
            justifyContent: 'space-between', 
            minHeight: '130px',
            cursor: 'pointer',
            transition: 'transform 0.15s ease, box-shadow 0.15s ease'
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 16px rgba(0, 96, 156, 0.12)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none'; }}
          title="Click to view all student submissions"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Total Submissions</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'var(--primary-light)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FileText size={18} color="var(--primary)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--secondary)', lineHeight: 1.1 }}>{totalSubmissions}</div>
            <span style={{ fontSize: '0.78rem', color: 'var(--primary)', marginTop: '0.3rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontWeight: 600 }}>
              View All Submissions <ArrowRight size={13} />
            </span>
          </div>
        </div>

        {/* Card 2: Graded / Approved */}
        <div 
          className="glass-panel" 
          onClick={() => navigate('/submissions', { state: { filter: 'graded' } })}
          style={{ 
            padding: '1.25rem 1.5rem', 
            borderRadius: '12px', 
            borderTop: '4px solid var(--success)', 
            backgroundColor: '#fff', 
            display: 'flex', 
            flexDirection: 'column', 
            justifyContent: 'space-between', 
            minHeight: '130px',
            cursor: 'pointer',
            transition: 'transform 0.15s ease, box-shadow 0.15s ease'
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 16px rgba(16, 185, 129, 0.15)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none'; }}
          title="Click to view graded and approved submissions"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Graded / Approved</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(16, 185, 129, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <CheckCircle2 size={18} color="var(--success)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--success)', lineHeight: 1.1 }}>{gradedApproved}</div>
            <span style={{ fontSize: '0.78rem', color: 'var(--success)', marginTop: '0.3rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontWeight: 600 }}>
              View Graded ({gradedApproved}) <ArrowRight size={13} />
            </span>
          </div>
        </div>

        {/* Card 3: Flagged for Review (Hyperlink to all flagged papers) */}
        <div 
          className="glass-panel" 
          onClick={() => navigate('/submissions', { state: { filter: 'flagged' } })}
          style={{ 
            padding: '1.25rem 1.5rem', 
            borderRadius: '12px', 
            borderTop: '4px solid var(--warning)', 
            backgroundColor: flaggedCount > 0 ? '#fffdf7' : '#fff', 
            display: 'flex', 
            flexDirection: 'column', 
            justifyContent: 'space-between', 
            minHeight: '130px',
            cursor: 'pointer',
            border: flaggedCount > 0 ? '1.5px solid rgba(245, 158, 11, 0.3)' : '1px solid var(--border)',
            transition: 'transform 0.15s ease, box-shadow 0.15s ease'
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 16px rgba(245, 158, 11, 0.2)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none'; }}
          title="Click to review all flagged submissions requiring lecturer audit"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: flaggedCount > 0 ? '#b45309' : 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Flagged for Review
            </span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(245, 158, 11, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <AlertTriangle size={18} color="var(--warning)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: '#b45309', lineHeight: 1.1 }}>{flaggedCount}</div>
            <span style={{ fontSize: '0.78rem', color: '#b45309', marginTop: '0.3rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontWeight: 700 }}>
              {flaggedCount > 0 ? (
                <>Review Flagged Papers ({flaggedCount}) <ArrowRight size={13} /></>
              ) : (
                <>No flagged papers pending</>
              )}
            </span>
          </div>
        </div>

        {/* Card 4: Class Average Score */}
        <div className="glass-panel" style={{ padding: '1.25rem 1.5rem', borderRadius: '12px', borderTop: '4px solid var(--primary-dark)', backgroundColor: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '130px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Class Average</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(0, 96, 156, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Clock size={18} color="var(--primary-dark)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: totalRubricMax ? '1.5rem' : '2.1rem', fontWeight: 800, color: 'var(--primary-dark)', lineHeight: 1.1 }}>
              {gradedSubs.length > 0
                ? (totalRubricMax ? `${averageScore} / ${totalRubricMax}` : `${averageScore} pts`)
                : (totalRubricMax ? `0.0 / ${totalRubricMax}` : 'N/A')}
            </div>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.3rem', display: 'block' }}>Based on {gradedSubs.length} graded paper(s)</span>
          </div>
        </div>
      </div>

      {/* Cohort Score Distribution Chart */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h3 style={{ margin: 0, color: 'var(--secondary)' }}>Cohort Score Distribution</h3>
            <p style={{ margin: '0.2rem 0 0 0', fontSize: '0.825rem', color: 'var(--text-muted)' }}>
              Distribution breakdown showing assessed score brackets and unassessed papers.
            </p>
          </div>
          <button className="btn btn-outline" onClick={() => navigate('/submissions')} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
            View Submissions List <ArrowRight size={16} />
          </button>
        </div>

        <div style={{ width: '100%', height: 280 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={scoreDistribution}>
              <XAxis dataKey="range" stroke="var(--text-muted)" fontSize={12} />
              <YAxis stroke="var(--text-muted)" fontSize={12} allowDecimals={false} />
              <Tooltip contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: '1px solid var(--border)' }} />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {scoreDistribution.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={
                      entry.range === 'Unassessed' ? '#f59e0b' :
                        index > 4 ? 'var(--success)' :
                          index > 2 ? 'var(--primary)' :
                            'var(--primary-dark)'
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {unassessedSubs.length > 0 && (
          <div style={{ marginTop: '0.75rem', fontSize: '0.825rem', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <AlertTriangle size={15} /> Note: {unassessedSubs.length} submission(s) are currently unassessed (Pending AI Grade) and categorized in the Unassessed bar.
          </div>
        )}
      </div>

      {/* Question-by-Question Average Mark Breakdown Panel */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', backgroundColor: '#fff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h3 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Layers size={20} color="var(--primary)" /> Question-by-Question Performance Breakdown
            </h3>
            <p style={{ margin: '0.2rem 0 0 0', fontSize: '0.825rem', color: 'var(--text-muted)' }}>
              Average marks awarded per rubric subquestion across evaluated student papers.
            </p>
          </div>
          <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)', fontWeight: 600 }}>
            {questionAnalyticsList.length} Question Criteria Evaluated
          </span>
        </div>

        {questionAnalyticsList.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No question breakdown available yet. Grade submissions to view per-question analytics.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1.25rem' }}>
            {questionAnalyticsList.map((item, idx) => {
              const barColor = item.percentage >= 75 ? 'var(--success)' : item.percentage >= 50 ? 'var(--primary)' : 'var(--warning)';

              return (
                <div 
                  key={idx} 
                  style={{ 
                    padding: '1.15rem 1.25rem', 
                    border: '1px solid var(--border)', 
                    borderRadius: '10px', 
                    backgroundColor: 'var(--bg-main)',
                    display: 'flex',
                    flexDirection: 'column',
                    justify: 'space-between'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--primary-dark)' }}>{item.question_number}</span>
                    <span style={{ fontSize: '0.9rem', fontWeight: 700, color: barColor }}>
                      {item.avgScore} / {item.max_score} marks <span style={{ fontSize: '0.78rem', opacity: 0.8 }}>({item.percentage}%)</span>
                    </span>
                  </div>

                  {/* Progress Bar */}
                  <div style={{ width: '100%', height: '8px', backgroundColor: 'var(--border)', borderRadius: '4px', overflow: 'hidden', marginBottom: '0.85rem' }}>
                    <div style={{ width: `${Math.min(100, Math.max(0, item.percentage))}%`, height: '100%', backgroundColor: barColor, borderRadius: '4px', transition: 'width 0.4s ease' }} />
                  </div>

                  {/* Detailed Stats */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--text-muted)', borderTop: '1px dashed var(--border)', paddingTop: '0.55rem' }}>
                    <span>Lowest: <strong>{item.minScore}</strong></span>
                    <span>Highest: <strong>{item.maxScoreAchieved}</strong></span>
                    <span>Evaluated: <strong>{item.count} paper(s)</strong></span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
