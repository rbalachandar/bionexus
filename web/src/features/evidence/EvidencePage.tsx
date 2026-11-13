import { Link } from 'react-router-dom'
import { Anchor, Check, Copy, Download, FileText, ShieldCheck, ShieldX, Stamp } from 'lucide-react'
import { useAnchor, useCampaigns, useCreateAnchor, useEvals, useLedger, useVerifyLedger } from '../../api/hooks'
import { useToast } from '../../app/toast'
import { Button } from '../../ui/Button'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'
import { Tip } from '../../ui/Tooltip'
import { ago } from '../campaign/format'

function LedgerCard() {
  const { data, isLoading } = useLedger()
  const verify = useVerifyLedger()
  const toast = useToast()
  if (isLoading || !data) return <Card><CardHeader title="Ledger" /><div className="p-4"><Skeleton className="h-24" /></div></Card>
  const ok = data.chain.verified
  return (
    <Card>
      <CardHeader title="Ledger" hint="every record, re-hashed on demand"
        right={<Button size="sm" variant="primary" disabled={verify.isPending}
          onClick={() => verify.mutate(undefined, { onSuccess: (d) => toast({ tone: d.chain.verified ? 'ok' : 'bad', text: d.chain.verified ? `Verified ${d.chain.records.toLocaleString()} records in ${d.verified_in_ms} ms — nothing was altered.` : 'Integrity check FAILED — see the branches below.' }) })}>
          <ShieldCheck size={14} /> {verify.isPending ? 'Verifying…' : 'Verify now'}</Button>} />
      <div className="flex items-center gap-3 px-4 py-4">
        {ok ? <ShieldCheck size={26} className="text-ok" /> : <ShieldX size={26} className="text-bad" />}
        <div>
          <div className="text-base font-semibold">{ok ? 'Intact' : 'Integrity failed'}</div>
          <div className="text-sm text-muted">{data.chain.records.toLocaleString()} records across {data.branches.length} branches · last check took <span className="num">{data.verified_in_ms}</span> ms</div>
        </div>
      </div>
      <p className="border-t border-line px-4 py-2.5 text-xs text-muted">
        Each record contains the hash of the one before it, and its own hash covers the whole record (including who wrote it). Editing any record, even one field, breaks the chain from that point on.
        A rewrite that fixes every later hash too can only be caught by an <b>anchor</b> published outside this machine.
      </p>
      <div className="max-h-72 overflow-auto border-t border-line">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-sunken text-left text-[11px] uppercase tracking-wider text-muted"><tr><th className="px-4 py-1.5 font-semibold">Branch</th><th className="px-3 font-semibold">Records</th><th className="px-4 text-right font-semibold">Status</th></tr></thead>
          <tbody>
            {data.branches.map((b) => (
              <tr key={b.id} className="border-t border-line">
                <td className="px-4 py-2">{b.campaign_id ? <Link className="hover:text-accent" to={`/campaigns/${b.campaign_id}`}><span className="num text-xs text-faint">{b.id}</span> <span className="ml-1">{b.campaign_title}</span></Link> : <span className="num text-xs">{b.id}</span>}</td>
                <td className="num px-3 text-muted">{b.records}</td>
                <td className="px-4 text-right">{b.verified ? <Tag tone="ok"><Check size={11} className="mr-1" />intact</Tag> : <Tag tone="bad">altered</Tag>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function AnchorCard() {
  const { data } = useAnchor()
  const create = useCreateAnchor()
  const toast = useToast()
  const latest = data?.anchors[0]
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => toast({ tone: 'ok', text: 'Root copied. Publish it somewhere you do not control.' }))
  return (
    <Card>
      <CardHeader title="External anchor" hint="a fingerprint of the whole ledger"
        right={<Button size="sm" variant="secondary" disabled={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: () => toast({ tone: 'ok', text: 'Anchor created. Now publish the root — an unpublished anchor protects nothing.' }) })}><Stamp size={14} /> Anchor now</Button>} />
      <div className="px-4 py-4">
        {latest ? (
          <>
            <div className="flex items-center gap-2 text-sm">
              <Anchor size={16} className="text-muted" /> Last anchored <b>{ago(latest.ts)}</b> · <span className="num">{latest.records.toLocaleString()}</span> records
              {data?.check && (data.check.match
                ? <Tag tone="ok">unchanged since{data.check.appended_since_anchor ? ` (+${data.check.appended_since_anchor} new)` : ''}</Tag>
                : <Tag tone="bad">{data.check.content_tampered ? 'content altered' : 'does not match'}</Tag>)}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <code className="num min-w-0 flex-1 truncate rounded bg-sunken px-2 py-1 text-xs" title={latest.merkle_root}>{latest.merkle_root}</code>
              <Tip label="Copy the Merkle root"><Button size="icon" variant="ghost" aria-label="Copy root" onClick={() => copy(latest.merkle_root)}><Copy size={14} /></Button></Tip>
            </div>
          </>
        ) : <p className="text-sm text-muted">No anchor yet.</p>}
        {data?.note && <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-[13px] text-warn">{data.note}</p>}
      </div>
    </Card>
  )
}

function ExportsCard() {
  const { data } = useCampaigns()
  return (
    <Card>
      <CardHeader title="Reports" hint="a campaign's record as a shareable file" />
      {!data?.length ? <EmptyState title="No campaigns yet" /> : (
        <ul className="divide-y divide-line">
          {data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1 truncate text-sm">{c.title}</span>
              {([['report', 'Report', FileText], ['notebook', 'Notebook', FileText], ['eln', 'ELN CSV', Download]] as const).map(([k, l, Icon]) => (
                <a key={k} href={`/api/v1/evidence/export/${c.id}?kind=${k}`} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-md border border-line-strong px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-ink"><Icon size={12} /> {l}</a>
              ))}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function MeasuredCard() {
  const { data } = useEvals()
  if (!data?.available) return null
  const deductions = data.tasks.filter((t) => t.honest_deduction)
  return (
    <Card>
      <CardHeader title="Measured" hint="the deterministic eval suite" />
      <div className="px-4 py-4">
        <div className="flex items-baseline gap-3"><span className="num text-2xl font-semibold">{data.mean.toFixed(3)}</span>
          <span className="text-sm text-muted">mean over {data.n_tasks} tasks · pass bar {data.pass_bar} · {data.all_pass ? 'all pass' : 'some failing'}</span></div>
        {!!deductions.length && (
          <div className="mt-3">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Honest deductions — passing, but below 1.0</div>
            <ul className="space-y-1">{deductions.map((t) => (
              <li key={t.task} className="flex items-baseline gap-2 text-[13px]"><span className="num w-44 shrink-0 font-medium">{t.task}</span><span className="num w-12 shrink-0 text-muted">{t.score.toFixed(3)}</span><span className="min-w-0 flex-1 truncate text-faint" title={t.notes}>{t.notes}</span></li>))}</ul>
            <p className="mt-2 text-xs text-faint">An abstention is graded down rather than counted as a pass, so these are the harness refusing to overcredit its own agents.</p>
          </div>
        )}
      </div>
    </Card>
  )
}

export default function EvidencePage() {
  return (
    <div className="mx-auto max-w-6xl p-6">
      <h1 className="mb-1 text-xl font-semibold tracking-tight">Evidence</h1>
      <p className="mb-5 max-w-3xl text-sm text-muted">Can you defend a result? Everything an agent or a person did is in one tamper-evident ledger. Verify it, anchor it outside this machine, and export any campaign's record.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4"><LedgerCard /><MeasuredCard /></div>
        <div className="space-y-4"><AnchorCard /><ExportsCard /></div>
      </div>
    </div>
  )
}
