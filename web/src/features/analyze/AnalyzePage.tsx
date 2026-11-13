import { AlertTriangle, FileSpreadsheet, FileText, Download, Paperclip, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAnalyses, useAnalysis, useAttachAnalysis, useCampaigns, useReviewAnalysis, useRunAnalysis, useUploadAnalysis } from '../../api/hooks'
import type { Schemas } from '../../api/v1'
import { useToast } from '../../app/toast'
import { Button } from '../../ui/Button'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import { Field, Input, Select, Textarea } from '../../ui/Field'
import { StateChip, type State } from '../../ui/Chip'
import { CurveCard } from '../campaign/CurvePlot'
import { sig } from '../campaign/format'

type View = Schemas['AnalysisView']
type Compound = Schemas['AnalysisCompound']

const CALL: Record<string, State> = { validated: 'validated', invalidated: 'refuted', inconclusive: 'abstained' }
const CALL_WORDS: Record<string, string> = {
  validated: 'The whole 95% interval clears the gate.',
  invalidated: 'The whole 95% interval misses the gate.',
  inconclusive: 'The interval straddles the gate — the data cannot say which side. No claim either way.',
}
const ORIGINS = ['measured', 'historical', 'simulated', 'predicted', 'unknown'] as const

/* ------------------------------------------------------------------ pick a file */
function DropZone({ onFiles, busy }: { onFiles: (f: File, layout?: File) => void; busy: boolean }) {
  const [over, setOver] = useState(false)
  const [layout, setLayout] = useState<File>()
  const ref = useRef<HTMLInputElement>(null)
  const lref = useRef<HTMLInputElement>(null)
  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFiles(f, layout) }}
        className={cn('flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors',
          over ? 'border-accent bg-accent-soft' : 'border-line-strong')}
      >
        <Upload size={26} className="mb-3 text-muted" aria-hidden />
        <p className="text-sm font-medium">Drop a plate-reader export here</p>
        <p className="mt-1 max-w-md text-xs text-muted">CSV, TSV or XLSX — a long table (well, sample, conc_um, value) or a plate grid with a layout file. The file is stored by its digest; nothing is fitted until you confirm.</p>
        <div className="mt-4 flex gap-2">
          <Button variant="primary" disabled={busy} onClick={() => ref.current?.click()}>{busy ? 'Reading…' : 'Choose file'}</Button>
          <Button onClick={() => lref.current?.click()}>{layout ? `Layout: ${layout.name}` : 'Add layout file (optional)'}</Button>
        </div>
        <input ref={ref} type="file" hidden accept=".csv,.tsv,.txt,.xlsx" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFiles(f, layout) }} />
        <input ref={lref} type="file" hidden accept=".csv,.tsv,.txt,.xlsx" onChange={(e) => setLayout(e.target.files?.[0])} />
      </div>
    </div>
  )
}

