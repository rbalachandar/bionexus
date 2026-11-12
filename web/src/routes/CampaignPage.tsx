import { Link, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { useCampaign } from '../api/hooks'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { StatusTag } from './Campaigns'

const Stat = ({ label, value }: { label: string; value: number }) => (
  <Card className="px-4 py-3">
    <div className="num text-2xl font-semibold">{value}</div>
    <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
  </Card>
)

/** Phase-2 placeholder: proves the generated client end to end. The full
 *  cockpit (rounds, why-this-plate, interval plots) lands in phase 3. */
export default function CampaignPage() {
  const { id = '' } = useParams()
  const { data, isLoading, error } = useCampaign(id)
  return (
    <div className="mx-auto max-w-6xl p-6">
      <Link to="/campaigns" className="mb-3 inline-flex items-center gap-1 text-xs text-muted hover:text-ink">
        <ChevronLeft size={14} /> Campaigns
      </Link>
      {isLoading && <Skeleton className="h-24" />}
      {error && <EmptyState title="Campaign not found" hint={(error as Error).message} />}
      {data && (
        <>
          <div className="mb-4 flex items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">{data.title}</h1>
            <StatusTag status={data.status} />
            {data.gate.label && <span className="num rounded bg-sunken px-2 py-0.5 text-xs text-muted">gate {data.gate.label}</span>}
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label="Proposed" value={data.funnel.proposed} />
            <Stat label="Selected" value={data.funnel.selected} />
            <Stat label="Tested" value={data.funnel.tested} />
            <Stat label="Claimed" value={data.funnel.claimed} />
            <Stat label="Refuted" value={data.funnel.refuted} />
            <Stat label="Abstained" value={data.funnel.abstained} />
          </div>
        </>
      )}
    </div>
  )
}
