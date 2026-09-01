import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, CheckCircle2, AlertTriangle, Play, ArrowRight, Layers, Download, Calendar, Users, Award, ShieldAlert, TrendingUp } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';

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
    { range: `0 - ${fmt(b1)} marks`, count: gradedSubs.filter(s => s.score <= b1).length },
    { range: `${fmt(b1 + 0.1)} - ${fmt(b2)} marks`, count: gradedSubs.filter(s => s.score > b1 && s.score <= b2).length },
    { range: `${fmt(b2 + 0.1)} - ${fmt(b3)} marks`, count: gradedSubs.filter(s => s.score > b2 && s.score <= b3).length },
    { range: `${fmt(b3 + 0.1)} - ${fmt(maxMark)} marks`, count: gradedSubs.filter(s => s.score > b3).length },
  ];

  // Class Average calculated strictly from graded papers
  const totalScoreSum = gradedSubs.reduce((acc, curr) => acc + curr.score, 0);
  const averageScore = gradedSubs.length > 0 ? (totalScoreSum / gradedSubs.length).toFixed(1) : '0.0';

  // Extract Whole Question Breakdown Analytics
  const getParentQuestionKey = (qNum) => {
    if (!qNum) return 'Q1';
    const match = String(qNum).match(/(?:Question\s*|Q)?\s*(\d+)/i);
    return match ? `Q${match[1]}` : String(qNum);
  };

  const parentQuestionMap = {};

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
    <div style={{ maxWidth: '1240px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* 1. Header Section */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1.25rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.35rem' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
              Evaluation Analytics
            </span>
            {currentAssignment?.course_code && (
              <span style={{ backgroundColor: 'var(--primary-light)', color: 'var(--primary-dark)', fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.55rem', borderRadius: '4px', border: '1px solid var(--border)' }}>
                {currentAssignment.course_code}
              </span>
            )}
          </div>
          <h1 style={{ fontSize: '1.65rem', fontWeight: 800, color: 'var(--secondary)', letterSpacing: '-0.02em', margin: 0 }}>
            {currentAssignment?.title || 'No Active Assignment'}
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', marginTop: '0.35rem', color: 'var(--text-muted)', fontSize: '0.825rem' }}>
            {currentAssignment?.due_date && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                <Calendar size={14} color="var(--primary)" /> Due Date: <strong style={{ color: 'var(--text-main)' }}>{currentAssignment.due_date}</strong>
              </span>
            )}
            <span>Total Papers: <strong style={{ color: 'var(--text-main)' }}>{totalSubmissions}</strong></span>
            {totalRubricMax && <span>Total Marks: <strong style={{ color: 'var(--text-main)' }}>{totalRubricMax} marks</strong></span>}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
          <button
            className="btn btn-outline"
            onClick={onExportCSVClick}
            disabled={totalSubmissions === 0}
            style={{ fontSize: '0.825rem' }}
          >
            <Download size={14} color="var(--primary)" /> Export CSV
          </button>
          <button
            className="btn btn-primary"
            onClick={gradeAll}
            disabled={loading || totalSubmissions === 0 || unassessedSubs.length === 0}
            style={{ fontSize: '0.825rem' }}
          >
            <Play size={14} /> Grade All Pending ({unassessedSubs.length})
          </button>
        </div>
      </div>

      {/* 2. Soft Blue Minimalist Metric Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.15rem' }}>

        {/* Card 1: Total Submissions (Crisp Sky Blue - distinct from panel) */}
        <div
          onClick={() => navigate('/submissions', { state: { filter: 'all' } })}
          className="card-panel"
          style={{
            padding: '1.2rem 1.35rem',
            cursor: 'pointer',
            backgroundColor: '#E0F2FE',
            borderColor: '#BAE6FD',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            minHeight: '125px'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#0369A1' }}>
              Total Submissions
            </span>
            <div style={{ width: '30px', height: '30px', borderRadius: '6px', backgroundColor: '#FFFFFF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Users size={15} color="#0284C7" />
            </div>
          </div>
          <div style={{ margin: '0.25rem 0' }}>
            <div style={{ fontSize: '1.85rem', fontWeight: 800, color: '#0369A1', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              {totalSubmissions}
            </div>
          </div>
          <span style={{ fontSize: '0.775rem', color: '#0284C7', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
            Browse All Papers <ArrowRight size={12} color="#0284C7" />
          </span>
        </div>

        {/* Card 2: Graded & Approved (Soft Mint Emerald) */}
        <div
          onClick={() => navigate('/submissions', { state: { filter: 'graded' } })}
          className="card-panel"
          style={{
            padding: '1.2rem 1.35rem',
            cursor: 'pointer',
            backgroundColor: '#EAF7EE',
            borderColor: '#A7E0B9',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            minHeight: '125px'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#16A34A' }}>
              Graded & Approved
            </span>
            <div style={{ width: '30px', height: '30px', borderRadius: '6px', backgroundColor: '#FFFFFF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Award size={15} color="#16A34A" />
            </div>
          </div>
          <div style={{ margin: '0.25rem 0' }}>
            <div style={{ fontSize: '1.85rem', fontWeight: 800, color: '#16A34A', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              {gradedApproved}
            </div>
          </div>
          <span style={{ fontSize: '0.775rem', color: '#16A34A', fontWeight: 600 }}>
            {totalSubmissions > 0 ? `${Math.round((gradedApproved / totalSubmissions) * 100)}% evaluated` : '0%'}
          </span>
        </div>

        {/* Card 3: Flagged for Review (Soft Warm Amber) */}
        <div
          onClick={() => navigate('/submissions', { state: { filter: 'flagged' } })}
          className="card-panel"
          style={{
            padding: '1.2rem 1.35rem',
            cursor: 'pointer',
            backgroundColor: '#FEF6E8',
            borderColor: '#FAD494',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            minHeight: '125px'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#D97706' }}>
              Flagged for Audit
            </span>
            <div style={{ width: '30px', height: '30px', borderRadius: '6px', backgroundColor: '#FFFFFF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ShieldAlert size={15} color="#D97706" />
            </div>
          </div>
          <div style={{ margin: '0.25rem 0' }}>
            <div style={{ fontSize: '1.85rem', fontWeight: 800, color: '#D97706', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              {flaggedCount}
            </div>
          </div>
          <span style={{ fontSize: '0.775rem', color: '#D97706', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
            {flaggedCount > 0 ? <>Review Flagged Papers <ArrowRight size={12} /></> : 'All papers clear'}
          </span>
        </div>

        {/* Card 4: Class Average (Light Blush Pink) */}
        <div
          className="card-panel"
          style={{
            padding: '1.2rem 1.35rem',
            backgroundColor: '#FAF0F6',
            borderColor: '#E8D4E2',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            minHeight: '125px'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#91215B' }}>
              Class Average
            </span>
            <div style={{ width: '30px', height: '30px', borderRadius: '6px', backgroundColor: '#FFFFFF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <TrendingUp size={15} color="#91215B" />
            </div>
          </div>
          <div style={{ margin: '0.25rem 0' }}>
            <div style={{ fontSize: '1.85rem', fontWeight: 800, color: '#4A102E', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              {gradedSubs.length > 0 ? averageScore : '—'}
              {totalRubricMax && <span style={{ fontSize: '1.05rem', fontWeight: 600, color: '#91215B', marginLeft: '0.25rem' }}>/ {totalRubricMax}</span>}
            </div>
          </div>
          <span style={{ fontSize: '0.775rem', color: '#91215B', fontWeight: 600 }}>
            From {gradedSubs.length} graded paper(s)
          </span>
        </div>

      </div>

      {/* 3. Side-by-Side Analytics */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr', gap: '1.25rem', alignItems: 'stretch' }}>

        {/* Left Column: Score Distribution Chart */}
        <div
          className="card-panel"
          style={{
            padding: '1.5rem 1.75rem',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: 'var(--secondary)' }}>
                  Cohort Score Distribution
                </h3>
                <p style={{ margin: '0.2rem 0 0 0', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Student score frequency distribution across rubric mark brackets.
                </p>
              </div>
              <button
                className="btn btn-outline"
                onClick={() => navigate('/submissions')}
                style={{ fontSize: '0.75rem', padding: '0.3rem 0.65rem' }}
              >
                Submissions Table <ArrowRight size={12} />
              </button>
            </div>

            {/* Soft Blue Bar Chart Area */}
            <div style={{ width: '100%', height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={scoreDistribution} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-light)" />
                  <XAxis dataKey="range" stroke="var(--text-muted)" fontSize={11} fontWeight={500} tickLine={false} axisLine={{ stroke: 'var(--border)' }} />
                  <YAxis stroke="var(--text-muted)" fontSize={11} fontWeight={500} allowDecimals={false} tickLine={false} axisLine={{ stroke: 'var(--border)' }} />
                  <Tooltip
                    cursor={{ fill: 'rgba(217, 236, 250, 0.6)' }}
                    contentStyle={{
                      backgroundColor: 'var(--surface)',
                      borderRadius: '6px',
                      border: '1px solid var(--border)',
                      boxShadow: 'none',
                      fontFamily: 'var(--font-main)',
                      fontSize: '0.825rem',
                      fontWeight: 600,
                      color: 'var(--text-main)'
                    }}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48}>
                    {scoreDistribution.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={
                          entry.range === 'Unassessed' ? '#CBD5E1' :
                            index > 4 ? '#16A34A' :
                              index > 2 ? '#3B82C4' :
                                '#1E4E73'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {unassessedSubs.length > 0 && (
            <div style={{ marginTop: '1rem', padding: '0.55rem 0.85rem', backgroundColor: 'var(--primary-light)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.8rem', color: 'var(--primary-dark)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              <AlertTriangle size={14} color="var(--primary)" /> {unassessedSubs.length} submission(s) are awaiting AI grading.
            </div>
          )}
        </div>

        {/* Right Column: Question Performance Breakdown */}
        <div
          className="card-panel"
          style={{
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: 'var(--secondary)' }}>
                  Question Performance
                </h3>
                <p style={{ margin: '0.15rem 0 0 0', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Mean marks awarded per rubric item.
                </p>
              </div>
              <span style={{ fontSize: '0.725rem', color: 'var(--primary-dark)', backgroundColor: 'var(--primary-light)', padding: '0.15rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border)', fontWeight: 600 }}>
                {questionAnalyticsList.length} Criteria
              </span>
            </div>

            {questionAnalyticsList.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontStyle: 'italic', margin: '3rem 0', textAlign: 'center', fontSize: '0.85rem' }}>
                No question breakdown available yet. Grade submissions to view analytics.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', maxHeight: '290px', overflowY: 'auto', paddingRight: '0.2rem' }}>
                {questionAnalyticsList.map((item, idx) => {
                  const barColor = item.percentage >= 75 ? '#16A34A' : item.percentage >= 50 ? '#3B82C4' : '#D97706';

                  return (
                    <div
                      key={idx}
                      className="card-secondary"
                      style={{
                        padding: '0.75rem 0.9rem',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.4rem'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
                          <span style={{ fontSize: '0.875rem', fontWeight: 800, color: 'var(--secondary)', minWidth: '34px' }}>{item.question_number}</span>
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Avg: <strong style={{ color: 'var(--text-main)' }}>{item.avgScore} / {item.max_score} marks</strong></span>
                        </div>
                        <span style={{ fontSize: '0.775rem', fontWeight: 700, color: barColor }}>
                          {item.percentage}%
                        </span>
                      </div>

                      {/* Progress Bar */}
                      <div style={{ width: '100%', height: '5px', backgroundColor: '#C9DCEB', borderRadius: '2.5px', overflow: 'hidden' }}>
                        <div style={{ width: `${Math.min(100, Math.max(0, item.percentage))}%`, height: '100%', backgroundColor: barColor, borderRadius: '2.5px', transition: 'width 0.4s ease' }} />
                      </div>

                      <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        <span>Min: <strong style={{ color: 'var(--text-main)' }}>{item.minScore}</strong></span>
                        <span>Max: <strong style={{ color: 'var(--text-main)' }}>{item.maxScoreAchieved}</strong></span>
                        <span>Evaluated: <strong style={{ color: 'var(--text-main)' }}>{item.count} paper(s)</strong></span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

      </div>

    </div>
  );
};

export default Dashboard;
