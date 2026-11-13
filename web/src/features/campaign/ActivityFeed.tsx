import { Activity, Atom, Ban, ClipboardCheck, Flag, ListChecks, Scale, Target } from 'lucide-react'
import { useActivity } from '../../api/hooks'
import { Skeleton } from '../../ui/Card'
import { ago } from './format'

const ICON: Record<string, typeof Activity> = {
  run: Activity, make: Atom, verdict: Scale, gate: Ban, round: Flag, review: ClipboardCheck, batch: ListChecks, problem: Target,
}

export function ActivityFeed({ id }: { id: string }) {
  const { data, isLoading } = useActivity(id, 12)
  if (isLoading) return <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-5" />)}</div>
  if (!data?.length) return <p className="p-6 text-center text-sm text-faint">Nothing has happened yet.</p>
  return (
    <ul className="divide-y divide-line" aria-live="polite">
      {data.map((a, i) => {
        const Icon = ICON[a.kind] ?? Activity
        return (
          <li key={i} className="flex items-start gap-2.5 px-4 py-2">
            <Icon size={14} className="mt-0.5 shrink-0 text-faint" aria-hidden />
            <span className="min-w-0 flex-1 text-[13px]">{a.text}</span>
            <time className="num shrink-0 text-[11px] text-faint">{ago(a.ts)}</time>
          </li>
        )
      })}
    </ul>
  )
}
