import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { api, unwrap } from './v1'

export const useSystemStatus = () =>
  useQuery({
    queryKey: ['system-status'],
    queryFn: () => unwrap(api.GET('/api/v1/system/status')),
    refetchInterval: 10_000,
  })

export const useCampaigns = (opts?: { program?: string; status?: string }) =>
  useQuery({
    queryKey: ['campaigns', opts],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns', { params: { query: opts } })),
    refetchInterval: 8_000,
  })

export const useCampaign = (id: string) =>
  useQuery({
    queryKey: ['campaign', id],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}', { params: { path: { eid: id } } })),
    // poll fast while the campaign is live, slowly once it has settled
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2_000 : 10_000),
  })

export const useActivity = (id: string, limit = 25) =>
  useQuery({
    queryKey: ['activity', id, limit],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}/activity', { params: { path: { eid: id }, query: { limit } } })),
    refetchInterval: 4_000,
  })

export const useHypothesis = (id: string, hid: string | null) =>
  useQuery({
    queryKey: ['hypothesis', id, hid],
    enabled: !!hid,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}/hypotheses/{hid}', { params: { path: { eid: id, hid: hid! } } })),
  })

export const useCurves = (id: string, hid: string | null) =>
  useQuery({
    queryKey: ['curves', id, hid],
    enabled: !!hid,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}/hypotheses/{hid}/curves', { params: { path: { eid: id, hid: hid! } } })),
  })

/** Halt/resume (legacy endpoint until the v1 governance resource lands). */
export function useHalt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { halted: boolean; reason?: string }) => {
      const r = await fetch('/api/halt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(v),
      })
      if (!r.ok) throw new Error(`halt: ${r.status}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system-status'] }),
  })
}
