export type Severity = "low" | "medium" | "high" | "critical";
export type Verdict = "PASS" | "BLOCK";

export interface VersionInfo {
  id: string;
  label: string;
  model: string;
  is_published: boolean;
  created_at: string;
  parent_version_id: string | null;
  system_prompt: string;
  suite_results: number;
  suite_passed: number;
}

export interface Span {
  name: string;
  type: "llm" | "tool" | "retrieval";
  start_ms: number;
  end_ms: number;
  model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  cost_usd?: number | null;
  attributes?: Record<string, unknown>;
}

export interface RunSummary {
  id: string;
  agent_version_id: string;
  version_label: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  latency_ms: number;
  total_cost_usd: number;
  span_count: number;
  ground_truth_ref: string | null;
  created_at: string;
}

export interface RunDetail extends Omit<RunSummary, "span_count"> {
  spans: Span[];
}

export interface EvalCase {
  id: string;
  title: string;
  severity: Severity;
  status: "active" | "muted";
  input: Record<string, unknown>;
  context_snapshot: Record<string, unknown>;
  rubric: string;
  reference_behavior: string;
  first_failed_label: string | null;
  fixed_in_label: string | null;
  ground_truth_source?: string | null;
  result_count: number;
  created_at: string;
}

export interface EvalResult {
  id: string;
  eval_case_id: string;
  agent_version_id: string;
  version_label?: string;
  passed: boolean;
  score: number;
  judge_rationale: string;
  actual_output: Record<string, unknown>;
  from_cache: boolean;
  created_at: string;
}

export interface EvalCaseDetail extends Omit<EvalCase, "result_count" | "ground_truth_source"> {
  results: EvalResult[];
}

export interface GateRunRecord {
  id: string;
  candidate_version_id: string;
  baseline_version_id: string;
  candidate_label: string;
  baseline_label: string;
  total_cases: number;
  passed_count: number;
  failed_count: number;
  regressed_case_ids: string[];
  newly_fixed_case_ids: string[];
  verdict: Verdict;
  created_at: string;
}

export interface Overview {
  total_runs: number;
  total_cases: number;
  critical_cases: number;
  suite_pass_rate: number | null;
  published_version: string | null;
  last_gate: GateRunRecord | null;
  gate_runs: GateRunRecord[];
  version_pass_rates: { label: string; pass_rate: number; results: number }[];
  p95_latency_ms: number;
  avg_cost_usd: number;
}

export interface DiffField {
  field: string;
  baseline: unknown;
  candidate: unknown;
  changed: boolean;
}

export interface CaseDiff {
  case: {
    id: string;
    title: string;
    severity: Severity;
    rubric: string;
    reference_behavior: string;
    input: Record<string, unknown>;
    context_snapshot: Record<string, unknown>;
  };
  baseline: { label: string; passed: boolean; rationale: string };
  candidate: { label: string; passed: boolean; rationale: string };
  fields: DiffField[];
}

export interface GateStreamCase {
  index: number;
  case_id: string;
  title: string;
  severity: Severity;
  baseline_passed: boolean | null;
  candidate_passed: boolean;
  score: number;
  rationale: string;
  from_cache: boolean;
  kind: "regression" | "newly_fixed" | "still_passing" | "still_failing" | "new_case";
}

export interface GateStreamVerdict {
  verdict: Verdict;
  passed_count: number;
  failed_count: number;
  total_cases: number;
  regressed: string[];
  newly_fixed: string[];
  published: boolean;
  publish_attempted: boolean;
  gate_run_id: string;
}
