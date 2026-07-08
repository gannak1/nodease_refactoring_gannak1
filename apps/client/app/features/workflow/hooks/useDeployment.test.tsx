import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { useDeployment } from './useDeployment';

vi.mock('@/app/features/workflow/api/workflowApi', () => ({
  workflowApi: {
    createDeployment: vi.fn(),
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
});
