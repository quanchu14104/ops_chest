import { Component, type ReactNode } from "react";

type State = { error: Error | null };

export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="alert error">
          <b>Trang gặp lỗi hiển thị.</b> {this.state.error.message}
          <div style={{ marginTop: 8 }}>
            <button className="sm" onClick={() => this.setState({ error: null })}>Thử lại</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
