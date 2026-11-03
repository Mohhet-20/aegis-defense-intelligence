import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** When this value changes (e.g. the route path) a previously caught error is cleared. */
  resetKey?: string
}

interface State {
  error: Error | null
}

/**
 * Last-resort render-error handler. Without it, one exception while rendering any
 * page unmounts the whole app and leaves a blank screen. It shows a short, generic
 * message (never the stack trace or error text, which can contain data) and logs the
 * error to the browser console for debugging.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error', error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="m-6 rounded-lg border border-red-700/60 bg-red-950/40 p-6 text-slate-100">
        <h2 className="text-lg font-semibold">Something went wrong on this page</h2>
        <p className="mt-2 text-sm text-slate-300">
          The rest of the application is unaffected. Try again, or go to another page. If it keeps happening, report it to an administrator.
        </p>
        <button
          type="button"
          className="mt-4 rounded-sm bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 focus:outline-hidden focus:ring-2 focus:ring-sky-400"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    )
  }
}
