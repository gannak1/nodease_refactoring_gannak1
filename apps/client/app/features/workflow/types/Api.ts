// API 요청 & 응답과 관련된 타입들을 정의합니다.

export interface WorkflowCreateRequest {
  app_id: string;
}

export interface WorkflowResponse {
  id: string;
  app_id: string;
  created_at: string;
  updated_at: string;
}

export type WorkflowPermissionSource =
  | {
      type: 'team';
      team_id: string;
      team_name: string;
      auth_state: string;
    }
  | {
      type: 'user';
      user_id: string;
      user_name?: string | null;
      auth_state: string;
    };

export interface WorkflowPermissionSummary {
  workflow_id: string;
  organization_id?: string | null;
  auth_state: string;
  can_read: boolean;
  can_write: boolean;
  can_execute: boolean;
  can_deploy: boolean;
  can_manage: boolean;
}

export interface WorkflowPermissionResponse extends WorkflowPermissionSummary {
  sources: WorkflowPermissionSource[];
}

export interface WorkflowCompareVariant {
  label: 'A' | 'B';
  value: string;
  status: 'success' | 'failed';
  error?: string | null;
  outputs?: Record<string, any>;
  node_output?: Record<string, any> | null;
  model?: string | null;
  total_tokens?: number;
  total_cost?: number;
  latency_ms?: number;
}

export interface WorkflowCompareResponse {
  workflow_id: string;
  node_id: string;
  compare_type: 'model' | 'prompt';
  variants: WorkflowCompareVariant[];
}

export interface CostOptimizerAvailabilityResponse {
  available: boolean;
  reason?: string | null;
  workflow_id: string;
  node_id: string;
  node_type: string;
  permission: {
    can_compare: boolean;
    can_apply: boolean;
    required_auth_state: string;
  };
}

export interface CostOptimizerBaselineRow {
  baseline_id: string;
  baseline_source: string;
  source_workflow_node_run_id: string;
  workflow_run_id: string;
  workflow_id: string;
  node_id: string;
  run_started_at: string;
  workflow_run_status: string;
  node_status: string;
  model: string;
  cost: number;
  total_tokens: number;
  latency_ms: number;
  input_available: boolean;
  output_available: boolean;
  usage_available: boolean;
  trace_available: boolean;
  compare_available: boolean;
  unavailable_reason?: string | null;
  input_preview: string;
  output_preview: string;
  input?: unknown;
  output?: unknown;
  has_trace: boolean;
  node_options?: Record<string, unknown>;
  downstream_compatibility?: CostOptimizerDownstreamCompatibility;
}

export interface CostOptimizerLatestBaselineResponse {
  baseline: CostOptimizerBaselineRow;
}

export interface CostOptimizerBaselineListResponse {
  total: number;
  limit: number;
  offset: number;
  items: CostOptimizerBaselineRow[];
}

export interface CostOptimizerBaselineListParams {
  q?: string;
  model?: string;
  date_from?: string;
  date_to?: string;
  sort?: string;
  compare_available?: boolean;
  limit?: number;
  offset?: number;
}

export interface CostOptimizerCandidateRequest {
  label?: string;
  model_id: string;
  fallback_model_id?: string | null;
  task_type?: string | null;
  system_prompt?: string | null;
  user_prompt?: string | null;
  assistant_prompt?: string | null;
  referenced_variables?: Array<{
    name: string;
    value_selector: string[];
  }>;
  parameters?: Record<string, unknown>;
  output_format?: {
    type: 'text' | 'json';
    schema?: Record<string, unknown> | null;
  };
  knowledge?: {
    knowledge_base_ids?: string[];
    top_k?: number;
    score_threshold?: number;
    dedupe_retrieved_context?: boolean;
    retrieved_context_max_chars?: number | null;
    retrieved_context_compression?: 'off' | 'light' | 'strong';
    answer_grounding_check?: 'off' | 'basic' | 'strict';
  };
}

export interface CostOptimizerCompareRequest {
  baseline_id: string;
  candidate: CostOptimizerCandidateRequest;
}

export interface CostOptimizerApplyRequest {
  comparison_id: string;
  candidate_settings: CostOptimizerCandidateRequest;
  acknowledge_downstream_warning?: boolean;
}

export interface CostOptimizerDownstreamCompatibility {
  state: string;
  label?: string;
  message?: string;
  baseline_downstream_hash?: string | null;
  current_downstream_hash?: string | null;
  first_consumer_status?: string | null;
  contract_check?: {
    status?: string | null;
    checked_node_ids?: string[];
    warnings?: string[];
  };
}

export interface CostOptimizerUsageSummary extends Record<string, unknown> {
  model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  cost?: number | null;
  total_cost?: number | null;
  cost_unavailable?: boolean;
  latency_ms?: number | null;
  status?: string | null;
}

