import './api/auth'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Outlet, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './styles/app.css'
import Shell from './app/Shell'
import Campaigns from './routes/Campaigns'
import CampaignPage from './features/campaign/CampaignPage'
import Soon from './routes/Soon'
// legacy screens, retired as each is rebuilt (see docs/WORKBENCH-REDESIGN.md)
import Workspace from './routes/Workspace'
import Program from './routes/Program'
import Wizard from './routes/Wizard'
import Analysis from './routes/Analysis'
import Approvals from './routes/Approvals'
import Experiment from './routes/Experiment'

/** Padding the legacy screens used to get from their own shell. */
const LegacyFrame = () => (
  <div style={{ maxWidth: 1240, margin: '0 auto', padding: '22px 40px 48px', zoom: 1.2 }}><Outlet /></div>
)

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaigns/:id" element={<CampaignPage />} />
            <Route path="/evidence" element={<Soon title="Evidence" hint="The provenance chain with a Verify button, anchor status and report export — next phase." />} />
            <Route path="/lab" element={<Soon title="Lab" hint="Instruments, the permitted fence and simulated-vs-real badges — next phase." />} />
            <Route element={<LegacyFrame />}>
              <Route path="/" element={<Workspace />} />
              <Route path="/programs/new" element={<Workspace initialForm />} />
              <Route path="/programs/:slug" element={<Program />} />
              <Route path="/wizard" element={<Wizard />} />
              <Route path="/analyze" element={<Analysis />} />
              <Route path="/analyses/new" element={<Analysis />} />
              <Route path="/analyses/:id" element={<Analysis />} />
              <Route path="/inbox" element={<Approvals />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/experiments/:eid" element={<Experiment />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)
