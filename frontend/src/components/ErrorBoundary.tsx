import React from 'react';

interface ErrorBoundaryProps {
    children: React.ReactNode;
    /** When this changes the boundary clears its error — e.g. the route, so leaving a broken page recovers. */
    resetKey?: unknown;
    /** What the failure is called on screen: "This page", "The application". */
    scope?: string;
}

interface ErrorBoundaryState {
    error: Error | null;
}

/**
 * Catches a render error below it and shows a message in its place (FE-01).
 *
 * In React 18 an uncaught render error unmounts the whole tree: one bad field in
 * one API response left a blank white page and no way back but a reload, which
 * reproduced it. With a boundary around the router and another around each
 * page, a broken page breaks only itself and the sidebar stays usable.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
    state: ErrorBoundaryState = { error: null };

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo): void {
        console.error(`${this.props.scope ?? 'A component'} failed to render:`, error, info.componentStack);
    }

    componentDidUpdate(prev: ErrorBoundaryProps): void {
        if (this.state.error && prev.resetKey !== this.props.resetKey) {
            this.setState({ error: null });
        }
    }

    private reset = () => this.setState({ error: null });

    render() {
        const { error } = this.state;
        if (!error) return this.props.children;
        return (
            <div role="alert" className="error-boundary">
                <h2>{this.props.scope ?? 'This page'} hit an error and could not be shown.</h2>
                <p className="error-boundary-message">{error.message || String(error)}</p>
                <div className="error-boundary-actions">
                    <button className="btn-secondary" onClick={this.reset}>Try again</button>
                    <button className="btn-secondary" onClick={() => window.location.reload()}>Reload</button>
                </div>
            </div>
        );
    }
}
