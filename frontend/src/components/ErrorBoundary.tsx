import { Component, type ErrorInfo, type ReactNode } from 'react'
import { paths } from '../lib/routes'

/**
 * Catches a render-time crash and shows something recoverable.
 *
 * Without this, one thrown error anywhere in the tree unmounts the whole app and leaves a
 * blank white page — no navigation, no message, nothing to click. That is the single worst
 * failure mode a single-page app has, because it looks identical to the server being down
 * and gives the user nothing to act on.
 *
 * A class component because React still offers no hook equivalent for componentDidCatch.
 */
interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept in the console so the stack survives for whoever is debugging: the panel below
    // deliberately shows the message only, not a component trace.
    console.error('Recourse crashed while rendering:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="mx-auto max-w-lg p-8">
        <div className="surface p-6">
          <h1 className="text-[17px]" style={{ fontVariationSettings: "'wght' 600" }}>
            Something broke on this page
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-[var(--fg-2)]">
            The rest of the app is fine — this is a display error, not a lost decision.
            Nothing has been approved or submitted as a result of it.
          </p>
          <pre className="num mt-3 overflow-x-auto rounded-[var(--radius-control)] bg-[var(--surface-2)] p-3 text-[11.5px] text-[var(--fg-3)]">
            {this.state.error.message}
          </pre>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="focus-ring pressable rounded-[var(--radius-control)] px-3 py-1.5 text-[12.5px]"
              style={{ background: 'var(--fg)', color: 'var(--bg)' }}
            >
              Try again
            </button>
            <a
              href={paths.overview}
              className="focus-ring pressable rounded-[var(--radius-control)] px-3 py-1.5 text-[12.5px] text-[var(--fg-2)]"
              style={{ boxShadow: 'var(--shadow-line)' }}
            >
              Back to overview
            </a>
          </div>
        </div>
      </div>
    )
  }
}
