import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './styles/tokens.css'
import Workspace from './routes/Workspace'
import ProgramForm from './routes/ProgramForm'
import Wizard from './routes/Wizard'
import Approvals, { HaltBanner } from './routes/Approvals'
import Experiment from './routes/Experiment'

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: '100vh' }}>
      <header style={{
        background: 'var(--ink)', color: '#fff',
        padding: '0 28px', height: 52,
        display: 'flex', alignItems: 'center', gap: 28,
      }}>
        <Link to="/" style={{ display: 'inline-flex', gap: 9, alignItems: 'center' }}>
          <img src="/bionexus-mark.png" alt="" width={26} height={26} />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>bionexus</span>
        </Link>
        <nav style={{ display: 'flex', gap: 4, fontSize: 13 }}>
          <Link to="/" style={{ color: '#cbd5e1', padding: '5px 12px',
            borderRadius: 6 }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
              e.currentTarget.style.color = '#fff'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.color = '#cbd5e1'
            }}>
            Workspace
          </Link>
        </nav>
        <span style={{ fontSize: 11, color: '#64748b', fontStyle: 'italic',
          marginLeft: 'auto' }}>
          agents run the scientific method
        </span>
      </header>
      <main style={{ maxWidth: 1240, margin: '0 auto', padding: '22px 28px 48px' }}>
        <HaltBanner />
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Shell>
          <Routes>
            <Route path="/" element={<Workspace />} />
            <Route path="/programs/new" element={<Workspace initialForm />} />
            <Route path="/wizard" element={<Wizard />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/experiments/:eid" element={<Experiment />} />
          </Routes>
        </Shell>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
