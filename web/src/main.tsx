import './api/auth'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './styles/app.css'
import Shell from './app/Shell'
import { ToastProvider } from './app/toast'
import Campaigns from './routes/Campaigns'
import CampaignPage from './features/campaign/CampaignPage'
import TodayPage from './features/today/TodayPage'
import ProgramPage from './features/program/ProgramPage'
import InboxPage from './features/inbox/InboxPage'
import EvidencePage from './features/evidence/EvidencePage'
import LabPage from './features/lab/LabPage'
// legacy screens, retired as each is rebuilt (see docs/WORKBENCH-REDESIGN.md)
import Analysis from './routes/Analysis'

/** Padding the legacy screens used to get from their own shell. */
const LegacyFrame = () => (
  <div style={{ maxWidth: 1240, margin: '0 auto', padding: '22px 40px 48px', zoom: 1.2 }}><Outlet /></div>
)

const ToCampaign = () => <Navigate to={`/campaigns/${useParams().eid}`} replace />

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

function Toasts({ children }: { children: React.ReactNode }) {
  const nav = useNavigate()
  return <ToastProvider onNavigate={nav}>{children}</ToastProvider>
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
       <Toasts>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/" element={<TodayPage />} />
            <Route path="/programs/:slug" element={<ProgramPage />} />
            <Route path="/experiments/:eid" element={<ToCampaign />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/approvals" element={<Navigate to="/inbox" replace />} />
            <Route path="/campaigns/:id" element={<CampaignPage />} />
            <Route path="/evidence" element={<EvidencePage />} />
            <Route path="/lab" element={<LabPage />} />
            <Route element={<LegacyFrame />}>
                      <Route path="/analyze" element={<Analysis />} />
              <Route path="/analyses/new" element={<Analysis />} />
              <Route path="/analyses/:id" element={<Analysis />} />
                  </Route>
          </Route>
        </Routes>
       </Toasts>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)