function Recent() {
  const { data } = useAnalyses()
  if (!data?.length) return null
  return (
    <Card className="mt-6">
      <CardHeader title="Recent analyses" />
      <ul className="divide-y divide-line">
        {data.slice(0, 8).map((a) => (
          <li key={a.id}>
            <Link to={`/analyze/${a.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-sunken">
              <FileSpreadsheet size={15} className="text-muted" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm">{a.filename ?? a.id}</span>
              <Tag>{a.state.replace('_', ' ')}</Tag>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/* ------------------------------------------------------------------ 1. what we found */
function Found({ a }: { a: View }) {
  const p = a.preview
  const blockers = p.diagnostics.filter((d) => d.severity !== 'info')
  return (
    <Card>
      <CardHeader title="1 · What we found" hint="before any fit" right={<span className="num text-xs text-faint" title={a.sha256 ?? ''}>sha256 {a.sha256?.slice(0, 10)}</span>} />
      <div className="grid gap-4 p-4 sm:grid-cols-4">
        <Stat label="File" value={a.filename ?? '—'} />
        <Stat label="Wells" value={`${p.n_wells}`} sub={p.format ? `${p.format} format` : undefined} />
        <Stat label="Controls" value={`${p.n_controls}`} sub={p.n_controls ? undefined : 'none detected'} />
        <Stat label="Plate quality (Z′)" value={p.z_prime != null ? p.z_prime.toFixed(2) : 'not computable'}
          sub={p.z_prime == null ? 'needs both control classes' : p.z_kind === 'heuristic' ? 'heuristic, not a real Z′' : p.z_prime >= 0.5 ? 'good separation' : 'weak separation'}
          tone={p.z_prime == null ? 'warn' : p.z_prime >= 0.5 ? 'ok' : 'warn'} />
      </div>
      <p className="border-t border-line px-4 py-2.5 text-xs text-muted">
        {p.samples.length} sample{p.samples.length === 1 ? '' : 's'}: <span className="num">{p.samples.slice(0, 12).join(', ')}{p.samples.length > 12 ? '…' : ''}</span>
        {!p.has_doses && ' · no concentrations found, so no dose–response can be fitted'}
      </p>
      {blockers.map((d) => (
        <p key={d.code} className="flex items-start gap-2 border-t border-line bg-warn-soft px-4 py-2 text-xs text-warn">
          <AlertTriangle size={13} className="mt-px shrink-0" aria-hidden />{d.message}
        </p>
      ))}
    </Card>
  )
}

const Stat = ({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'ok' | 'warn' }) => (
  <div className="min-w-0">
    <div className="text-[11px] font-medium uppercase tracking-wider text-faint">{label}</div>
    <div className={cn('num truncate text-base font-semibold', tone === 'ok' && 'text-ok', tone === 'warn' && 'text-warn')}>{value}</div>
    {sub && <div className="text-[11px] text-faint">{sub}</div>}
  </div>
)

/* ------------------------------------------------------------------ 2. confirm + run */
function Confirm({ a }: { a: View }) {
  const run = useRunAnalysis()
  const toast = useToast()
  const cfg = a.result?.gate
  const [t, setT] = useState(cfg?.threshold != null ? String(cfg.threshold) : '')
  const [dir, setDir] = useState<'min' | 'max'>(cfg?.direction === 'max' ? 'max' : 'min')
  const [top, setTop] = useState('')
  const [origin, setOrigin] = useState<string>(a.preview.evidence_origin)
  const proxy = ['simulated', 'predicted', 'unknown'].includes(origin)
  return (
    <Card>
      <CardHeader title="2 · Confirm and fit" hint="what you state here is recorded" />
      <div className="grid gap-x-4 p-4 sm:grid-cols-4">
        <Field label="Gate: IC50 must be" hint="optional — blank gives estimates only">
          <Select value={dir} onChange={(e) => setDir(e.target.value as 'min' | 'max')}>
            <option value="min">at most (≤)</option><option value="max">at least (≥)</option>
          </Select>
        </Field>
        <Field label="Gate value (µM)"><Input inputMode="decimal" placeholder="e.g. 10" value={t} onChange={(e) => setT(e.target.value)} /></Field>
        <Field label="Assay ceiling" hint="optional: known top response"><Input inputMode="decimal" placeholder="e.g. 100" value={top} onChange={(e) => setTop(e.target.value)} /></Field>
        <Field label="Where did the data come from?">
          <Select value={origin} onChange={(e) => setOrigin(e.target.value)}>{ORIGINS.map((o) => <option key={o}>{o}</option>)}</Select>
        </Field>
      </div>
      {proxy && <p className="mx-4 mb-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">Marked “{origin}”: results are shown but this data can’t be attached to a campaign as evidence.</p>}
      <div className="flex items-center gap-3 border-t border-line px-4 py-3">
        <Button variant="primary" disabled={run.isPending || !a.preview.has_doses}
          onClick={() => run.mutate({ id: a.id, v: {
            threshold: t.trim() ? Number(t) : null, direction: dir, max_response: top.trim() ? Number(top) : null,
            evidence_origin: origin as Schemas['AnalysisRun']['evidence_origin'] } },
          { onError: (e) => toast({ tone: 'bad', text: e.message }) })}>
          {run.isPending ? 'Fitting…' : a.result ? 'Re-run with these settings' : 'Fit curves'}
        </Button>
        <span className="text-xs text-faint">{a.revision > 1 ? `revision ${a.revision} · earlier revisions stay on record` : 'a changed setting opens a new revision'}</span>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ 3. results */
function CompoundBlock({ c, gate }: { c: Compound; gate: number | null }) {
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{c.entity}</span>
        {c.call ? <StateChip state={CALL[c.call] ?? 'proposed'} /> : <Tag>estimate only</Tag>}
        {c.call && <span className="text-xs text-muted">{CALL_WORDS[c.call]}</span>}
      </div>
      {c.curve ? <CurveCard c={{ ...c.curve, label: c.entity, run_id: 'this plate' }} gate={gate} />
        : <p className="rounded-md border border-line px-3 py-2 text-xs text-muted">No usable dose–response points for {c.entity}{c.ic50_um == null ? ' — no IC50 claimed' : ''}.</p>}
    </div>
  )
}

function Results({ a }: { a: View }) {
  const r = a.result!
  const gate = r.gate?.threshold ?? null
  return (
    <Card>
      <CardHeader title="3 · What the data says" hint={r.gate?.label ?? 'estimate only — no gate registered'}
        right={<div className="flex gap-2">
          <Button size="sm" asChild><a href={`/api/v1/analyses/${a.id}/report`} target="_blank" rel="noreferrer"><FileText size={13} />Report</a></Button>
          <Button size="sm" asChild><a href={`/api/v1/analyses/${a.id}/export.csv`}><Download size={13} />CSV</a></Button>
        </div>} />
      {(r.qc_hold || r.refused || r.note) && (
        <p className="flex items-start gap-2 border-b border-line bg-warn-soft px-4 py-2.5 text-xs text-warn">
          <AlertTriangle size={13} className="mt-px shrink-0" aria-hidden />
          {r.refused ? 'The system declined to interpret this plate. ' : r.qc_hold ? 'Plate quality is below the floor, so calls are held. ' : ''}{r.note ?? r.z_note}
        </p>
      )}
      <div className="space-y-5 p-4">
        {r.compounds.length ? r.compounds.map((c) => <CompoundBlock key={c.entity} c={c} gate={gate} />)
          : <EmptyState title="No compounds fitted" hint="The plate has no compound wells with a dose series." />}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ 4. review + attach */
function ReviewAttach({ a }: { a: View }) {
  const review = useReviewAnalysis()
  const attach = useAttachAnalysis()
  const camps = useCampaigns()
  const toast = useToast()
  const [action, setAction] = useState<'acknowledge' | 'comment' | 'override'>('acknowledge')
  const [reason, setReason] = useState('')
  const [target, setTarget] = useState('')
  const [campaign, setCampaign] = useState('')
  const [cand, setCand] = useState('')
  const reviewed = a.state === 'reviewed'
  const origin = a.preview.evidence_origin
  const canAttach = reviewed && !['simulated', 'predicted', 'unknown'].includes(origin) && !!campaign
  return (
    <Card>
      <CardHeader title="4 · Your decision" hint="beside the computed call, never over it" />
      <div className="grid gap-6 p-4 lg:grid-cols-2">
        <div>
          <div className="grid gap-x-3 sm:grid-cols-2">
            <Field label="What are you doing?"><Select value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
              <option value="acknowledge">Acknowledge</option><option value="comment">Comment</option><option value="override">Override a call</option></Select></Field>
            <Field label="About compound (optional)"><Select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">the whole plate</option>{a.result?.compounds.map((c) => <option key={c.entity}>{c.entity}</option>)}</Select></Field>
          </div>
          <Field label={action === 'override' ? 'Why? (required)' : 'Note'}><Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. curve is shallow; top plateau not reached" /></Field>
          <Button variant="primary" disabled={review.isPending || (action === 'override' && !reason.trim())}
            onClick={() => review.mutate({ id: a.id, v: { action, reason, target } }, {
              onSuccess: () => { setReason(''); toast({ tone: 'ok', text: 'Recorded under your name.' }) }, onError: (e) => toast({ tone: 'bad', text: e.message }) })}>Record</Button>
          {a.reviews.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-muted">
              {a.reviews.map((r, i) => <li key={i}><b className="text-ink">{r.by}</b> {r.action}{r.target && ` · ${r.target}`}{r.reason && ` — ${r.reason}`}</li>)}
            </ul>
          )}
        </div>
        <div className={cn(!reviewed && 'opacity-60')}>
          <p className="mb-2 text-xs text-muted">Cite this analysis in a campaign’s record as supporting evidence. It is context for whoever reads the campaign — it does not change any verdict.</p>
          <Field label="Campaign"><Select value={campaign} disabled={!reviewed} onChange={(e) => setCampaign(e.target.value)}>
            <option value="">choose…</option>{camps.data?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}</Select></Field>
          <Field label="Candidate (optional)"><Select value={cand} disabled={!reviewed} onChange={(e) => setCand(e.target.value)}>
            <option value="">—</option>{a.result?.compounds.map((c) => <option key={c.entity}>{c.entity}</option>)}</Select></Field>
          <Button disabled={!canAttach || attach.isPending}
            onClick={() => attach.mutate({ id: a.id, v: { campaign_id: campaign, candidate: cand || null, note: '' } }, {
              onSuccess: () => toast({ tone: 'ok', text: 'Attached and sealed in the campaign’s record.' }), onError: (e) => toast({ tone: 'bad', text: e.message }) })}><Paperclip size={13} />Attach as evidence</Button>
          {!reviewed && <p className="mt-2 text-[11px] text-faint">Record your decision first.</p>}
          {a.attachments.map((x, i) => (
            <p key={i} className="mt-2 text-xs text-muted">Attached to <Link className="text-accent underline" to={`/campaigns/${x.campaign_id}`}>{camps.data?.find((c) => c.id === x.campaign_id)?.title ?? x.campaign_id}</Link>{x.candidate && ` for ${x.candidate}`} by {x.by}</p>
          ))}
        </div>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ page */
export default function AnalyzePage() {
  const { id } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const up = useUploadAnalysis()
  const { data: a, isLoading, error } = useAnalysis(id)
  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-5 flex items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight">Analyze</h1>
          <p className="max-w-2xl text-sm text-muted">Is this plate any good, and what does it say? Drop an export; get dose–response curves with IC50 and its interval, plate QC, and honest abstentions.</p>
        </div>
        {id && <Button onClick={() => nav('/analyze')}>New analysis</Button>}
      </div>
      {!id && (<>
        <DropZone busy={up.isPending} onFiles={(file, layout) => up.mutate({ file, layout }, {
          onSuccess: (d) => nav(`/analyze/${d.id}`), onError: (e) => toast({ tone: 'bad', text: e.message }) })} />
        <Recent />
      </>)}
      {id && isLoading && <Skeleton className="h-48" />}
      {id && error && <EmptyState title="Analysis not found" hint={error.message} />}
      {a && (
        <div className="space-y-4">
          <Found a={a} />
          <Confirm key={`${a.id}-${a.revision}`} a={a} />
          {a.result && <Results a={a} />}
          {a.result && <ReviewAttach a={a} />}
        </div>
      )}
    </div>
  )
}