export interface CostOptimizerCompareResponse {
  comparison_id: string;
  workflow_id: string;
  node_id: string;
  baseline: {
    baseline_id: string;
    label?: string;
    settings?: Record<string, unknown>;
    input?: unknown;
    output?: unknown;
    usage?: CostOptimizerUsageSummary;
    trace?: Record<string, unknown>;
  };
  candidate: {
    label?: string;
    settings?: Record<string, unknown>;
    status: 'success' | 'failed' | 'schema_failed' | string;
    output?: unknown;
    usage?: CostOptimizerUsageSummary;
    schema_validation?: {
      status?: string | null;
      errors?: unknown[];
    };
    latency_ms?: number | null;
    trace?: Record<string, unknown>;
    error_message?: string | null;
  };
  diff?: Record<string, unknown>;
  downstream_compatibility?: CostOptimizerDownstreamCompatibility;
}

export interface CostOptimizerApplyResponse {
  workflow_id: string;
  node_id: string;
  applied: boolean;
  downstream_compatibility: CostOptimizerDownstreamCompatibility;
  updated_draft_revision?: string | number | null;
}

export interface CostOptimizerExperimentListParams {
  baseline_id?: string;
  date_from?: string;
  date_to?: string;
  created_by?: string;
  candidate_status?: 'success' | 'failed' | 'schema_failed' | 'running' | string;
  model?: string;
  is_applied?: boolean;
  schema_status?: 'not_checked' | 'pass' | 'failed' | string;
  downstream_state?: 'compatible' | 'warning' | 'incompatible' | 'unknown' | string;
  limit?: number;
  offset?: number;
}

export interface CostOptimizerCandidateSummary {
  candidate_id: string;
  name?: string | null;
  status?: string | null;
  model_id?: string | null;
  fallback_model_id?: string | null;
  task_type?: string | null;
  total_cost?: number | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  latency_ms?: number | null;
  output_available?: boolean;
  output?: unknown;
  output_preview?: string | null;
  schema_status?: string | null;
  downstream_state?: string | null;
  is_applied?: boolean;
  created_at?: string | null;
}

export interface CostOptimizerExperimentBaselineSummary {
  baseline_id?: string | null;
  workflow_run_id?: string | null;
  model?: string | null;
  cost?: number | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  latency_ms?: number | null;
  output_available?: boolean;
  output?: unknown;
  output_preview?: string | null;
  output_format?: unknown;
  max_tokens?: number | null;
  temperature?: number | null;
}

export interface CostOptimizerExperimentSummary {
  experiment_id: string;
  workflow_id: string;
  app_id?: string | null;
  node_id: string;
  baseline_node_run_id?: string | null;
  baseline_workflow_run_id?: string | null;
  status?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  baseline_summary?: CostOptimizerExperimentBaselineSummary;
  usage_summary?: CostOptimizerUsageSummary;
  candidates: CostOptimizerCandidateSummary[];
}

export interface CostOptimizerExperimentListResponse {
  total: number;
  limit: number;
  offset: number;
  items: CostOptimizerExperimentSummary[];
}

// 로그 관련 타입 (Backend Schemas와 일치)
export interface WorkflowNodeRun {
  id: string;
  node_id: string;
  node_type: string;
  status: string;
  inputs?: Record<string, any>;
  process_data?: Record<string, any>; // 노드 옵션 스냅샷 (실행 시점 설정)
  outputs?: Record<string, any>;
  error_message?: string;
  started_at: string;
  finished_at?: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  user_id: string;
  status: string;
  trigger_mode: 'manual' | 'scheduler' | 'api' | 'app' | 'webhook';
  inputs?: Record<string, any>;
  outputs?: Record<string, any>;
  error_message?: string;
  started_at: string;
  finished_at?: string;
  duration?: number;
  workflow_version?: number;
  total_tokens?: number;
  total_cost?: number;
  node_runs?: WorkflowNodeRun[];
}

// Dashboard Stats Types
export interface StatsSummary {
  totalRuns: number;
  successRate: number;
  avgDuration: number;
  totalCost: number;
  avgTokenPerRun: number;
  avgCostPerRun: number;
}

export interface DailyRunStat {
  date: string;
  count: number;
  total_cost: number;
  total_tokens: number;
}

export interface RunCostStat {
  run_id: string;
  started_at: string;
  total_tokens: number;
  total_cost: number;
}

export interface FailureStat {
  node_id: string;
  node_name: string;
  count: number;
  reason: string;
  rate: string;
}

export interface RecentFailure {
  run_id: string;
  failed_at: string; // ISO date
  node_id: string;
  error_message: string;
}

export interface DashboardStatsResponse {
  summary: StatsSummary;
  runsOverTime: DailyRunStat[];
  minCostRuns: RunCostStat[];
  maxCostRuns: RunCostStat[];
  failureAnalysis: FailureStat[];
  recentFailures: RecentFailure[];
}

export interface WorkflowRunListResponse {
  total: number;
  items: WorkflowRun[];
}

export interface LLMTrace {
  id: string;
  workflow_id?: string | null;
  workflow_run_id: string;
  node_id?: string | null;
  model_id?: string | null;
  model_name?: string | null;
  provider?: string | null;
  credential_id?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost?: number | null;
  latency_ms?: number | null;
  status: string;
  created_at: string;
}

export interface LLMTraceListResponse {
  total: number;
  limit: number;
  offset: number;
  items: LLMTrace[];
}

export interface TopExpensiveModel {
  model_name: string;
  provider_name: string;
  total_cost: number;
  total_tokens: number;
}
