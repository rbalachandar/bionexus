import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

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
