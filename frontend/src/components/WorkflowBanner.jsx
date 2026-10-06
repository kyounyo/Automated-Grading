import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { CheckCircle2, ChevronRight } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const WorkflowBanner = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentAssignment } = useAssignment();

  const hasCalibration = Boolean(currentAssignment?.calibration_enabled);

  const steps = [
    { label: 'Create Assignment', path: '/create-assignment', alt: '/assignment-creator' },
    { label: 'Submissions Upload', path: '/bulk-upload' },
    ...(hasCalibration ? [{ label: 'Calibration', path: '/calibration' }] : []),
    { label: 'Submissions List', path: '/submissions' },
  ];

  const activeIdx = steps.findIndex(
    s => location.pathname === s.path || location.pathname === s.alt
  );

  // Only show on workflow pages
  if (activeIdx === -1) return null;

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 0,
      marginBottom: '1.35rem',
      backgroundColor: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: '10px',
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {steps.map((step, i) => {
        const isDone = i < activeIdx;
        const isActive = i === activeIdx;
        const isFuture = i > activeIdx;

        return (
          <React.Fragment key={i}>
            <button
              onClick={() => navigate(step.path)}
              style={{
                flex: 1,
                padding: '0.65rem 0.85rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                background: isActive
                  ? 'linear-gradient(135deg, var(--primary-light) 0%, #EFF6FF 100%)'
                  : isDone ? '#F0FDF4' : 'transparent',
                border: 'none',
                borderBottom: isActive
                  ? '2.5px solid var(--primary)'
                  : '2.5px solid transparent',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                textAlign: 'left',
                minWidth: 0,
              }}
              onMouseEnter={e => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = isDone ? '#E2FBE8' : 'var(--bg-hover)';
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = isDone ? '#F0FDF4' : 'transparent';
                }
              }}
            >
              {/* Step number / check */}
              <div style={{
                width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                backgroundColor: isDone
                  ? '#16A34A'
                  : isActive ? 'var(--primary)' : 'var(--bg-hover)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {isDone ? (
                  <CheckCircle2 size={13} color="#fff" />
                ) : (
                  <span style={{ fontSize: '0.7rem', fontWeight: 800, color: isActive ? '#fff' : 'var(--text-muted)' }}>{i + 1}</span>
                )}
              </div>

              <span style={{
                fontSize: '0.8rem',
                fontWeight: isActive ? 700 : 600,
                color: isDone
                  ? '#15803D'
                  : isActive ? 'var(--primary-dark)' : isFuture ? 'var(--text-muted)' : 'var(--text-main)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {step.label}
              </span>
            </button>

            {i < steps.length - 1 && (
              <ChevronRight
                size={14}
                color="var(--border)"
                style={{ flexShrink: 0 }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export default WorkflowBanner;
