import axios from 'axios';
import {
  attachActiveOrganizationHeader,
  getStoredActiveOrganizationId,
} from '@/lib/activeOrganization';
import { WorkflowDraftRequest } from '../types/Workflow';
import {
  DeploymentCreate,
  DeploymentPreflightRequest,
  DeploymentPreflightResponse,
  DeploymentResponse,
  DeploymentRunInfoResponse,
} from '../types/Deployment';
import {
  WorkflowCreateRequest,
  WorkflowCompareResponse,
  CostOptimizerAvailabilityResponse,
  CostOptimizerApplyRequest,
  CostOptimizerApplyResponse,
  CostOptimizerBaselineListParams,
  CostOptimizerBaselineListResponse,
  CostOptimizerCompareRequest,
  CostOptimizerCompareResponse,
  CostOptimizerExperimentListParams,
  CostOptimizerExperimentListResponse,
  CostOptimizerLatestBaselineResponse,
  CostOptimizerParameterRecommendationsResponse,
  CostOptimizerRecommendationApplyRequest,
  ModelRoutingPolicyPatchRequest,
  ModelRoutingPolicyRefreshResponse,
  ModelRoutingPolicyResponse,
  WorkflowPermissionResponse,
  LLMTraceListResponse,
  WorkflowResponse,
  WorkflowRunListResponse,
} from '../types/Api';
import {
  mockDashboardStats,
  createMockWorkflowExecuteResult,
  createMockWorkflowStreamEvents,
  mockDeployments,
  mockWorkflowDraft,
  mockWorkflowResponse,
  mockWorkflowRunDetail,
  mockWorkflowRuns,
} from '../mock/mockWorkflow';
import { isMockWorkflowId } from '../utils/mockMode';

const API_BASE_URL = '/api/v1';

// Axios 인스턴스 생성 (withCredentials 설정)
const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // ✅ 쿠키 자동 전송
});

attachActiveOrganizationHeader(api);

const cloneMockResponse = <T>(value: T): T => {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

const createHttpError = (
  status: number,
  data: unknown,
  fallbackMessage: string,
) => {
  const detail =
    typeof data === 'object' && data !== null && 'detail' in data
      ? (data as { detail?: unknown }).detail
      : undefined;
  const message =
    typeof detail === 'string'
      ? detail
      : typeof detail === 'object' &&
          detail !== null &&
          'message' in detail &&
          typeof (detail as { message?: unknown }).message === 'string'
        ? (detail as { message: string }).message
        : fallbackMessage;

  return Object.assign(new Error(message), {
    isAxiosError: true,
    response: { status, data },
  });
};

// 401 에러 인터셉터 (인증 만료 시 로그인 페이지로)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 인증 만료 → 로그인 페이지로 리다이렉트
      console.warn('Authentication expired, redirecting to login...');
      window.location.href = '/auth/login';
    }
    return Promise.reject(error);
  },
);

