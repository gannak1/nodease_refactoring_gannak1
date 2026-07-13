import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LogDetail } from './LogDetail';
import { workflowApi } from '../../api/workflowApi';
import type {
  LLMTrace,
  WorkflowNodeRun,
  WorkflowRun,
} from '@/app/features/workflow/types/Api';

vi.mock('../../api/workflowApi', () => ({
  workflowApi: {
    getWorkflowRunLlmTraces: vi.fn(),
  },
}));

const createRun = (id: string, workflowId = 'workflow-1'): WorkflowRun => ({
  id,
  workflow_id: workflowId,
  user_id: 'user-1',
  status: 'success',
  trigger_mode: 'manual',
  started_at: '2026-06-27T00:00:00Z',
  duration: 1,
  node_runs: [
    {
      id: `${id}-node-run`,
      node_id: `${id}-node`,
      node_type: 'llmNode',
      status: 'success',
      started_at: '2026-06-27T00:00:00Z',
      outputs: {
        model: 'legacy-model',
        cost: 0.001,
        usage: {
          prompt_tokens: 1,
          completion_tokens: 2,
          total_tokens: 3,
        },
      },
    },
  ],
});

const createTrace = (runId: string): LLMTrace => ({
  id: `${runId}-trace`,
  workflow_id: 'workflow-1',
  workflow_run_id: runId,
  node_id: `${runId}-node`,
  model_id: 'model-1',
  model_name: 'gpt-trace-model',
  provider: 'openai',
  credential_id: 'credential-1',
  prompt_tokens: 10,
  completion_tokens: 20,
  total_tokens: 30,
  total_cost: 0.02,
  latency_ms: 123,
  status: 'success',
  created_at: '2026-06-27T00:00:01Z',
});

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
});

describe('LogDetail', () => {
  it('배포 실행 LLM trace에서 사용자가 이해할 수 있는 모델 선택 근거를 보여준다', async () => {
    vi.mocked(workflowApi.getWorkflowRunLlmTraces).mockResolvedValue({
      total: 0,
      limit: 500,
      offset: 0,
      items: [],
    });
    const run = createRun('run-routing');
    const llmNodeRun = run.node_runs?.[0] as WorkflowNodeRun;
    llmNodeRun.outputs = {
      ...llmNodeRun.outputs,
      model: 'gpt-4.1',
    };
    llmNodeRun.trace_metadata = {
      llm: {
        selected_model: 'gpt-4.1',
        fallback_model: 'gpt-4.1-mini',
        decision_source: 'active_policy',
        matched_cohort_id: 'high_risk',
        semantic_route_label: '보안 및 SLA 고위험',
        semantic_match_status: 'matched',
        semantic_decision_source: 'safety_override',
        semantic_lexical_score: 1,
        semantic_lexical_signal_count: 1,
        semantic_safety_override: true,
        policy_version: 'routing-policy-v10',
        route_catalog_version: 'ticket-routing-v7',
        judge_called: false,
      },
    };

    await act(async () => {
      render(<LogDetail run={run} />);
    });

    const routingDetails = screen.getByText('자동 라우팅').closest('dl');
    expect(routingDetails).not.toBeNull();
    const routing = within(routingDetails as HTMLElement);
    expect(routing.getByText('보안 및 SLA 고위험')).toBeInTheDocument();
    expect(routing.getByText('gpt-4.1')).toBeInTheDocument();
    expect(
      routing.getByText(
        '정책의 안전 조건 1개와 일치해 안전 유형을 우선했습니다.',
      ),
    ).toBeInTheDocument();
    expect(
      routing.getByText(
        '비용 절감보다 사고 대응 품질을 우선해 검증된 모델을 선택했습니다.',
      ),
    ).toBeInTheDocument();
    expect(routing.getByText('실행 중 Judge 호출 안 함')).toBeInTheDocument();
  });

  it('run 전환 시 이전 LLM trace state를 즉시 초기화한다', async () => {
    let resolveSecondTrace: (
      value: Awaited<ReturnType<typeof workflowApi.getWorkflowRunLlmTraces>>,
    ) => void = () => undefined;

    vi.mocked(workflowApi.getWorkflowRunLlmTraces)
      .mockResolvedValueOnce({
        total: 1,
        limit: 500,
        offset: 0,
        items: [createTrace('run-1')],
      })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecondTrace = resolve;
        }),
      );

    const { rerender } = render(<LogDetail run={createRun('run-1')} />);

    await waitFor(() => {
      expect(screen.getAllByText('gpt-trace-model').length).toBeGreaterThan(0);
    });

    rerender(<LogDetail run={{ ...createRun('run-2'), node_runs: [] }} />);

    await waitFor(() => {
      expect(screen.queryByText('gpt-trace-model')).not.toBeInTheDocument();
    });
    expect(
      screen.getByText('LLM trace를 불러오는 중입니다...'),
    ).toBeInTheDocument();

    await act(async () => {
      resolveSecondTrace({
        total: 0,
        limit: 500,
        offset: 0,
        items: [],
      });
    });
  });
});
