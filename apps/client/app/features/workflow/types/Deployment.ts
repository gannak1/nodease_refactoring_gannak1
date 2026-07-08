export type DeploymentType =
  | 'api'
  | 'widget'
  | 'chatbot'
  | 'webapp'
  | 'workflow_node'
  | 'schedule'
  | 'webhook';

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
