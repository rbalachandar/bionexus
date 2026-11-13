import { useState } from 'react'
import * as D from '@radix-ui/react-dialog'
import { Bot, Cpu, ShieldCheck, User, X } from 'lucide-react'
import { useAgents, useTrace } from '../../api/hooks'
import { Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'
import { ago } from './format'

const ICON: Record<string, typeof Bot> = { agent: Bot, service: Cpu, human: User, instrument: ShieldCheck }

function TraceDrawer({ id, actor, onClose }: { id: string; actor: string | null; onClose: () => void }) {
  const { data, isLoading } = useTrace(id, actor)
  const [open, setOpen] = useState<number | null>(null)
  return (
    <D.Root open={!!actor} onOpenChange={(o) => !o && onClose()}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <D.Content aria-describedby={undefined} className="fixed right-0 top-0 z-50 flex h-full w-[min(640px,96vw)] flex-col border-l border-line-strong bg-surface shadow-2xl">
          <div className="flex items-center gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1"><D.Title className="num text-lg font-semibold">Trace · {actor}</D.Title>
              <p className="text-xs text-muted">Every record this actor wrote, in order, exactly as sealed in the ledger.</p></div>
            <D.Close aria-label="Close" className="rounded p-1 text-faint hover:bg-sunken hover:text-ink"><X size={18} /></D.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {isLoading && <div className="space-y-2 p-5"><Skeleton className="h-6" /><Skeleton className="h-6" /></div>}
            <ol className="divide-y divide-line">
              {data?.records.map((r, i) => (
                <li key={i} className="px-5 py-2.5">
                  <button className="flex w-full items-baseline gap-3 text-left" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
                    <span className="num w-20 shrink-0 text-[11px] text-faint">{ago(r.ts)}</span>
                    <span className="min-w-0 flex-1 text-[13px]">{r.summary}</span>
                    <Tag>{r.event.replace(/_/g, ' ')}</Tag>
                  </button>
                  {open === i && (
                    <pre className="num mt-2 max-h-72 overflow-auto rounded-md bg-sunken p-3 text-[11px] leading-relaxed">
                      {JSON.stringify({ actor: r.actor, kind: r.actor_kind, model_version: r.model_version, decision: r.detail }, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

/** Who acted in this campaign — and the full trace of each, one click away. */
export function AgentsCard({ id }: { id: string }) {
  const { data } = useAgents(id)
  const [actor, setActor] = useState<string | null>(null)
  if (!data) return <div className="p-4"><Skeleton className="h-16" /></div>
  return (
    <>
      <ul className="divide-y divide-line">
        {data.map((a) => {
          const Icon = ICON[a.kind] ?? Cpu
          return (
            <li key={a.id}>
              <button onClick={() => setActor(a.id)} className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-sunken">
                <Icon size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2"><span className="num text-sm font-medium">{a.id}</span>
                    {a.model_version && <Tag tone="accent">{a.model_version}</Tag>}<Tag>{a.kind}</Tag></span>
                  <span className="block text-xs text-muted">{a.role}</span>
                  <span className="block truncate text-[11px] text-faint">last: {a.last_text}</span>
                </span>
                <span className="num shrink-0 text-xs text-muted">{a.events} records</span>
              </button>
            </li>
          )
        })}
      </ul>
      <TraceDrawer id={id} actor={actor} onClose={() => setActor(null)} />
    </>
  )
}
