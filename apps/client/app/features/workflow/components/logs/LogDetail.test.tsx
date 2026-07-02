import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LogDetail } from './LogDetail';
import { workflowApi } from '../../api/workflowApi';
import type { LLMTrace, WorkflowRun } from '@/app/features/workflow/types/Api';

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
  it('응답 노드 결과를 상단 최종 응답으로 먼저 보여주고 응답 노드를 기본 선택한다', async () => {
    vi.mocked(workflowApi.getWorkflowRunLlmTraces).mockResolvedValue({
      total: 0,
      limit: 500,
      offset: 0,
      items: [],
    });

    render(
      <LogDetail
        run={{
          ...createRun('run-demo'),
          node_runs: [
            {
              id: 'trigger-run',
              node_id: 'webhook-trigger',
              node_type: 'webhookTriggerNode',
              status: 'success',
              started_at: '2026-06-27T00:00:00Z',
              finished_at: '2026-06-27T00:00:01Z',
              outputs: { message: '가족돌봄휴가 질문' },
            },
            {
              id: 'llm-run',
              node_id: 'llm',
              node_type: 'llmNode',
              status: 'success',
              started_at: '2026-06-27T00:00:01Z',
              finished_at: '2026-06-27T00:00:04Z',
              outputs: { text: 'LLM 중간 답변' },
            },
            {
              id: 'answer-run',
              node_id: 'answer',
              node_type: 'answerNode',
              status: 'success',
              started_at: '2026-06-27T00:00:04Z',
              finished_at: '2026-06-27T00:00:05Z',
              inputs: {
                webhook: {
                  message: '가족돌봄휴가 질문',
                },
              },
              outputs: {
                answer_text: '가족돌봄휴가는 연차와 이어 사용할 수 있습니다.',
              },
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('최종 응답')).toBeInTheDocument();
    expect(
      screen.getByText('가족돌봄휴가는 연차와 이어 사용할 수 있습니다.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('가족돌봄휴가 질문')).not.toBeInTheDocument();

    const selectedAnswerButtons = screen
      .getAllByRole('button', { name: /응답/ })
      .filter((button) => button.className.includes('bg-blue-50'));
    expect(selectedAnswerButtons.length).toBeGreaterThan(0);
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
