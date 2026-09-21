// Thin typed client over the FastAPI backend (P0.5 contract).

export interface ProgramLink {
  eid: string
  role: 'campaign' | 'leaf'
  campaign_root: string | null
  question: string | null
  status: string
  live: boolean
}

export interface ProgramOut {
  slug: string
  name: string
  objective: string | null
  gate_summary: string | null
  modality: string | null
  mode: string
  links: ProgramLink[]
  tally: Record<string, number>
}

export interface TreeLeafStat {
  runs: number
  hyp: number
  statement: string
  ok: number
  blocked: string | null
  pids: string[]
}

export interface ProblemTreeOut {
  root_id: string
  objective: string
  nodes: { id: string; parent: string | null; objective: string; status: string; metric: string | null; direction: string | null; gate: number | null }[]
  alloc: Record<string, number>
  leaf_stats: Record<string, TreeLeafStat>
  rollup: Record<string, string>
  has_rollup: boolean
  branch: string
  linked_program: string | null
  is_linked: boolean
}

export interface Workspace {
  programs: ProgramOut[]
  trees: ProblemTreeOut[]
  groups: Record<'autonomous' | 'guided', { eid: string; question: string; status: string }[]>
  archived: { eid: string; question: string }[]
}

export interface PipelineCard {
  key: string
  candidate: string | null
  head: string
  statement: string
  predicted: string | null
  mechanism: string | null
  citation: string | null
  citation_status: string | null
  citation_detail: string | null
  refutation_condition: string | null
  gate_label: string | null
  threshold: number | null
  verdict: {
    status: string
    observed: number | null
    ci: number[] | null
    unit_label: string
    margin: string
  } | null
  stage: string
  state: 'confirmed' | 'validated' | 'inconclusive' | 'refuted' | 'refused' | 'in_lab' | 'selected' | 'not_selected' | 'proposed'
  round: number | null
  selected: boolean
}

export interface ExperimentDetail {
  id: string
  question: string
  status: string
  registry_status: string
  updated_at: number
  agent: { autonomy: string; problem_id: string | null; log_path: string | null }
  branch: string | null
  record_count: number
  program: { slug: string; name: string; gate: { metric: string; direction: string; value: number; unit: string; symbol: string }; modality: string | null; mode: string } | null
  spec: { objective: string; k: number; rounds: number; autonomy: string; hypothesis_source: string; n_candidates: number; modality: string | null; constraints: { name: string; description: string }[] } | null
  objective: string
  constraints: { name: string; description: string }[]
  success_metric: string | null
  counts: Record<string, number>
  rounds: { round: number; candidates: string[]; verdicts: Record<string, string> }[]
  cards: PipelineCard[]
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

export const api = {
  workspace: () => get<Workspace>('/api/programs'),
  experiment: (eid: string) => get<ExperimentDetail>(`/api/experiments/${eid}`),
  trace: (eid: string) =>
    get<{ lines: string[]; truncated: boolean }>(`/api/experiments/${eid}/trace`),
  record: (eid: string) => get<Record<string, unknown>>(`/api/experiments/${eid}/record`),
  health: () => get<{ ok: boolean }>('/api/system/health'),
}
