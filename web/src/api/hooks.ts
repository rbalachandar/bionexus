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
    refetchInterval: 4_000,
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