export const workflowApi = {
  // 1. 드래프트 워크플로우 동기화 (저장)
  syncDraftWorkflow: async (workflowId: string, data: WorkflowDraftRequest) => {
    if (isMockWorkflowId(workflowId)) {
      return { ...data, mockMode: true };
    }

    const response = await api.post(`/workflows/${workflowId}/draft`, data);
    return response.data;
  },

  // 2. 드래프트 워크플로우 가져오기
  getDraftWorkflow: async (workflowId: string) => {
    if (isMockWorkflowId(workflowId)) {
      return cloneMockResponse(mockWorkflowDraft);
    }

    const response = await api.get(`/workflows/${workflowId}/draft`);
    return response.data;
  },

  // 3. 워크플로우 실행
  executeWorkflow: async (
    workflowId: string,
    userInput?: Record<string, unknown>,
  ) => {
    if (isMockWorkflowId(workflowId)) {
      return cloneMockResponse(createMockWorkflowExecuteResult(userInput));
    }

    const response = await api.post(
      `/workflows/${workflowId}/execute`,
      userInput || {},
    );
    return response.data;
  },

  // 3-1. 워크플로우 스트리밍 실행 (SSE)
  executeWorkflowStream: async (
    workflowId: string,
    userInput: Record<string, unknown> | FormData,
    onEvent?: (event: any) => void | Promise<void>,
    options?: { signal?: AbortSignal; graphSnapshot?: WorkflowDraftRequest },
  ) => {
    if (isMockWorkflowId(workflowId)) {
      for (const event of createMockWorkflowStreamEvents(userInput)) {
        if (onEvent) await onEvent(cloneMockResponse(event));
      }
      return;
    }

    const isFormData = userInput instanceof FormData;

    console.log(
      '[사용자 입력]: ',
      isFormData ? 'FormData (파일 포함)' : JSON.stringify(userInput || {}),
    );

    // [FIX] Next.js rewrites는 /api/* 경로를 모두 가로채므로,
    // 스트리밍은 /stream-api/* 경로로 분리하여 Next.js API Route에서 처리
    const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
    const fetchUrl = `${baseUrl}/stream-api/workflows/${workflowId}`;

    let body: BodyInit;
    if (isFormData) {
      if (options?.graphSnapshot) {
        userInput.set('graph_snapshot', JSON.stringify(options.graphSnapshot));
      }
      body = userInput;
    } else {
      body = JSON.stringify({
        inputs: userInput || {},
        graph_snapshot: options?.graphSnapshot,
      });
    }

    const activeOrganizationId = getStoredActiveOrganizationId();
    const headers = new Headers();
    if (!isFormData) {
      headers.set('Content-Type', 'application/json');
    }
    if (activeOrganizationId) {
      headers.set('X-Organization-Id', activeOrganizationId);
    }

    const response = await fetch(fetchUrl, {
      method: 'POST',
      headers,
      credentials: 'include', // 쿠키 인증 포함
      body,
      signal: options?.signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw createHttpError(
        response.status,
        errorData,
        'Workflow execution failed',
      );
    }

    if (!response.body) {
      throw new Error('No response body');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      buffer += chunk;

      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // 마지막 불완전한 라인은 버퍼에 유지

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const jsonStr = line.slice(6);
            const event = JSON.parse(jsonStr);
            if (onEvent) await onEvent(event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
            throw e;
          }
        }
      }
    }

    // 남은 버퍼 처리
    if (buffer.startsWith('data: ')) {
      try {
        const jsonStr = buffer.slice(6);
        const event = JSON.parse(jsonStr);
        if (onEvent) await onEvent(event);
      } catch (e) {
        console.error('Failed to parse SSE event:', e);
        throw e;
      }
    }
  },

  // 4. 단일 워크플로우 상세 조회
  getWorkflow: async (workflowId: string): Promise<WorkflowResponse> => {
    if (isMockWorkflowId(workflowId)) {
      return mockWorkflowResponse;
    }

    const response = await api.get(`/workflows/${workflowId}`);
    return response.data;
  },

  getWorkflowPermission: async (
    workflowId: string,
  ): Promise<WorkflowPermissionResponse> => {
    const response = await api.get(`/workflows/${workflowId}/permissions/me`);
    return response.data;
  },

  compareWorkflow: async (
    workflowId: string,
    data: {
      node_id: string;
      compare_type: 'model' | 'prompt';
      inputs: Record<string, unknown>;
      left: string;
      right: string;
    },
  ): Promise<WorkflowCompareResponse> => {
    const response = await api.post(`/workflows/${workflowId}/compare`, data);
    return response.data;
  },

  getCostOptimizerAvailability: async (
    workflowId: string,
    nodeId: string,
  ): Promise<CostOptimizerAvailabilityResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/availability`,
    );
    return response.data;
  },

  getCostOptimizerLatestBaseline: async (
    workflowId: string,
    nodeId: string,
  ): Promise<CostOptimizerLatestBaselineResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/baselines/latest`,
    );
    return response.data;
  },

  listCostOptimizerBaselines: async (
    workflowId: string,
    nodeId: string,
    params: CostOptimizerBaselineListParams = {},
  ): Promise<CostOptimizerBaselineListResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/baselines`,
      { params },
    );
    return response.data;
  },

  compareCostOptimizerCandidate: async (
    workflowId: string,
    nodeId: string,
    data: CostOptimizerCompareRequest,
  ): Promise<CostOptimizerCompareResponse> => {
    const response = await api.post(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/compare`,
      data,
    );
    return response.data;
  },

  applyCostOptimizerCandidate: async (
    workflowId: string,
    nodeId: string,
    data: CostOptimizerApplyRequest,
  ): Promise<CostOptimizerApplyResponse> => {
    const response = await api.patch(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/apply`,
      data,
    );
    return response.data;
  },

  applyCostOptimizerRecommendations: async (
    workflowId: string,
    nodeId: string,
    data: CostOptimizerRecommendationApplyRequest,
  ): Promise<CostOptimizerApplyResponse> => {
    const response = await api.patch(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/apply-recommendations`,
      data,
    );
    return response.data;
  },

  listCostOptimizerExperiments: async (
    workflowId: string,
    nodeId: string,
    params: CostOptimizerExperimentListParams = {},
  ): Promise<CostOptimizerExperimentListResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/experiments`,
      { params },
    );
    return response.data;
  },

  getCostOptimizerParameterRecommendations: async (
    workflowId: string,
    nodeId: string,
  ): Promise<CostOptimizerParameterRecommendationsResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/cost-optimizer/parameter-recommendations`,
    );
    return response.data;
  },

  getModelRoutingPolicy: async (
    workflowId: string,
    nodeId: string,
  ): Promise<ModelRoutingPolicyResponse> => {
    const response = await api.get(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/model-routing/policy`,
    );
    return response.data;
  },

  patchModelRoutingPolicy: async (
    workflowId: string,
    nodeId: string,
    data: ModelRoutingPolicyPatchRequest,
  ): Promise<ModelRoutingPolicyResponse> => {
    const response = await api.patch(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/model-routing/policy`,
      data,
    );
    return response.data;
  },

  refreshModelRoutingPolicy: async (
    workflowId: string,
    nodeId: string,
  ): Promise<ModelRoutingPolicyRefreshResponse> => {
    const response = await api.post(
      `/workflows/${workflowId}/llm-nodes/${nodeId}/model-routing/policy/refresh`,
    );
    return response.data;
  },

  // 5. 새 워크플로우 생성
  createWorkflow: async (
    data: WorkflowCreateRequest,
  ): Promise<WorkflowResponse> => {
    const response = await api.post('/workflows', data);
    return response.data;
  },

  // 6. 특정 App의 워크플로우 목록 조회
  listWorkflowsByApp: async (appId: string): Promise<WorkflowResponse[]> => {
    const response = await api.get(`/workflows/app/${appId}`);
    return response.data;
  },

  createDeployment: async (data: DeploymentCreate) => {
    const response = await api.post('/deployments', data);
    return response.data as DeploymentResponse;
  },

  preflightDeployment: async (data: DeploymentPreflightRequest) => {
    const response = await api.post('/deployments/preflight', data);
    return response.data as DeploymentPreflightResponse;
  },

  getDeployments: async (workflowId: string) => {
    if (isMockWorkflowId(workflowId)) {
      return mockDeployments;
    }

    const response = await api.get('/deployments', {
      params: { workflow_id: workflowId },
    });
    return response.data as DeploymentResponse[];
  },

  // [NEW] 워크플로우 실행 이력 조회
  getWorkflowRuns: async (workflowId: string, page = 1, limit = 20) => {
    if (isMockWorkflowId(workflowId)) {
      return {
        ...mockWorkflowRuns,
        items: mockWorkflowRuns.items.slice((page - 1) * limit, page * limit),
      };
    }

    const response = await api.get(`/workflows/${workflowId}/runs`, {
      params: { page, limit },
    });
    return response.data as WorkflowRunListResponse;
  },

  // [NEW] 단일 워크플로우 실행 이력 상세 조회
  getWorkflowRun: async (workflowId: string, runId: string) => {
    if (isMockWorkflowId(workflowId)) {
      return { ...mockWorkflowRunDetail, id: runId };
    }

    const response = await api.get(`/workflows/${workflowId}/runs/${runId}`);
    return response.data as import('../types/Api').WorkflowRun;
  },

  getWorkflowRunLlmTraces: async (
    workflowId: string,
    runId: string,
    params?: { node_id?: string; limit?: number; offset?: number },
  ) => {
    const response = await api.get(
      `/workflows/${workflowId}/runs/${runId}/llm-traces`,
      { params },
    );
    return response.data as LLMTraceListResponse;
  },

  // [NEW] 대시보드 통계 조회
  getDashboardStats: async (workflowId: string) => {
    if (isMockWorkflowId(workflowId)) {
      return cloneMockResponse(mockDashboardStats);
    }

    const response = await api.get(`/workflows/${workflowId}/stats`);
    return response.data as import('../types/Api').DashboardStatsResponse;
  },

  // [NEW] Top 3 Models
  getTopExpensiveModels: async () => {
    const response = await api.get('/llm/stats/top-models'); // Note: baseURL is /api/v1
    return response.data as import('../types/Api').TopExpensiveModel[];
  },

  getDeployment: async (deploymentId: string) => {
    const response = await api.get(`/deployments/${deploymentId}`);
    return response.data as DeploymentResponse;
  },

  getDeploymentRunInfo: async (deploymentId: string) => {
    const response = await api.get(`/deployments/${deploymentId}/run-info`);
    return response.data as DeploymentRunInfoResponse;
  },

  runDeployment: async (
    deploymentId: string,
    inputs: Record<string, unknown>,
  ) => {
    const response = await api.post(`/deployments/${deploymentId}/run`, {
      inputs,
    });
    return response.data as { status: string; results?: unknown };
  },

  listWorkflowNodes: async (excludedAppId?: string) => {
    const response = await api.get('/deployments/nodes', {
      params: { excluded_app_id: excludedAppId },
    });
    return response.data as {
      deployment_id: string;
      app_id: string;
      name: string;
      description: string;
      version: number;
      input_schema: any;
      output_schema: any;
    }[];
  },

  // 배포 토글 (is_active)
  toggleDeployment: async (deploymentId: string) => {
    const response = await api.patch(`/deployments/${deploymentId}/toggle`);
    return response.data as DeploymentResponse;
  },

  // 배포 삭제
  deleteDeployment: async (deploymentId: string) => {
    const response = await api.delete(`/deployments/${deploymentId}`);
    return response.data;
  },
};
