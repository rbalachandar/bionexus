import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import type { Schemas } from './v1'
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

/** Halt / resume all agents. The actor is the authenticated person, server-side. */
export function useHalt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { halted: boolean; reason?: string }) =>
      unwrap(api.POST('/api/v1/halt', { body: { halted: v.halted, reason: v.reason ?? '' } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['system-status'] }),
  })
}

export const useToday = () =>
  useQuery({
    queryKey: ['today'],
    queryFn: () => unwrap(api.GET('/api/v1/today')),
    refetchInterval: 6_000,
  })

export const useProgram = (slug: string) =>
  useQuery({
    queryKey: ['program', slug],
    queryFn: () => unwrap(api.GET('/api/v1/programs/{slug}', { params: { path: { slug } } })),
    refetchInterval: 6_000,
  })

export const useInbox = (status: 'pending' | 'all' = 'pending') =>
  useQuery({
    queryKey: ['inbox', status],
    queryFn: () => unwrap(api.GET('/api/v1/inbox', { params: { query: { status } } })),
    refetchInterval: 4_000,
  })

export const useAgents = (id: string) =>
  useQuery({
    queryKey: ['agents', id],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}/agents', { params: { path: { eid: id } } })),
    refetchInterval: 8_000,
  })

export const useTrace = (id: string, actor: string | null) =>
  useQuery({
    queryKey: ['trace', id, actor],
    enabled: !!actor,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{eid}/provenance', { params: { path: { eid: id }, query: { actor: actor!, limit: 500 } } })),
  })

/** Refresh everything a decision can change. */
function useRefresh() {
  const qc = useQueryClient()
  return () => ['inbox', 'campaign', 'campaigns', 'today', 'program', 'activity', 'hypothesis', 'agents', 'system-status']
    .forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
}

export function useDecideApproval() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (v: { id: string; approve: boolean }) =>
      unwrap(api.POST('/api/v1/inbox/{item_id}/decision', { params: { path: { item_id: v.id } }, body: { approve: v.approve, note: '' } })),
    onSuccess: refresh,
  })
}

export function useReviewHypothesis(campaignId: string) {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (v: { hid: string; decision: Schemas['ReviewIn']['decision']; note: string; followUpCampaignId?: string }) =>
      unwrap(api.POST('/api/v1/campaigns/{eid}/hypotheses/{hid}/review', { params: { path: { eid: campaignId, hid: v.hid } }, body: { decision: v.decision, note: v.note, follow_up_campaign_id: v.followUpCampaignId ?? null } })),
    onSuccess: refresh,
  })
}

export function useCreateProgram() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (body: Schemas['ProgramCreate']) => unwrap(api.POST('/api/v1/programs', { body })),
    onSuccess: refresh,
  })
}

export function useLaunchCampaign(slug: string) {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (body: Schemas['CampaignCreate']) =>
      unwrap(api.POST('/api/v1/programs/{slug}/campaigns', { params: { path: { slug } }, body })),
    onSuccess: refresh,
  })
}
