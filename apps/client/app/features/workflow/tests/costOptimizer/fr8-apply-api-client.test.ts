import { beforeEach, describe, expect, it, vi } from 'vitest';

const axiosPatchMock = vi.hoisted(() => vi.fn());
const attachActiveOrganizationHeaderMock = vi.hoisted(() => vi.fn());

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      get: vi.fn(),
      post: vi.fn(),
      patch: axiosPatchMock,
      interceptors: {
        response: { use: vi.fn() },
      },
    })),
  },
}));

vi.mock('@/lib/activeOrganization', () => ({
  attachActiveOrganizationHeader: attachActiveOrganizationHeaderMock,
}));

describe('FR-008 Cost Optimizer apply API client', () => {
  beforeEach(() => {
    vi.resetModules();
    axiosPatchMock.mockReset();
    attachActiveOrganizationHeaderMock.mockClear();
  });

  it('apply API client는 candidate_settings를 문서 계약 경로로 전송한다', async () => {
    axiosPatchMock.mockResolvedValue({
      data: {
        workflow_id: 'workflow-1',
        node_id: 'llm-triage',
        applied: true,
        downstream_compatibility: { state: 'compatible', label: '검증 가능' },
        updated_draft_revision: null,
      },
    });
    const { workflowApi } = await import('../../api/workflowApi');

    await workflowApi.applyCostOptimizerCandidate(
      'workflow-1',
      'llm-triage',
      {
        comparison_id: 'comparison-1',
        candidate_settings: {
          label: 'B',
          model_id: 'gpt-4.1-mini',
          parameters: { max_tokens: 800, temperature: 0.1 },
        },
        acknowledge_downstream_warning: true,
      },
    );

    expect(axiosPatchMock).toHaveBeenCalledWith(
      '/workflows/workflow-1/llm-nodes/llm-triage/cost-optimizer/apply',
      {
        comparison_id: 'comparison-1',
        candidate_settings: {
          label: 'B',
          model_id: 'gpt-4.1-mini',
          parameters: { max_tokens: 800, temperature: 0.1 },
        },
        acknowledge_downstream_warning: true,
      },
    );
  });
});
