import { CircleCheck, CircleSlash, Cpu, Hand, ShieldAlert, ShieldCheck, Wifi } from 'lucide-react'
import { useApproveSop, useAuthority, useInstruments } from '../../api/hooks'
import type { Schemas } from '../../api/v1'
import { useToast } from '../../app/toast'
import { Button } from '../../ui/Button'
import { Card, CardHeader, Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'

type Instrument = Schemas['Instrument']

/** Real vs simulated is the most important fact about an instrument: say it first, in words. */
function Badge({ i }: { i: Instrument }) {
  if (i.hardware_validated) return <Tag tone="ok"><CircleCheck size={11} className="mr-1" />hardware-validated</Tag>
  if (i.simulated) return <Tag tone="warn"><CircleSlash size={11} className="mr-1" />simulated — output is synthetic</Tag>
  return <Tag tone="neutral">real driver · not yet validated on hardware</Tag>
}

function InstrumentCard({ i }: { i: Instrument }) {
  return (
    <div className="rounded-lg border border-line p-3.5">
      <div className="flex items-start gap-2">
        <Cpu size={16} className="mt-0.5 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-snug">{i.name}</div>
          <div className="text-xs text-muted">{i.kind}{i.vendor ? ` · ${i.vendor}` : ''}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5"><Badge i={i} />
        {i.requires_network && <Tag><Wifi size={11} className="mr-1" />network</Tag>}
        {!i.installed && <Tag tone="warn">not installed</Tag>}</div>
      {!!(i.assay_types.length || i.readouts.length) && (
        <div className="mt-2 flex flex-wrap gap-1">{[...i.assay_types, ...i.readouts].map((a) => <span key={a} className="num rounded bg-sunken px-1.5 py-0.5 text-[11px] text-muted">{a}</span>)}</div>
      )}
      {i.note && <p className="mt-2 text-xs text-faint">{i.note}</p>}
    </div>
  )
}

const COL = {
  autonomous: { label: 'Agent may act alone', icon: ShieldCheck, cls: 'text-accent bg-accent-soft' },
  human: { label: 'A person must approve', icon: Hand, cls: 'text-warn bg-warn-soft' },
  never: { label: 'Never — out of scope', icon: ShieldAlert, cls: 'text-bad bg-bad-soft' },
} as const

export default function LabPage() {
  const { data: ins, isLoading } = useInstruments()
  const { data: auth } = useAuthority()
  const sop = useApproveSop()
  const toast = useToast()
  const groups: [string, Instrument[]][] = [
    ['Hardware-validated', (ins ?? []).filter((i) => i.hardware_validated)],
    ['Real drivers, not yet validated on hardware', (ins ?? []).filter((i) => !i.hardware_validated && !i.simulated)],
    ['Simulated (synthetic output)', (ins ?? []).filter((i) => !i.hardware_validated && i.simulated)],
  ]
  return (
    <div className="mx-auto max-w-6xl p-6">
      <h1 className="mb-1 text-xl font-semibold tracking-tight">Lab</h1>
      <p className="mb-5 max-w-3xl text-sm text-muted">What can run an experiment, how real it is, and what the agents are allowed to do with it. A campaign may only use instruments a program has permitted; with none capable, it refuses instead of falling back to simulation.</p>
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-7">
          {isLoading && <Skeleton className="h-40" />}
          {groups.map(([title, list]) => list.length > 0 && (
            <Card key={title}>
              <CardHeader title={title} hint={`${list.length}`} />
              <div className="grid gap-3 p-4 md:grid-cols-2">{list.map((i) => <InstrumentCard key={i.id} i={i} />)}</div>
            </Card>
          ))}
          {ins && !groups[0][1].length && <p className="px-1 text-xs text-faint">No instrument here is validated against physical hardware yet — real results from a device must come from a session that verifies one.</p>}
        </div>
        <div className="space-y-4 lg:col-span-5">
          <Card>
            <CardHeader title="What the agents may do" hint="checked in this order; first match wins" />
            {!auth ? <div className="p-4"><Skeleton className="h-32" /></div> : (
              <ol className="divide-y divide-line">
                {auth.rules.map((r, i) => {
                  const c = COL[r.column]
                  return (
                    <li key={i} className="flex items-start gap-3 px-4 py-2.5">
                      <span className={`mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${c.cls}`}><c.icon size={11} />{c.label}</span>
                      <span className="text-[13px]">{r.when}{r.custom && <Tag className="ml-2" tone="accent">custom</Tag>}</span>
                    </li>
                  )
                })}
              </ol>
            )}
            {auth?.safety_rules && <p className="border-t border-line px-4 py-2.5 text-xs text-faint">Submissions are also screened against toxicophore rules (version {auth.safety_rules}); a refusal cites it.</p>}
          </Card>
          <Card>
            <CardHeader title="Procedures awaiting sign-off" hint="recurring work needs a person first" />
            {!auth?.sops_pending.length ? <p className="px-4 py-4 text-sm text-muted">None. Nothing recurring is waiting on you.</p> : (
              <ul className="divide-y divide-line">{auth.sops_pending.map((s) => (
                <li key={s.id} className="flex items-center gap-3 px-4 py-3"><div className="min-w-0 flex-1"><div className="num text-xs text-faint">{s.id}</div><div className="text-sm">{s.objective}</div></div>
                  <Button size="sm" variant="primary" disabled={sop.isPending} onClick={() => sop.mutate(s.id, { onSuccess: () => toast({ tone: 'ok', text: 'Signed off. Runs of this procedure may now proceed unattended.' }) })}>Sign off</Button></li>))}</ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Stop switch" />
            <p className="px-4 py-3 text-sm">{auth?.halt.halted ? <><b className="text-bad">Halted</b>{auth.halt.reason ? ` — ${auth.halt.reason}` : ''}. Agents cannot submit anything until a person resumes.</> : 'Not engaged. Use Halt (top right) to stop every agent at once.'}</p>
            {!!auth?.halt.history.length && <p className="border-t border-line px-4 py-2 text-xs text-faint">{auth.halt.history.length} halt event{auth.halt.history.length > 1 ? 's' : ''} on record.</p>}
          </Card>
        </div>
      </div>
    </div>
  )
}
