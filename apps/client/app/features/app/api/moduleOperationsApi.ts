import { apiClient } from '@/lib/apiClient';
import type { WorkflowPermissionResponse } from '../../workflow/types/Api';
import type { AppIcon } from './appApi';

export type ModulePermissionSource = {
  type: 'team' | 'user';
  team_id?: string;
  team_name?: string;
  user_id?: string;
  user_name?: string;
  auth_state: string;
};

export type ModuleRunState =
  | 'running'
  | 'success'
  | 'failed'
  | 'not_started'
  | 'unavailable';

export type ModuleOperationAppSummary = {
  id: string;
  name: string;
  description?: string;
  icon?: AppIcon;
  workflow_id?: string;
  owner_name?: string;
  created_at: string;
  updated_at: string;
};

export type ModuleOperationDeployment = {
  state: 'active' | 'inactive' | 'undeployed';
  deployment_id?: string;
  type?: string;
  is_active?: boolean;
};

export type ModuleOperationRow = {
  app: ModuleOperationAppSummary;
  permission?: WorkflowPermissionResponse;
  permissionStatus: ModulePermissionStatus;
  permissionSources: ModulePermissionSource[];
  permissionError?: string;
  deployment: ModuleOperationDeployment;
  deploymentState: ModuleOperationDeployment['state'];
  latestRun: {
    state: ModuleRunState;
    started_at?: string;
    finished_at?: string;
    error_message?: string;
  };
  dataQuality: {
    permissionSourcesUnavailable: boolean;
    latestRunUnavailable: boolean;
  };
};

export type ModulePermissionStatus = 'loaded' | 'failed' | 'not_available';

type OperationsApiRow = {
  app: ModuleOperationAppSummary;
  permission?: WorkflowPermissionResponse;
  permission_status?: ModulePermissionStatus;
  permissionStatus?: ModulePermissionStatus;
  permission_error?: string;
  permissionError?: string;
  permission_sources?: ModulePermissionSource[];
  permissionSources?: ModulePermissionSource[];
  deployment?: ModuleOperationDeployment;
  latest_run?: ModuleOperationRow['latestRun'];
  latestRun?: ModuleOperationRow['latestRun'];
};

const normalizeOperationsApiRow = (row: OperationsApiRow): ModuleOperationRow => {
  const app = row.app;
  const permissionSources = row.permission_sources || row.permissionSources || [];
  const deployment = row.deployment || { state: 'undeployed' };
  const latestRun = row.latest_run ||
    row.latestRun || {
      state: deployment.deployment_id ? 'unavailable' : 'not_started',
    };

  return {
    app,
    permission: row.permission,
    permissionStatus:
      row.permission_status ||
      row.permissionStatus ||
      (row.permission ? 'loaded' : 'not_available'),
    permissionSources,
    permissionError: row.permission_error || row.permissionError,
    deployment,
    deploymentState: deployment.state,
    latestRun,
    dataQuality: {
      permissionSourcesUnavailable: permissionSources.length === 0,
      latestRunUnavailable: latestRun.state === 'unavailable',
    },
  };
};

export const moduleOperationsApi = {
  listModuleOperations: async (): Promise<ModuleOperationRow[]> => {
    const response = await apiClient.get<OperationsApiRow[]>('/apps/operations', {
      params: { limit: 100, offset: 0 },
    });
    return response.data.map(normalizeOperationsApiRow);
  },
};
