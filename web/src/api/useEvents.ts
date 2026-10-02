import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

/** Workspace-level live updates: program cards, trees, tallies. The
 * main page used to snapshot once on mount and go stale while campaigns
 * ran; this invalidates on every workspace event (and pairs with a
 * modest refetchInterval as the safety net). */
export function useWorkspaceEvents() {
  const qc = useQueryClient()
  useEffect(() => {
    const es = new EventSource('/api/events?topics=workspace')
    let last = 0
    const invalidate = () => {
      const now = Date.now()
      if (now - last < 2000) return        // throttle bursts
      last = now
      qc.invalidateQueries({ queryKey: ['workspace'] })
      qc.invalidateQueries({ queryKey: ['gov-pill'] })
    }
    for (const kind of ['experiment_added', 'experiment_removed',
      'program_updated', 'program_deleted', 'status', 'updated', 'records'])
      es.addEventListener(kind, invalidate)
    return () => es.close()
  }, [qc])
}

/** Subscribe to SSE topics; invalidate queries on events. */
export function useCampaignEvents(eid: string | undefined, active: boolean) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!eid || !active) return
    const es = new EventSource(`/api/events?topics=campaign:${eid},workspace`)
    const invalidate = () => {
      qc.invalidateQueries({ queryKey: ['experiment', eid] })
      qc.invalidateQueries({ queryKey: ['pipeline', eid] })
      qc.invalidateQueries({ queryKey: ['trace', eid] })
      qc.invalidateQueries({ queryKey: ['record', eid] })
      qc.invalidateQueries({ queryKey: ['workspace'] })
    }
    es.addEventListener('status', (e) => {
      // status flip (e.g. completion): full detail refresh
      qc.invalidateQueries({ queryKey: ['experiment', eid] })
      invalidate()
    })
    es.addEventListener('records', invalidate)
    es.addEventListener('updated', invalidate)
    es.addEventListener('experiment_added', invalidate)
    es.addEventListener('experiment_removed', invalidate)
    return () => es.close()
  }, [eid, active, qc])
}
