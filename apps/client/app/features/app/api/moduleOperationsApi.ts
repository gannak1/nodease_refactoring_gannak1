import axios from 'axios';
import { apiClient } from '@/lib/apiClient';
import { appApi, type App } from './appApi';
import type {
  WorkflowPermissionResponse,
  WorkflowRun,
} from '../../workflow/types/Api';

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

export type ModuleOperationRow = {
  app: App;
  permission?: WorkflowPermissionResponse;
  permissionStatus: ModulePermissionStatus;
  permissionSources: ModulePermissionSource[];
  permissionError?: string;
  deploymentState: 'active' | 'inactive' | 'undeployed';
  latestRun: {
    state: ModuleRunState;
    started_at?: string;
    finished_at?: string;
    error_message?: string;
  };
  dataQuality: {
    source: 'operations-api' | 'composed-adapter';
    permissionSourcesUnavailable: boolean;
    latestRunUnavailable: boolean;
  };
};

export type ModulePermissionStatus = 'loaded' | 'failed' | 'not_available';

type OperationsApiRow = {
  app: App;
  permission?: WorkflowPermissionResponse;
  permission_status?: ModulePermissionStatus;
  permissionStatus?: ModulePermissionStatus;
  permission_error?: string;
  permissionError?: string;
  permission_sources?: ModulePermissionSource[];
  permissionSources?: ModulePermissionSource[];
  deployment?: { state?: ModuleOperationRow['deploymentState'] };
  latest_run?: ModuleOperationRow['latestRun'];
  latestRun?: ModuleOperationRow['latestRun'];
};

const deploymentStateOf = (app: App): ModuleOperationRow['deploymentState'] => {
  if (!app.active_deployment_id) return 'undeployed';
  return app.active_deployment_is_active ? 'active' : 'inactive';
};

const normalizeRunState = (status?: string): ModuleRunState => {
  const normalized = status?.toLowerCase();
  if (!normalized) return 'not_started';
  if (['running', 'pending', 'queued', 'in_progress'].includes(normalized)) {
    return 'running';
  }
  if (['success', 'succeeded', 'completed'].includes(normalized)) {
    return 'success';
  }
  if (['failed', 'failure', 'error'].includes(normalized)) {
    return 'failed';
  }
  return 'unavailable';
};

const latestRunFromApi = (
  run?: WorkflowRun,
): ModuleOperationRow['latestRun'] | undefined => {
  if (!run) return undefined;

  return {
    state: normalizeRunState(run.status),
    started_at: run.started_at,
    finished_at: run.finished_at,
    error_message: run.error_message,
  };
};

const composeOperationRow = async (app: App): Promise<ModuleOperationRow> => {
  let permission: WorkflowPermissionResponse | undefined;
  let permissionStatus: ModuleOperationRow['permissionStatus'] =
    'not_available';
  let permissionError: string | undefined;
  let latestRun: ModuleOperationRow['latestRun'] = {
    state: app.active_deployment_id ? 'unavailable' : 'not_started',
  };
  let latestRunUnavailable = Boolean(app.active_deployment_id);

  if (app.workflow_id) {
    try {
      const response = await apiClient.get<WorkflowPermissionResponse>(
        `/workflows/${app.workflow_id}/permissions/me`,
      );
      permission = response.data;
      permissionStatus = 'loaded';
    } catch {
      permissionStatus = 'failed';
      permissionError = '권한 확인 실패';
    }

    try {
      const response = await apiClient.get<{ items: WorkflowRun[] }>(
        `/workflows/${app.workflow_id}/runs`,
        { params: { page: 1, limit: 1 } },
      );
      const apiLatestRun = latestRunFromApi(response.data.items[0]);
      if (apiLatestRun) {
        latestRun = apiLatestRun;
        latestRunUnavailable = false;
      } else {
        latestRun = { state: 'not_started' };
        latestRunUnavailable = false;
      }
    } catch {
      latestRun = { state: 'unavailable' };
      latestRunUnavailable = true;
    }
  }

  return {
    app,
    permission,
    permissionStatus,
    permissionSources: [],
    permissionError,
    deploymentState: deploymentStateOf(app),
    latestRun,
    dataQuality: {
      source: 'composed-adapter',
      permissionSourcesUnavailable: true,
      latestRunUnavailable,
    },
  };
};

const normalizeOperationsApiRow = (row: OperationsApiRow): ModuleOperationRow => {
  const app = row.app;
  const permissionSources = row.permission_sources || row.permissionSources || [];
  const latestRun = row.latest_run ||
    row.latestRun || {
      state: app.active_deployment_id ? 'unavailable' : 'not_started',
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
    deploymentState: row.deployment?.state || deploymentStateOf(app),
    latestRun,
    dataQuality: {
      source: 'operations-api',
      permissionSourcesUnavailable: permissionSources.length === 0,
      latestRunUnavailable: latestRun.state === 'unavailable',
    },
  };
};

export const moduleOperationsApi = {
  listModuleOperations: async (): Promise<ModuleOperationRow[]> => {
    if (process.env.NEXT_PUBLIC_ENABLE_APPS_OPERATIONS_API === 'true') {
      try {
        const response = await apiClient.get<OperationsApiRow[]>(
          '/apps/operations',
        );
        if (Array.isArray(response.data)) {
          return response.data.map(normalizeOperationsApiRow);
        }
      } catch (error) {
        if (!axios.isAxiosError(error)) {
          throw error;
        }

        const status = error.response?.status ?? 0;
        const canFallbackToComposedAdapter = [400, 404, 405, 422, 501].includes(
          status,
        );
        if (!canFallbackToComposedAdapter) {
          throw error;
        }
      }
    }

    const apps = await appApi.listApps();
    return Promise.all(apps.map(composeOperationRow));
  },
};
