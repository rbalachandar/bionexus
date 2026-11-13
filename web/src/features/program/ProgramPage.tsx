import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, CheckCircle2, ChevronLeft, CircleDashed, Compass, Plus } from 'lucide-react'
import { useProgram } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'
import { StatusTag, when } from '../../routes/Campaigns'
import { MiniOutcome } from '../campaign/MiniOutcome'
import { ResultsTable } from '../campaign/ResultsTable'
import type { Hyp } from '../campaign/format'
import { sig } from '../campaign/format'
import { goalLine } from './goal'
import { LaunchCampaignDialog } from '../launch/LaunchCampaignDialog'
import { NewProgramDialog } from '../launch/NewProgramDialog'

export default function ProgramPage() {
  const { slug = '' } = useParams()
  const nav = useNavigate()
  const { data: p, isLoading, error } = useProgram(slug)
  const [launch, setLaunch] = useState(false)
  const [follow, setFollow] = useState<string[] | null>(null)
  const [np, setNp] = useState(false)
  if (isLoading) return <div className="mx-auto max-w-6xl space-y-4 p-6"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-24" /><Skeleton className="h-64" /></div>
  if (error || !p) return <div className="mx-auto max-w-3xl p-10"><EmptyState title="Program not found" hint={(error as Error | null)?.message} /></div>

  const g = goalLine(p.goal, p.gate)
  const unit = p.gate.unit ?? ''
  // every judged candidate of every campaign, as rows against the SAME gate
  const hyps: Hyp[] = p.results.map((r) => ({
    id: `${r.campaign_id}|${r.hypothesis_id}`, head: r.candidate, candidate: r.candidate, statement: '', stage: '',
    state: r.state as Hyp['state'], selected: false,
    verdict: { status: (r.state === 'refuted' ? 'refuted' : r.state === 'abstained' ? 'abstained' : r.state) as 'validated', observed: r.observed, ci: r.ci, extrapolation: false },
  }))
  const campaignOf = new Map(p.results.map((r) => [`${r.campaign_id}|${r.hypothesis_id}`, r]))

  return (
    <div className="mx-auto max-w-6xl p-6">
      <Link to="/" className="mb-2 inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><ChevronLeft size={14} /> Today</Link>
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{p.name}</h1>
        {p.gate.label && <Tag className="num !text-xs">gate {p.gate.label}</Tag>}
        {p.modality && <Tag>{p.modality}</Tag>}
        {p.mode && <Tag>{p.mode}</Tag>}
        <Button variant="primary" size="sm" className="ml-auto" onClick={() => setLaunch(true)}><Plus size={14} /> New campaign</Button>
        <LaunchCampaignDialog open={launch} onOpenChange={setLaunch} slug={p.slug} />
      </div>
      {p.objective && <p className="mb-4 max-w-3xl text-sm text-muted">{p.objective}</p>}

      <Card className={`mb-4 flex items-start gap-3 px-5 py-4 ${g.tone === 'ok' ? 'border-ok/40 bg-ok-soft' : ''}`}>
        {g.tone === 'ok' ? <CheckCircle2 className="mt-0.5 text-ok" size={20} /> : <CircleDashed className="mt-0.5 text-muted" size={20} />}
        <div>
          <div className="text-base font-semibold">{g.title}</div>
          <div className="text-sm text-muted">{g.detail}</div>
          <div className="mt-1 text-xs text-faint">Across {p.campaigns} campaign{p.campaigns === 1 ? '' : 's'}: <b className="num text-ink">{p.goal.claimed}</b> claimed · <b className="num text-ink">{p.goal.refuted}</b> refuted · <b className="num text-ink">{p.goal.abstained}</b> abstained</div>
        </div>
      </Card>

      {!!p.next_steps.length && (
        <Card className="mb-4">
          <CardHeader title="What next" hint="from the evidence — no model needed" />
          <ul className="divide-y divide-line">
            {p.next_steps.map((n, i) => (
              <li key={i} className="flex items-start gap-3 px-4 py-3">
                <Compass size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden />
                <div className="min-w-0 flex-1"><div className="text-sm font-medium">{n.title}</div><div className="text-xs text-muted">{n.detail}</div></div>
                <Button size="sm" variant="secondary" onClick={() => {
                  if (n.action === 'inbox') nav('/inbox')
                  else if (n.action === 'new_program') setNp(true)
                  else if (n.kind === 'follow_up') setFollow(n.candidates)
                  else setLaunch(true)
                }}>{n.action === 'inbox' ? 'Open inbox' : n.action === 'new_program' ? 'New program' : n.kind === 'follow_up' ? 'Follow up' : 'New campaign'} <ArrowRight size={13} /></Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <NewProgramDialog open={np} onOpenChange={setNp} />
      {follow && <LaunchCampaignDialog open onOpenChange={() => setFollow(null)} slug={p.slug} title="Follow up"
        defaults={{ objective: `Follow-up: resolve ${follow.join(', ')}`, candidates: follow }} />}

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7">
          <CardHeader title="Every candidate, one gate" hint="click one to open it in its campaign" />
          {hyps.length ? (
            <ResultsTable hyps={hyps} gate={p.gate} sub={(h) => campaignOf.get(h.id)?.campaign_title}
              onOpen={(h) => { const r = campaignOf.get(h.id); if (r) nav(`/campaigns/${r.campaign_id}?h=${encodeURIComponent(r.hypothesis_id)}`) }} />
          ) : <EmptyState title="Nothing judged yet" hint={`Candidates appear here once a campaign measures them against ${p.gate.label ?? 'the gate'}.`} />}
        </Card>
        <Card className="lg:col-span-5">
          <CardHeader title="Campaigns" hint={`${p.campaign_list.length}`} />
          {p.campaign_list.length ? (
            <ul className="divide-y divide-line">
              {p.campaign_list.map((c) => (
                <li key={c.id}>
                  <Link to={`/campaigns/${c.id}`} className="block px-4 py-3 hover:bg-sunken">
                    <div className="flex items-start gap-2"><span className="min-w-0 flex-1 text-sm font-medium leading-snug">{c.title}</span><StatusTag status={c.status} /></div>
                    <div className="mt-1.5 flex items-center gap-3 text-xs text-muted">
                      <MiniOutcome f={c.funnel} />
                      {c.best && <span>best <b className="num text-ink">{c.best.candidate}</b> {sig(c.best.observed)} {unit}</span>}
                      <span className="num ml-auto text-faint">{when(c.updated_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No campaigns yet" hint="Launch one to start testing candidates against the gate." />}
        </Card>
      </div>
    </div>
  )
}
