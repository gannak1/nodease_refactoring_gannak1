import { InputSchema, OutputSchema } from '../../types/Deployment';

export type DeploymentStep = 'input' | 'success' | 'error';

export interface DeploymentResult {
  success: boolean;
  deploymentId?: string;
  appId?: string;
  url_slug?: string | null;
  auth_secret?: string | null;
  version?: number;
  webAppUrl?: string;
  internalRunUrl?: string;
  embedUrl?: string;
  isWorkflowNode?: boolean;
  input_schema?: InputSchema | null;
  output_schema?: OutputSchema | null;
  message?: string; // Error message
  cronExpression?: string; // Schedule trigger용
  timezone?: string; // Schedule trigger용
  graph_snapshot?: any; // 노드 타입 확인용 (webhookTrigger 등)
}
