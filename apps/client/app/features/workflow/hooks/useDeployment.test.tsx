import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { useDeployment } from './useDeployment';

vi.mock('@/app/features/workflow/api/workflowApi', () => ({
  workflowApi: {
    createDeployment: vi.fn(),
    preflightDeployment: vi.fn(),
  },
}));

const mockedWorkflowApi = vi.mocked(workflowApi);
const initialStoreState = useWorkflowStore.getState();

const renderDeploymentHook = () =>
  renderHook(() =>
    useDeployment({
      nodes: [],
      isSettingsOpen: false,
      toggleSettings: vi.fn(),
      isVersionHistoryOpen: false,
      toggleVersionHistory: vi.fn(),
      isTestPanelOpen: false,
      toggleTestPanel: vi.fn(),
      setSelectedNodeId: vi.fn(),
      setSelectedNodeType: vi.fn(),
    }),
  );

describe('useDeployment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkflowStore.setState(initialStoreState, true);
    useWorkflowStore.setState({
      activeWorkflowId: 'workflow-1',
      workflows: [
        {
          id: 'workflow-1',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: {},
        },
      ],
    });
    mockedWorkflowApi.createDeployment.mockResolvedValue({
      id: 'deployment-1',
      app_id: 'app-1',
      version: 3,
      type: 'chatbot',
      url_slug: 'onboarding-bot',
      is_active: true,
      created_by: 'user-1',
      created_at: '2026-07-08T00:00:00Z',
      graph_snapshot: {},
      input_schema: null,
      output_schema: null,
    });
    mockedWorkflowApi.preflightDeployment.mockResolvedValue({
      status: 'passed',
      audience: 'anonymous_public',
      safe_summary: {
        blocked_reason: null,
        affected_node_count: 0,
        affected_kb_count_bucket: '0',
      },
      required_actions: [],
      warnings: [],
      nodes: [],
    });
  });

  it('chatbot deployment returns separate public and authenticated run links', async () => {
    const { result } = renderDeploymentHook();

    act(() => {
      result.current.handlePublishAsChatbot();
    });

    let deploymentResult: Awaited<ReturnType<typeof result.current.handleDeploy>>;
    await act(async () => {
      deploymentResult = await result.current.handleDeploy('사내 문서 질문 응답 봇');
    });

    expect(mockedWorkflowApi.createDeployment).toHaveBeenCalledWith(
      expect.objectContaining({
        app_id: 'app-1',
        type: 'chatbot',
        is_active: true,
      }),
    );
    expect(deploymentResult!.webAppUrl).toContain(
      '/embed/chat/onboarding-bot',
    );
    expect(deploymentResult!.internalRunUrl).toContain(
      '/modules/workflow-1/run?deploymentId=deployment-1',
    );
  });

  it('blocked preflight stops active deployment creation', async () => {
    mockedWorkflowApi.preflightDeployment.mockResolvedValueOnce({
      status: 'blocked',
      audience: 'anonymous_public',
      safe_summary: {
        blocked_reason: 'private_kb_requires_execution_subject',
        affected_node_count: 1,
        affected_kb_count_bucket: '1',
      },
      required_actions: [
        {
          action: 'remove_private_kb_or_use_authenticated_run',
          label: 'Private KB를 제거하거나 인증 실행 경로를 사용하세요',
        },
      ],
      warnings: [],
      nodes: [],
    });
    const { result } = renderDeploymentHook();

    let deploymentResult: Awaited<ReturnType<typeof result.current.handleDeploy>>;
    await act(async () => {
      deploymentResult = await result.current.handleDeploy('private kb');
    });

    expect(deploymentResult!.success).toBe(false);
    expect(deploymentResult!.message).toContain(
      'private_kb_requires_execution_subject',
    );
    expect(mockedWorkflowApi.createDeployment).not.toHaveBeenCalled();
  });
});
