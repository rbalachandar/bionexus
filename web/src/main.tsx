import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link, NavLink } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
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
  const gov = useQuery({
    queryKey: ['gov-pill'],
    queryFn: async () => {
      const [ap, halt] = await Promise.all([
        fetch('/api/approvals').then((r) => r.json()),
        fetch('/api/halt').then((r) => r.json()),
      ])
      return { pending: (ap.pending ?? []).length, halted: !!halt.halted }
    },
    refetchInterval: 5000,
  })
  const navLink = (to: string, label: string) => (
    <NavLink to={to} style={({ isActive }) => ({
      color: isActive ? '#fff' : '#94a3b8', padding: '5px 12px',
      borderRadius: 6, fontSize: 13, textDecoration: 'none',
      background: isActive ? 'rgba(255,255,255,0.12)' : 'transparent',
    })}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.12)'
        ; e.currentTarget.style.color = '#fff' }}
      onMouseLeave={(e) => {
        const active = (e.currentTarget as HTMLAnchorElement).classList.contains('active')
        e.currentTarget.style.background = active ? 'rgba(255,255,255,0.12)' : 'transparent'
        e.currentTarget.style.color = active ? '#fff' : '#94a3b8'
      }}>
      {label}
    </NavLink>
  )
  return (
    <div style={{ minHeight: '100vh' }}>
      <header style={{
        background: 'linear-gradient(90deg, #0b1220 0%, #0f2e38 100%)', color: '#fff',
        padding: '0 40px', height: 54,
        borderBottom: '2px solid var(--brand)',
        display: 'flex', alignItems: 'center', gap: 28,
      }}>
        <Link to="/" style={{ display: 'inline-flex', gap: 9, alignItems: 'center' }}>
          <img src="/bionexus-mark.png" alt="" width={26} height={26} />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>bionexus</span>
        </Link>
        <nav style={{ display: 'flex', gap: 4 }}>
          {navLink('/', 'Workspace')}
          {navLink('/wizard', 'Wizard')}
        </nav>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8,
          marginLeft: 'auto', fontSize: 12, color: '#7dd3e8' }}>
          <span style={{ width: 24, height: 1, background: 'rgba(125,211,232,0.4)' }} />
          agents run the scientific method
        </span>
        {(gov.data?.halted || (gov.data?.pending ?? 0) > 0) && (
          <Link to="/approvals" title="open Approvals & governance"
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center',
              flex: 'none', textDecoration: 'none', fontSize: 12, fontWeight: 600,
              color: gov.data!.halted ? '#fecaca' : '#fde68a',
              background: gov.data!.halted ? 'rgba(220,38,38,0.35)'
                : 'rgba(217,119,6,0.25)',
              border: `1px solid ${gov.data!.halted ? '#ef4444' : '#f59e0b'}`,
              borderRadius: 999, padding: '4px 12px' }}>
            <ShieldAlert size={13} />
            {gov.data!.halted ? 'halted' : `${gov.data!.pending} approval${gov.data!.pending === 1 ? '' : 's'}`}
          </Link>
        )}
      </header>
      <main style={{ maxWidth: 1240, margin: '0 auto', padding: '22px 40px 48px' }}>
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
