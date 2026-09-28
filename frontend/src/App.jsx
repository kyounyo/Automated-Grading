import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AssignmentProvider } from './context/AssignmentContext';
import ErrorBoundary from './components/ErrorBoundary';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import AssignmentCreator from './pages/AssignmentCreator';
import BulkUpload from './pages/BulkUpload';
import SubmissionsList from './pages/SubmissionsList';
import GradingReview from './pages/GradingReview';
import Calibration from './pages/Calibration';

function App() {
  return (
    <ErrorBoundary>
      <AssignmentProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="create-assignment" element={<AssignmentCreator />} />
            <Route path="assignment-creator" element={<AssignmentCreator />} />
            <Route path="bulk-upload" element={<BulkUpload />} />
            <Route path="submissions" element={<SubmissionsList />} />
            <Route path="review" element={<GradingReview />} />
            <Route path="calibration" element={<Calibration />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AssignmentProvider>
  </ErrorBoundary>
  );
}

export default App;
