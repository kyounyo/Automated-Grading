import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, FileUp, Files, CheckSquare, Settings } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import './Layout.css';

const Layout = () => {
  const { currentAssignmentId, setCurrentAssignmentId, availableAssignments = [] } = useAssignment();

  return (
    <div className="layout-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar glass-panel">
        <div className="sidebar-header">
          <div className="logo-placeholder">
            <span className="logo-initial">AI</span>
          </div>
          <div>
            <h2 className="brand-name">AutoGrade+</h2>
          </div>
        </div>

        <nav className="sidebar-nav">
          <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <LayoutDashboard size={20} /> Dashboard
          </NavLink>
          <NavLink to="/assignment-creator" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <FileUp size={20} /> Create Assignment
          </NavLink>
          <NavLink to="/bulk-upload" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <Files size={20} /> Bulk Upload
          </NavLink>
          <NavLink to="/submissions" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <CheckSquare size={20} /> Submissions
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <button className="nav-item user-settings">
            <Settings size={20} /> (Lecturer's Name)
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="top-header glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            <h3 style={{ margin: 0 }}>Welcome back, (Lecturer's Name)</h3>
            <div style={{ height: '24px', width: '1px', backgroundColor: 'var(--border)' }}></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', background: 'var(--primary-light)', padding: '0.25rem 0.5rem', borderRadius: '8px' }}>
              <span style={{ fontSize: '0.875rem', color: 'var(--primary-dark)', fontWeight: 600 }}>Assignment Context:</span>
              <select
                className="input-field"
                style={{ padding: '0.4rem 2.5rem 0.4rem 1rem', width: '280px', backgroundColor: '#fff', cursor: 'pointer', appearance: 'auto', border: '2px solid var(--primary)', fontWeight: 'bold', color: 'var(--primary-dark)', boxShadow: 'var(--shadow-sm)' }}
                value={currentAssignmentId}
                onChange={(e) => setCurrentAssignmentId(e.target.value)}
              >
                {(availableAssignments || []).map(assignment => (
                  <option key={assignment.id} value={assignment.id}>{assignment.title}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="status-badge">
            <span className="status-dot"></span> Azure Copilot Active
          </div>
        </header>

        <div className="page-content animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
