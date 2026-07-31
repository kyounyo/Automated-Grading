import React from 'react';
import { useAssignment } from '../context/AssignmentContext';

const GradingReview = () => {
  const { currentData } = useAssignment();
  
  return (
    <div className="glass-panel" style={{ padding: '2rem' }}>
      <h2>Grading Review</h2>
      <p>Review individual student grades here.</p>
    </div>
  );
};

export default GradingReview;
