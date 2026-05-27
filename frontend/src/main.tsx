import { StrictMode, Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

class ErrorBoundary extends Component<{ children: ReactNode }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex flex-col items-center justify-center p-8" style={{ backgroundColor: '#0a0a0c', color: '#f8fafc' }}>
          <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
          <p className="mb-6" style={{ color: '#94a3b8' }}>An unexpected error occurred. Please refresh the page.</p>
          <button onClick={() => window.location.reload()} className="px-6 py-3 rounded-xl font-bold text-white" style={{ backgroundColor: '#8b5cf6' }}>
            Refresh Page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
