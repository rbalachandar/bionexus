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
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 16px' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 18 }}>
        <Link to="/" style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <img src="/bionexus-mark.png" alt="" width={30} height={30} />
          <span style={{ fontSize: 17, fontWeight: 700 }}>bionexus</span>
        </Link>
        <nav style={{ display: 'flex', gap: 14, fontSize: 13 }}>
          <Link to="/">Workspace</Link>
        </nav>
        <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
          agents run the scientific method
        </span>
      </header>
      <HaltBanner />
      {children}
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
