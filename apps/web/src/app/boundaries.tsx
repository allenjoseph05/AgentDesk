import { Component, type ErrorInfo, type ReactNode } from "react";

interface ApplicationErrorBoundaryProps {
  children: ReactNode;
}

interface ApplicationErrorBoundaryState {
  error: Error | null;
}

export class ApplicationErrorBoundary extends Component<
  ApplicationErrorBoundaryProps,
  ApplicationErrorBoundaryState
> {
  state: ApplicationErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ApplicationErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("AgentDesk render boundary caught an error.", error, info);
  }

  render() {
    if (this.state.error !== null) {
      return (
        <main className="boundary-page" role="alert">
          <div className="boundary-card">
            <span className="brand-mark" aria-hidden="true">
              AD
            </span>
            <p className="eyebrow">Workspace interrupted</p>
            <h1>AgentDesk could not render this view.</h1>
            <p>{this.state.error.message}</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload workspace
            </button>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

export function ShellLoadingFallback() {
  return (
    <main className="boundary-page" aria-busy="true" aria-live="polite">
      <div className="loading-shell">
        <span className="brand-mark" aria-hidden="true">
          AD
        </span>
        <div>
          <p className="eyebrow">AgentDesk</p>
          <p className="loading-label">Preparing your research workspace...</p>
        </div>
        <span className="loading-indicator" aria-hidden="true" />
      </div>
    </main>
  );
}
