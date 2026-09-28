import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('UI Render Error caught by ErrorBoundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ maxWidth: 600, margin: '4rem auto', padding: '2rem', textAlign: 'center', backgroundColor: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: '10px' }}>
          <AlertTriangle size={42} color="#DC2626" style={{ marginBottom: '1rem' }} />
          <h3 style={{ margin: '0 0 0.5rem', color: '#991B1B' }}>Something went wrong displaying this view</h3>
          <p style={{ fontSize: '0.85rem', color: '#B91C1C', marginBottom: '1.25rem' }}>
            {this.state.error?.message || 'An unexpected rendering error occurred.'}
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            style={{ backgroundColor: '#DC2626', borderColor: '#DC2626', display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <RefreshCw size={14} /> Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
