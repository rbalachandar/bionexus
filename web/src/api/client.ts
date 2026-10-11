// Thin typed client over the FastAPI backend (P0.5 contract).

export interface ProgramLink {
  eid: string
  role: 'campaign' | 'leaf'
  campaign_root: string | null
  question: string | null
  status: string
  live: boolean
  runs?: number
  rounds_done?: number
  rounds_planned?: number | null
  verdicts?: { confirmed: number; preliminary?: number; refuted: number; inconclusive: number }
  candidates?: string[]
}

export interface ProgramVerdict {
  status: 'supported' | 'partial' | 'refuted' | 'inconclusive' | 'no-tree'
  reason: string
  leaves: number
  resolved: number
  gate?: { status: string; leaf: string; metric: string } | null
}

export interface ProgramOut {
  slug: string
  pid?: string
  name: string
  objective: string | null
  gate_summary: string | null
  modality: string | null
  mode: string
  fence?: { id: string; name: string;
    installed: boolean; simulated: boolean }[]
  links: ProgramLink[]
  tally: Record<string, number>
  taste?: TasteReport
  verdict?: ProgramVerdict
  policy?: { status: 'active' | 'escalated'; reason: string;
    runs: number; cycles: number; limits: { max_runs: number;
    max_cycles: number } }
  brief?: { text: string; at: number; hash: string;
    actions?: (string | { objective: string; tree: boolean })[];
    conclusion?: string | null;
    launched?: Record<string, string>;
    launched_status?: Record<string, string> }
  tree?: ProblemTreeOut
  trees?: ProblemTreeOut[]
}

export interface TreeLeafStat {
  runs: number
  hyp: number
  statement: string
  ok: number
  blocked: string | null
  pids: string[]
  eid?: string
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
  experiments_total?: number
  programs: ProgramOut[]
  trees: ProblemTreeOut[]
  groups: Record<'autonomous' | 'guided', { eid: string; question: string; status: string
    runs?: number; rounds_done?: number; rounds_planned?: number | null
    verdicts?: { confirmed: number; preliminary?: number; refuted: number; inconclusive: number }
    candidates?: string[] }[]>
  archived: { eid: string; question: string }[]
}

export interface PipelineCard {
  key: string
  candidate: string | null
  head: string
  statement: string
  predicted_by?: { source: string; model?: string;
    policy?: string; note?: string } | null
  predicted: string | null
  rationale?: string | null
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
  sandbox?: { type: string; sandbox_id: string | null;
    policy: Record<string, string | number>;
    execs: number; snapshots: number; forks: number;
    destroyed: boolean } | null
  series?: {
    key: string; kind: string; backend: string; n_members: number
    n_tested?: number; rollup: Record<string, number>; label: string
    members: { candidate: string; verdict: string | null; observed: number | null }[]
    matched_pairs: { a: string; b: string; ic50_a: number; ic50_b: number;
      delta_log10: number; ci95: [number, number] | null;
      fold_a_over_b: number; call: string; cited_cis: boolean }[]
    claim_status?: string | null; claim_reason?: string | null
  }[]
  program: { slug: string; name: string; gate: { metric: string; direction: string; value: number; unit: string; symbol: string }; modality: string | null; mode: string } | null
  spec: { objective: string; k: number; rounds: number; autonomy: string; hypothesis_source: string; n_candidates: number; modality: string | null; constraints: { name: string; description: string }[] } | null
  objective: string
  constraints: { name: string; description: string }[]
  success_metric: string | null
  counts: Record<string, number>
  rounds: { round: number; candidates: string[]; verdicts: Record<string, string> }[]
  cards: PipelineCard[]
  eliminated?: { candidate: string; reason: string; score: number | null }[]
}

export interface TasteReport {
  n: number
  accepted: number
  overall_rate: number
  by_feature: Record<string, { n: number; rate: number | null;
    rate_without: number | null }>
  families: Record<string, { n: number; accepted: number }>
  amendments: string[]
  error?: string
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

async function post<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: 'POST' })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `${path}: ${r.status}`)
  }
  return r.json()
}

export const api = {
  workspace: () => get<Workspace>('/api/programs?include_archived=1'),
  program: (slug: string) => get<ProgramOut>(`/api/programs/${slug}`),
  brief: (slug: string) =>
    post<{ narrative: string }>(`/api/programs/${slug}/brief`),
  launchAction: (slug: string, idx: number, tree = false) =>
    post<{ eid: string; objective: string }>(
      `/api/programs/${slug}/actions/${idx}${tree ? '?tree=true' : ''}`),
  taste: () => get<TasteReport>('/api/taste'),
  experiment: (eid: string) => get<ExperimentDetail>(`/api/experiments/${eid}`),
  trace: (eid: string) =>
    get<{ lines: string[]; truncated: boolean }>(`/api/experiments/${eid}/trace`),
  record: (eid: string) => get<Record<string, unknown>>(`/api/experiments/${eid}/record`),
  health: () => get<{ ok: boolean }>('/api/system/health'),
}
