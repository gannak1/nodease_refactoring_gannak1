export type DeploymentType =
  | 'api'
  | 'widget'
  | 'chatbot'
  | 'webapp'
  | 'mcp'
  | 'workflow_node'
  | 'schedule'
  | 'webhook';

export type DeploymentPreflightStatus = 'passed' | 'warning' | 'blocked';
export type DeploymentPreflightAudience =
  | 'anonymous_public'
  | 'authenticated_user'
  | 'workflow_node_inherited';

// 입력 변수 스키마 타입
export interface InputVariable {
  name: string;
  type: string;
  label: string;
  required?: boolean;
}

export interface InputSchema {
  variables: InputVariable[];
}

// 출력 변수 스키마 타입
export interface OutputVariable {
  variable: string;
  label: string;
}

export interface OutputSchema {
  outputs: OutputVariable[];
}

export interface DeploymentBase {
  type: DeploymentType;
  url_slug?: string;
  description?: string | null;
  config?: Record<string, any>;
  is_active: boolean;
}

export interface DeploymentCreate extends DeploymentBase {
  app_id: string;
  graph_snapshot?: Record<string, any>;
  auth_secret?: string;
}

export interface DeploymentPreflightRequest extends DeploymentBase {
  app_id: string;
  graph_snapshot?: Record<string, any>;
  audience?: DeploymentPreflightAudience;
}

export interface DeploymentPreflightRequiredAction {
  action: string;
  label: string;
}

export interface DeploymentPreflightResponse {
  status: DeploymentPreflightStatus;
  audience: DeploymentPreflightAudience;
  safe_summary: {
    blocked_reason?: string | null;
    affected_node_count: number;
    affected_kb_count_bucket: string;
  };
  required_actions: DeploymentPreflightRequiredAction[];
  warnings: string[];
  nodes: Array<{
    node_id?: string | null;
    node_type: string;
    status: DeploymentPreflightStatus;
    reason_codes: string[];
    knowledge_base_count_bucket: string;
  }>;
}

export interface DeploymentResponse extends DeploymentBase {
  id: string;
  app_id: string;
  version: number;
  auth_secret?: string;
  created_by: string;
  created_at: string;
  graph_snapshot: Record<string, any>;
  input_schema?: InputSchema | null;
  output_schema?: OutputSchema | null;
}

export interface DeploymentRunInfoResponse {
  deployment_id: string;
  app_id: string;
  workflow_id: string;
  name: string;
  version: number;
  description?: string;
  type: DeploymentType;
  input_schema?: InputSchema | null;
  output_schema?: OutputSchema | null;
}
