import {
  DeploymentBrowserAccessPolicy,
  InputSchema,
  OutputSchema,
} from '../../types/Deployment';

export type DeploymentStep = 'input' | 'optimization' | 'success' | 'error';

export type DeploymentOptimizationNode = {
  id: string;
  title: string;
};

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
  message?: string; // Error or non-blocking preflight warning
  cronExpression?: string; // Schedule trigger용
  timezone?: string; // Schedule trigger용
  graph_snapshot?: any; // 노드 타입 확인용 (webhookTrigger 등)
  browser_access_policy?: DeploymentBrowserAccessPolicy | null;
}
