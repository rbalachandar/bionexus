import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './styles/tokens.css'
import Workspace from './routes/Workspace'
import Experiment from './routes/Experiment'

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 16px' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
        <img src="/bionexus-mark.png" alt="" width={34} height={34} />
        <Link to="/" style={{ fontSize: 18, fontWeight: 700 }}>bionexus</Link>
        <span className="muted" style={{ fontSize: 12 }}>
          agents run the scientific method
        </span>
      </header>
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
