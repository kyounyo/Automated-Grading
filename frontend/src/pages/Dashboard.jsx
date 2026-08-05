import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, CheckCircle2, AlertTriangle, Clock, Play, ArrowRight, Sparkles, Layers } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const Dashboard = () => {
  const navigate = useNavigate();
  const { currentAssignment, submissions = [], gradeAll, loading } = useAssignment();

  const totalSubmissions = submissions.length;
  const gradedApproved = submissions.filter(s => s.status === 'graded' || s.status === 'approved').length;
  const flaggedPending = submissions.filter(s => s.status === 'flagged' || s.status === 'pending' || s.status === 'uploaded').length;

  // Separate graded submissions from unassessed submissions
  const gradedSubs = submissions.filter(s => s.score != null && (s.status === 'graded' || s.status === 'approved' || s.status === 'flagged'));
  const unassessedSubs = submissions.filter(s => s.score == null || s.status === 'pending' || s.status === 'uploaded' || s.status === 'extracting_answers' || s.status === 'retrieving_rubric' || s.status === 'grading');

  const scoreDistribution = [
    { range: 'Unassessed', count: unassessedSubs.length },
    { range: '0-50', count: gradedSubs.filter(s => s.score < 50).length },
    { range: '51-60', count: gradedSubs.filter(s => s.score >= 51 && s.score <= 60).length },
    { range: '61-70', count: gradedSubs.filter(s => s.score >= 61 && s.score <= 70).length },
    { range: '71-80', count: gradedSubs.filter(s => s.score >= 71 && s.score <= 80).length },
    { range: '81-90', count: gradedSubs.filter(s => s.score >= 81 && s.score <= 90).length },
    { range: '91-100', count: gradedSubs.filter(s => s.score >= 91 && s.score <= 100).length },
  ];

  // Class Average calculated strictly from graded papers
  const totalScoreSum = gradedSubs.reduce((acc, curr) => acc + curr.score, 0);
  const averageScore = gradedSubs.length > 0 ? Math.round(totalScoreSum / gradedSubs.length) : 0;

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Premium Header Banner */}
      <div className="glass-panel" style={{ padding: '1.5rem 2rem', background: 'linear-gradient(135deg, rgba(0, 96, 156, 0.08) 0%, rgba(16, 185, 129, 0.05) 100%)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, color: 'var(--secondary)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Sparkles size={24} color="var(--primary)" /> Evaluation Overview
          </h2>
          <p style={{ margin: '0.4rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.925rem' }}>
            Real-time assessment analytics and submission performance metrics powered by PostgreSQL & ChromaDB RAG.
          </p>
        </div>
        <button className="btn btn-primary" onClick={gradeAll} disabled={loading || totalSubmissions === 0 || unassessedSubs.length === 0} style={{ padding: '0.6rem 1.25rem' }}>
          <Play size={18} /> Grade All Pending Submissions
        </button>
      </div>

      {/* Active Assignment Info Panel */}
      <div className="glass-panel" style={{ backgroundColor: '#fff', borderLeft: '4px solid var(--primary)', padding: '1.25rem 1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: '0 0 0.4rem 0', color: 'var(--primary-dark)', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} color="var(--primary)" /> {currentAssignment?.title || 'Assignment Overview'}
          </h3>
          <p style={{ margin: 0, color: 'var(--text-main)', fontSize: '0.9rem', display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
            <span>Course Code: <strong style={{ color: 'var(--primary)' }}>{currentAssignment?.course_code || 'N/A'}</strong></span>
            <span>Due Date: <strong>{currentAssignment?.due_date || 'N/A'}</strong></span>
            <span>Class Average (Graded): <strong style={{ color: 'var(--success)' }}>{averageScore}%</strong></span>
          </p>
        </div>
        <button className="btn btn-outline" onClick={() => navigate('/assignment-creator')} style={{ fontSize: '0.85rem' }}>
          + New Assignment
        </button>
      </div>

      {/* Metric Cards Grid - 4 Organized Boxes in 1 Single Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.25rem' }}>
        {/* Card 1: Total Submissions */}
        <div className="glass-panel" style={{ padding: '1.25rem 1.5rem', borderRadius: '12px', borderTop: '4px solid var(--primary)', backgroundColor: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '125px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Total Submissions</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'var(--primary-light)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FileText size={18} color="var(--primary)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--secondary)', lineHeight: 1.1 }}>{totalSubmissions}</div>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.3rem', display: 'block' }}>Saved in PostgreSQL DB</span>
          </div>
        </div>

        {/* Card 2: Graded / Approved */}
        <div className="glass-panel" style={{ padding: '1.25rem 1.5rem', borderRadius: '12px', borderTop: '4px solid var(--success)', backgroundColor: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '125px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Graded / Approved</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(16, 185, 129, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <CheckCircle2 size={18} color="var(--success)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--success)', lineHeight: 1.1 }}>{gradedApproved}</div>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.3rem', display: 'block' }}>Ready for release</span>
          </div>
        </div>

        {/* Card 3: Flagged / Pending */}
        <div className="glass-panel" style={{ padding: '1.25rem 1.5rem', borderRadius: '12px', borderTop: '4px solid var(--warning)', backgroundColor: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '125px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Flagged / Unassessed</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(245, 158, 11, 0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <AlertTriangle size={18} color="var(--warning)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--warning)', lineHeight: 1.1 }}>{flaggedPending}</div>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.3rem', display: 'block' }}>Requires review / AI grade</span>
          </div>
        </div>

        {/* Card 4: Class Average Score */}
        <div className="glass-panel" style={{ padding: '1.25rem 1.5rem', borderRadius: '12px', borderTop: '4px solid var(--primary-dark)', backgroundColor: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '125px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Class Average</span>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: 'rgba(0, 96, 156, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Clock size={18} color="var(--primary-dark)" />
            </div>
          </div>
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ fontSize: '2.1rem', fontWeight: 800, color: 'var(--primary-dark)', lineHeight: 1.1 }}>{averageScore}%</div>
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
    </div>
  );
};

export default Dashboard;
