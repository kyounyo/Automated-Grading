import React from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FileUp, Files, CheckSquare, Sparkles, BookOpen, ChevronDown, PlusCircle, Target } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import HelpSidebar from './HelpSidebar';
import GradingProgressBar from './GradingProgressBar';
import WorkflowBanner from './WorkflowBanner';
import './Layout.css';

const Layout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentAssignmentId, setCurrentAssignmentId, assignments = [], submissions = [], isGradingActive, currentAssignment, isAssignmentCreationPending } = useAssignment();

  const isStep1Incomplete = Boolean(isAssignmentCreationPending || !currentAssignmentId || assignments.length === 0);

  const availableAssignments = assignments.length > 0 ? assignments : [
    { id: '', title: 'No Active Assignments' }
  ];

  return (
    <div className="layout-container">
      {/* Docked Left Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo-badge">
            <span>AG+</span>
          </div>
          <div className="brand-text">
            <span className="brand-title">AutoGrade+</span>
            <span className="brand-tag">Academic Assessment</span>
          </div>
        </div>

        <div className="sidebar-content">
          {/* Section 1: Overview */}
          <div className="nav-section">
            <span className="nav-section-title">Overview</span>
            <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <LayoutDashboard size={18} /> Dashboard
            </NavLink>
          </div>

          {/* Section 2: Assessment Workflow (Dynamic Steps) */}
          <div className="nav-section">
            <span className="nav-section-title">Assessment Workflow</span>
            <NavLink
              to="/create-assignment"
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              style={({ isActive }) => (isStep1Incomplete && !isActive) ? {
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                color: '#DC2626'
              } : {}}
            >
              <div
                className="step-badge"
                style={isStep1Incomplete && location.pathname !== '/create-assignment' ? {
                  backgroundColor: '#DC2626',
                  color: '#fff',
                  fontWeight: 800
                } : {}}
              >
                {isStep1Incomplete && location.pathname !== '/create-assignment' ? '!' : '1'}
              </div>
              <span>Create Assignment</span>
              {isStep1Incomplete && location.pathname !== '/create-assignment' && (
                <span style={{
                  fontSize: '0.68rem',
                  backgroundColor: '#FEE2E2',
                  color: '#DC2626',
                  padding: '0.1rem 0.4rem',
                  borderRadius: '4px',
                  marginLeft: 'auto',
                  fontWeight: 700
                }}>
                  Incomplete
                </span>
              )}
            </NavLink>
            <NavLink to="/bulk-upload" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <div className="step-badge">2</div> Submissions Upload
            </NavLink>
            {currentAssignment?.calibration_enabled && (
              <NavLink to="/calibration" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <div className="step-badge">3</div> Calibration
              </NavLink>
            )}
            <NavLink to="/submissions" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <div className="step-badge">{currentAssignment?.calibration_enabled ? '4' : '3'}</div> Submissions List
            </NavLink>
          </div>

          {/* Section 3: Evaluation Studio */}
          <div className="nav-section">
            <span className="nav-section-title">Evaluation</span>
            <NavLink to="/review" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <CheckSquare size={18} /> Grading & Review
            </NavLink>
          </div>
        </div>
      </aside>

      {/* Main Workspace Area */}
      <main className="main-content">
        {/* Luminous High-Class Top Navigation Glide Bar */}
        <div key={`progress-${location.pathname}`} className="route-progress-bar" />

        {/* Top Header */}
        <header className="top-header">
          {/* Group: Assessment Dropdown + New Button RIGHT BESIDE IT */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <div className="active-assignment-pill">
              <div className="assignment-badge-icon">
                <BookOpen size={16} color="var(--primary)" />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span className="assignment-label">Current Assessment</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <select
                    className="assignment-select"
                    value={currentAssignmentId}
                    onChange={(e) => setCurrentAssignmentId(e.target.value)}
                  >
                    {availableAssignments.map(assignment => (
                      <option key={assignment.id} value={assignment.id}>
                        {assignment.course_code ? `${assignment.course_code}: ` : ''}{assignment.title}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={14} color="var(--primary)" style={{ pointerEvents: 'none' }} />
                </div>
              </div>
            </div>

            {/* + New Button located right beside current assessment box */}
            <button
              onClick={() => navigate('/create-assignment')}
              title="Create a new assignment"
              className="new-assignment-btn"
            >
              <PlusCircle size={16} />
              <span>New</span>
            </button>
          </div>
        </header>

        {/* Page View Body with Luxury Smooth Transition */}
        <div className="page-content">
          <WorkflowBanner />
          <div key={location.pathname} className="route-page-transition">
            <Outlet />
          </div>
        </div>
      </main>

      {/* Global: Contextual Help Sidebar (visible on all pages) */}
      <HelpSidebar />

      {/* Global: Live Grading Progress Bar */}
      <GradingProgressBar submissions={submissions} isGrading={isGradingActive} />
    </div>
  );
};

export default Layout;

