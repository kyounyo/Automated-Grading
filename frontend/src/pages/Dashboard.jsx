import React from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { AlertTriangle, CheckCircle, AlertCircle, ShieldCheck, FileText } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import './Dashboard.css';

const Dashboard = () => {
  const navigate = useNavigate();
  const { currentData } = useAssignment();
  const { metrics, chartData } = currentData;

  // Compute average marks for each question
  const questionAverages = [];
  if (currentData.questions && currentData.students) {
    const questionScores = {};
    currentData.questions.forEach(q => {
      questionScores[q.id] = { totalScore: 0, count: 0, maxScore: 0, title: q.text };
    });

    currentData.students.forEach(student => {
      student.evaluations.forEach(evalData => {
        if (questionScores[evalData.qId]) {
          const scoreParts = evalData.aiScore.split('/');
          const score = parseFloat(scoreParts[0].trim());
          const max = parseFloat(scoreParts[1].trim());
          if (!isNaN(score)) {
            questionScores[evalData.qId].totalScore += score;
            questionScores[evalData.qId].count += 1;
            questionScores[evalData.qId].maxScore = max;
          }
        }
      });
    });

    Object.keys(questionScores).forEach(qId => {
      const qs = questionScores[qId];
      if (qs.count > 0) {
        questionAverages.push({
          qId,
          title: qs.title,
          averageScore: (qs.totalScore / qs.count).toFixed(1),
          maxScore: qs.maxScore,
          percentage: Math.round((qs.totalScore / qs.count) / qs.maxScore * 100)
        });
      }
    });
  }

  return (
    <div className="dashboard-container">

      {/* Call to Action Banner */}
      {metrics.actionRequired > 0 && (
        <div className="glass-panel" style={{ marginBottom: '1.5rem', backgroundColor: 'rgba(245, 158, 11, 0.05)', borderLeft: '4px solid var(--warning)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem 1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <AlertTriangle size={24} color="var(--warning)" />
            <div>
              <h3 style={{ margin: 0, color: 'var(--warning)', fontSize: '1.1rem' }}>Action Required</h3>
              <p style={{ margin: '0.2rem 0 0 0', fontSize: '0.9rem', color: 'var(--text-main)' }}>{metrics.actionRequired} submissions require your manual review (Conflicts, Borderline Grades, Low Confidence).</p>
            </div>
          </div>
          <button className="btn btn-primary" onClick={() => navigate('/submissions')} style={{ backgroundColor: 'var(--warning)', color: '#fff', border: 'none', padding: '0.5rem 1rem' }}>Review Flagged</button>
        </div>
      )}

      {/* Assignment Overall Feedback */}
      {currentData.overallFeedback && (
        <div className="glass-panel" style={{ marginBottom: '1.5rem', backgroundColor: 'var(--primary-light)', borderLeft: '4px solid var(--primary)', padding: '1.25rem 1.5rem' }}>
          <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--primary-dark)', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={20} /> Overall Class Feedback
          </h3>
          <p style={{ margin: 0, color: 'var(--text-main)', fontSize: '0.95rem', lineHeight: '1.5' }}>
            {currentData.overallFeedback}
          </p>
        </div>
      )}

      <div className="metrics-grid">
        <div className="metric-card glass-panel" style={{ borderTop: '4px solid var(--border)' }}>
          <div className="flex-between"><p className="label">Total Submissions</p> <FileText size={18} color="var(--text-muted)" /></div>
          <h2>{metrics.total}</h2>
          <span className="trend neutral">100% processed</span>
        </div>
        <div className="metric-card glass-panel" style={{ borderTop: '4px solid var(--success)' }}>
          <div className="flex-between"><p className="label">Auto-Approved</p> <CheckCircle size={18} color="var(--success)" /></div>
          <h2>{metrics.autoApproved}</h2>
          <span className="trend positive">High Confidence</span>
        </div>
        <div className="metric-card glass-panel" style={{ borderTop: '4px solid var(--warning)' }}>
          <div className="flex-between"><p className="label">Action Required</p> <AlertCircle size={18} color="var(--warning)" /></div>
          <h2>{metrics.actionRequired}</h2>
          <span className="trend negative">Pending Review</span>
        </div>
        <div className="metric-card glass-panel" style={{ borderTop: '4px solid var(--primary)' }}>
          <div className="flex-between"><p className="label">Random Audit</p> <ShieldCheck size={18} color="var(--primary)" /></div>
          <h2>{metrics.randomAudit}</h2>
          <span className="trend neutral">papers selected</span>
        </div>
      </div>

      <div className="charts-section" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))' }}>
        <div className="chart-card glass-panel">
          <h3 style={{ marginBottom: '1.5rem', color: 'var(--secondary)' }}>Mark Distribution for Current Assignment</h3>
          <div className="chart-wrapper" style={{ height: '300px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis dataKey="range" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)' }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)' }} />
                <Tooltip
                  cursor={{ fill: 'var(--primary-light)' }}
                  contentStyle={{ borderRadius: '8px', border: '1px solid var(--border)', boxShadow: 'var(--shadow-md)' }}
                />
                <Bar dataKey="count" fill="var(--primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="chart-card glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginBottom: '1.5rem', color: 'var(--secondary)' }}>Average Marks by Question</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', flex: 1, overflowY: 'auto' }}>
            {questionAverages.map((qa) => (
              <div key={qa.qId} style={{ background: 'var(--bg-main)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                  <h4 style={{ margin: 0, fontSize: '0.95rem', color: 'var(--text-main)', flex: 1, paddingRight: '1rem' }}>
                    {qa.title.length > 60 ? qa.title.substring(0, 60) + '...' : qa.title}
                  </h4>
                  <span style={{ fontWeight: 600, color: 'var(--primary)', whiteSpace: 'nowrap' }}>
                    {qa.averageScore} / {qa.maxScore}
                  </span>
                </div>
                <div style={{ height: '8px', background: 'var(--border)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      background: 'var(--primary)',
                      width: `${qa.percentage}%`,
                      borderRadius: '4px'
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
