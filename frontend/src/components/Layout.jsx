import React, { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, FileUp, Files, CheckSquare, Database } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';
import VectorStoreModal from './VectorStoreModal';
import './Layout.css';

const Layout = () => {
  const { currentAssignmentId, setCurrentAssignmentId, assignments = [] } = useAssignment();
  const [isVectorModalOpen, setIsVectorModalOpen] = useState(false);

  const availableAssignments = assignments.length > 0 ? assignments : [
    { id: '', title: 'No Active Assignments' }
  ];

  return (
    <div className="layout-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar glass-panel">
        <div className="sidebar-header">
          <div className="logo-placeholder" style={{ background: 'linear-gradient(135deg, #00609c, #10b981)', color: '#fff' }}>
            <span className="logo-initial">AG+</span>
          </div>
          <div>
            <h2 className="brand-name">AutoGrade+</h2>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>AI Grading Platform</div>
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
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="top-header glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', background: 'var(--primary-light)', padding: '0.35rem 0.85rem', borderRadius: '8px' }}>
            <span style={{ fontSize: '0.875rem', color: 'var(--primary-dark)', fontWeight: 600 }}>Active Assignment:</span>
            <select
              className="input-field"
              style={{ padding: '0.4rem 1rem', width: '320px', backgroundColor: '#fff', cursor: 'pointer', border: '1.5px solid var(--primary)', fontWeight: '600', color: 'var(--primary-dark)', borderRadius: '6px' }}
              value={currentAssignmentId}
              onChange={(e) => setCurrentAssignmentId(e.target.value)}
            >
              {availableAssignments.map(assignment => (
                <option key={assignment.id} value={assignment.id}>
                  {assignment.course_code ? `${assignment.course_code}: ` : ''}{assignment.title}
                </option>
              ))}
            </select>
          </div>

          <button
            className="btn btn-outline"
            onClick={() => setIsVectorModalOpen(true)}
            disabled={!currentAssignmentId}
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem', padding: '0.45rem 1rem' }}
          >
            <Database size={16} color="var(--primary)" /> View Vector Embeddings
          </button>
        </header>

        <div className="page-content animate-fade-in">
          <Outlet />
        </div>

        <VectorStoreModal
          assignmentId={currentAssignmentId}
          isOpen={isVectorModalOpen}
          onClose={() => setIsVectorModalOpen(false)}
        />
      </main>
    </div>
  );
};

export default Layout;
