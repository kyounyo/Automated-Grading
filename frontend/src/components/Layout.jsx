import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, FileUp, Files, CheckSquare, Sparkles, BookOpen, ChevronDown } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import './Layout.css';

const Layout = () => {
  const { currentAssignmentId, setCurrentAssignmentId, assignments = [] } = useAssignment();

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

          {/* Section 2: Assessment Workflow */}
          <div className="nav-section">
            <span className="nav-section-title">Assessment Setup</span>
            <NavLink to="/create-assignment" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Sparkles size={18} /> Create Assignment
            </NavLink>
            <NavLink to="/bulk-upload" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <FileUp size={18} /> Submissions Upload
            </NavLink>
          </div>

          {/* Section 3: Evaluation */}
          <div className="nav-section">
            <span className="nav-section-title">Grading & Review</span>
            <NavLink to="/submissions" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Files size={18} /> Submissions List
            </NavLink>
            <NavLink to="/review" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <CheckSquare size={18} /> Grading & Review
            </NavLink>
          </div>
        </div>

        {/* Sidebar Footer: Status */}
        <div className="sidebar-footer">
          <div className="system-status-indicator">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              <span className="status-dot online"></span> AI Models Ready
            </span>
            <span style={{ fontSize: '0.675rem', opacity: 0.75, fontWeight: 500 }}>v2.4.0</span>
          </div>
        </div>
      </aside>

      {/* Main Workspace Area */}
      <main className="main-content">
        {/* Top Header */}
        <header className="top-header">
          {/* Aesthetic Blue Assignment Selector */}
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
        </header>

        {/* Page View Body */}
        <div className="page-content animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
