import { Link } from 'react-router-dom'
import { FlaskConical } from 'lucide-react'
import { useCampaigns } from '../api/hooks'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Tag } from '../ui/Chip'

export const StatusTag = ({ status }: { status: string }) => {
  const s = status.toLowerCase()
  if (s === 'running') return <Tag tone="accent"><span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />running</Tag>
  if (s === 'awaiting_results') return <Tag tone="warn">awaiting results</Tag>
  if (s === 'completed') return <Tag tone="ok">completed</Tag>
  if (s === 'interrupted' || s === 'failed') return <Tag tone="bad">{s}</Tag>
  return <Tag>{s}</Tag>
}

export const when = (t?: number | null) =>
  t ? new Date(t * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'

export default function Campaigns() {
  const { data, isLoading, error } = useCampaigns()
  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Campaigns</h1>
        {data && <span className="text-sm text-muted">{data.length} total</span>}
      </div>
      <Card className="overflow-hidden">
        {isLoading && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>}
        {error && <EmptyState title="Could not load campaigns" hint={(error as Error).message} />}
        {data && !data.length && (
          <EmptyState icon={<FlaskConical size={28} />} title="No campaigns yet"
            hint="Start one from a program, or run `bn campaign auto --template dose-response-screen` — it will appear here as it runs." />
        )}
        {!!data?.length && (
          <table className="w-full text-sm">
            <thead className="border-b border-line bg-sunken text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="px-4 py-2 font-semibold">Objective</th><th className="px-3 font-semibold">Status</th>
                <th className="px-3 font-semibold">Program</th><th className="px-3 font-semibold">Autonomy</th>
                <th className="px-4 text-right font-semibold">Updated</th></tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="border-b border-line last:border-0 hover:bg-sunken">
                  <td className="px-4 py-2.5"><Link to={`/campaigns/${c.id}`} className="font-medium hover:text-accent">{c.title}</Link></td>
                  <td className="px-3"><StatusTag status={c.status} /></td>
                  <td className="px-3 text-muted">{c.program?.name ?? '—'}</td>
                  <td className="px-3 text-muted">{c.autonomy ?? '—'}</td>
                  <td className="num px-4 text-right text-xs text-muted">{when(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
