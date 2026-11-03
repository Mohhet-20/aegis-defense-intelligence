// Types mirror backend/app/schemas/scenario.py and app/simulation/*. Everything
// here is SIMULATED data; nothing is an observation of the real world.

export type ScenarioStatus = 'draft' | 'ready' | 'archived'
export type RunStatus = 'running' | 'completed' | 'failed'
export type RunKind = 'simulation' | 'sensitivity'

export interface ParamDoc {
  name: string
  type: 'int' | 'float' | 'bool' | 'choice'
  description: string
  default: number | boolean | string | null
  unit: string
  min: number | null
  max: number | null
  choices: string[] | null
}
export interface MetricDoc { name: string; unit: string; description: string; higher_is: string }
export interface SimulatorDoc {
  id: string
  version: string
  title: string
  description: string
  parameters: ParamDoc[]
  metrics: MetricDoc[]
  assumptions: string[]
  limitations: string[]
}
export interface SimulatorsResponse {
  synthetic: true
  simulators: SimulatorDoc[]
  limits: { max_sweep_params: number; max_sweep_values: number; max_repetitions: number; max_total_runs: number; max_generated_records: number }
  not_implemented: string[]
}
export interface TemplateDoc {
  id: string
  title: string
  simulator_id: string
  simulator_version: string
  category: string
  question: string
  assumptions: string[]
  params: Record<string, number | boolean | string>
}

export type ParamValues = Record<string, number | boolean | string>

export interface Scenario {
  id: string
  lineage_id: string
  version: number
  parent_scenario_id: string | null
  title: string
  description: string | null
  question: string | null
  category: string
  template_id: string | null
  simulator_id: string
  simulator_version: string
  params: ParamValues
  assumptions: string[]
  limitations: string[]
  seed: number
  execution_config: { max_seconds?: number }
  status: ScenarioStatus
  investigation_id: string | null
  owner_user_id: string
  latest_summary: { run_id: string; completed_at: string; seed: number; metrics: Metrics } | null
  created_at: string
  updated_at: string
  synthetic: true
  label: string
}

export type Metrics = Record<string, number | null>

export interface RunSummary {
  id: string
  scenario_id: string
  scenario_version: number
  run_kind: RunKind
  status: RunStatus
  simulator_id: string
  simulator_version: string
  seed: number
  error_code: string | null
  error_message: string | null
  retry_of_run_id: string | null
  started_at: string
  completed_at: string | null
  runtime_ms: number | null
  result_sha256: string | null
  synthetic: true
}

export interface DatasetHeader {
  synthetic: boolean
  generator: string
  generator_version: string
  seed: number
  record_count: number
  n_dropped_missing: number
  n_duplicates: number
  n_outliers: number
  limitations: string[]
  content_sha256: string
  params: Record<string, unknown>
}

export interface SummaryStats {
  n: number
  n_undefined: number
  mean: number | null
  sd: number | null
  sem: number | null
  min: number | null
  max: number | null
  p10: number | null
  p50: number | null
  p90: number | null
}
export interface SensitivityPoint { value: number; metric_summary: SummaryStats; metric_means: Record<string, number | null> }
export interface SensitivityResult {
  method: string
  metric: string
  metric_unit: string
  repetitions: number
  seeds: number[]
  total_runs: number
  limits: { max_params: number; max_values: number; max_reps: number; max_total_runs: number }
  baseline_params: ParamValues
  baseline_summary: SummaryStats
  parameters: { param: string; unit: string; points: SensitivityPoint[]; effect_range: number | null; exceeds_baseline_seed_variability: boolean | null }[]
  ranking: { param: string; effect_range: number; exceeds_baseline_seed_variability: boolean | null }[]
  interpretation: string[]
  assumptions: string[]
  limitations: string[]
  label: string
}

export interface SimulationResult {
  label: string
  synthetic: true
  metrics: Metrics
  preview: Record<string, unknown>[]
  notes: string[]
  dataset_header: DatasetHeader | null
}

export interface RunDetail extends RunSummary {
  config_snapshot: Record<string, unknown> & { params: ParamValues; assumptions: string[]; limitations: string[]; sensitivity?: { sweep: { param: string; values: number[] }[]; repetitions: number; metric: string } }
  dataset_ref: Record<string, unknown> | null
  results: (SimulationResult & Partial<SensitivityResult>) | null
  idempotency_key: string | null
  requested_by_user_id: string
  idempotent_replay: boolean
  label: string
}

export interface ComparisonMetric {
  name: string
  unit: string
  baseline: number | null
  alternative: number | null
  absolute_diff: number | null
  relative_diff: number | null
  comparable: boolean
  reason: string | null
}
export interface ComparisonAlternative {
  run_id: string
  label: string | null
  warnings: string[]
  parameter_changes: { param: string; baseline: unknown; alternative: unknown }[]
  held_constant: { param: string; value: unknown }[]
  seed_changed: boolean
  comparable: boolean
  attribution: { status: 'identical_inputs' | 'single_parameter' | 'multiple_inputs' | 'incomparable'; statement: string }
  metrics: ComparisonMetric[]
}
export interface Comparison {
  baseline: { run_id: string; label: string | null }
  alternatives: ComparisonAlternative[]
  assumptions: string[]
  limitations: string[]
  caveats: string[]
  synthetic: true
  label: string
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface SweepEntryInput { param: string; values?: number[]; min?: number; max?: number; steps?: number }
export interface ValidateResult { valid: boolean; errors: { param: string; message: string }[]; params: ParamValues | null; assumptions?: string[]; limitations?: string[] }
