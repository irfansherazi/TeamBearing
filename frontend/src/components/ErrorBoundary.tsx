import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Standard React Error Boundary (Class Component)
 * React 19+ still requires class components for Error Boundaries.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    // Update state so the next render will show the fallback UI.
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // You can also log the error to an error reporting service
    console.error("Uncaught error in ErrorBoundary:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary-fallback">
          <div className="error-boundary-content">
            <span className="error-boundary-icon">⚠️</span>
            <h2 className="error-boundary-title">Something went wrong</h2>
            <p className="error-boundary-message">
              The application encountered an unexpected runtime error.
            </p>
            {this.state.error && (
              <pre className="error-boundary-stack">
                {this.state.error.message}
              </pre>
            )}
            <button
              className="error-boundary-retry-btn"
              onClick={this.handleReset}
            >
              🔄 Refresh Component
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
