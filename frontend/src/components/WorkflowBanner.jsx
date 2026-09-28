import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { CheckCircle2, ChevronRight, AlertTriangle } from 'lucide-react';
import { useAssignment } from '../context/AssignmentContext';

const WorkflowBanner = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentAssignment, currentAssignmentId, assignments = [], isAssignmentCreationPending } = useAssignment();

  const hasCalibration = Boolean(currentAssignment?.calibration_enabled);
  const isStep1Incomplete = Boolean(isAssignmentCreationPending || !currentAssignmentId || assignments.length === 0);

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
      border: isStep1Incomplete && activeIdx > 0 ? '1px solid #FCA5A5' : '1px solid var(--border)',
      borderRadius: '10px',
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {steps.map((step, i) => {
        const isStep1 = i === 0;
        const isIncomplete = isStep1 && isStep1Incomplete && activeIdx > 0;
        const isDone = i < activeIdx && !isIncomplete;
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
                  : isIncomplete
                    ? '#FEF2F2'
                    : isDone ? '#F0FDF4' : 'transparent',
                border: 'none',
                borderBottom: isActive
                  ? '2.5px solid var(--primary)'
                  : isIncomplete
                    ? '2.5px solid #EF4444'
                    : '2.5px solid transparent',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                textAlign: 'left',
                minWidth: 0,
              }}
              onMouseEnter={e => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = isIncomplete ? '#FEE2E2' : 'var(--bg-hover)';
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = isIncomplete
                    ? '#FEF2F2'
                    : isDone ? '#F0FDF4' : 'transparent';
                }
              }}
              title={isIncomplete ? 'Step 1 Incomplete: No new assignment was created. Click to return and finish creation.' : ''}
            >
              {/* Step number / check / alert */}
              <div style={{
                width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                backgroundColor: isIncomplete
                  ? '#DC2626'
                  : isDone
                    ? '#16A34A'
                    : isActive ? 'var(--primary)' : 'var(--bg-hover)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {isIncomplete ? (
                  <AlertTriangle size={12} color="#fff" />
                ) : isDone ? (
                  <CheckCircle2 size={13} color="#fff" />
                ) : (
                  <span style={{ fontSize: '0.7rem', fontWeight: 800, color: isActive ? '#fff' : 'var(--text-muted)' }}>{i + 1}</span>
                )}
              </div>

              <span style={{
                fontSize: '0.8rem',
                fontWeight: isActive || isIncomplete ? 700 : 600,
                color: isIncomplete
                  ? '#DC2626'
                  : isDone
                    ? '#15803D'
                    : isActive ? 'var(--primary-dark)' : isFuture ? 'var(--text-muted)' : 'var(--text-main)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {isIncomplete ? 'Create Assignment (Incomplete)' : step.label}
              </span>
            </button>

            {i < steps.length - 1 && (
              <ChevronRight
                size={14}
                color={isIncomplete ? '#FCA5A5' : 'var(--border)'}
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
