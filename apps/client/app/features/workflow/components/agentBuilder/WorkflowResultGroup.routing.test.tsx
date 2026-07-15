import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WorkflowResultGroup } from './WorkflowResultGroup';
import type { Node } from '../../types/Workflow';

const nodes: Node[] = [
  {
    id: 'generated-llm',
    type: 'llmNode',
    position: { x: 0, y: 0 },
    data: { title: '요약 LLM', auto_model_routing: false },
  } as Node,
  {
    id: 'routing-enabled-llm',
    type: 'llmNode',
    position: { x: 320, y: 0 },
    data: { title: '라우팅 완료 LLM', auto_model_routing: true },
  } as Node,
  {
    id: 'existing-llm',
    type: 'llmNode',
    position: { x: 640, y: 0 },
    data: { title: '기존 LLM', auto_model_routing: false },
  } as Node,
  {
    id: 'generated-slack',
    type: 'slackPostNode',
    position: { x: 960, y: 0 },
    data: { title: '알림 Slack' },
  } as Node,
  {
    id: 'generated-github',
    type: 'githubNode',
    position: { x: 1280, y: 0 },
    data: { title: '리뷰 GitHub' },
  } as Node,
];

describe('WorkflowResultGroup model routing guidance', () => {
  it('이번 결과의 라우팅 미설정 LLM만 하나의 안내로 보여주고 Routing control 열기를 요청한다', () => {
    const onFocusNode = vi.fn();
    const onOpenNodeSettings = vi.fn();

    render(
      <WorkflowResultGroup
        tasks={[]}
        nodes={nodes}
        routingNodeIds={['generated-llm', 'routing-enabled-llm']}
        onFocusNode={onFocusNode}
        onOpenNodeSettings={onOpenNodeSettings}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByTestId('agent-builder-routing-guidance')).toBeInTheDocument();
    expect(
      screen.getByText('모델 자동 라우팅은 LLM 노드를 선택한 뒤 Routing 설정할 수 있습니다.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '요약 LLM Routing 설정으로 이동' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '라우팅 완료 LLM Routing 설정으로 이동' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '기존 LLM Routing 설정으로 이동' }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: '요약 LLM Routing 설정으로 이동' }),
    );

    expect(onOpenNodeSettings).toHaveBeenCalledTimes(1);
    expect(onOpenNodeSettings).toHaveBeenCalledWith('generated-llm', 'routing');
  });

  it('이번 결과에 라우팅 미설정 LLM이 없으면 안내를 숨긴다', () => {
    render(
      <WorkflowResultGroup
        tasks={[]}
        nodes={nodes}
        routingNodeIds={['routing-enabled-llm']}
        onFocusNode={vi.fn()}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('agent-builder-routing-guidance')).not.toBeInTheDocument();
  });

  it('Slack과 GitHub는 credential 입력 카드 대신 기존 연결 설정으로 이동한다', () => {
    const onOpenNodeSettings = vi.fn();

    render(
      <WorkflowResultGroup
        tasks={[]}
        nodes={nodes}
        connectionNodeIds={['generated-slack', 'generated-github']}
        onFocusNode={vi.fn()}
        onOpenNodeSettings={onOpenNodeSettings}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByTestId('agent-builder-connection-guidance')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: '알림 Slack 연결 설정으로 이동' }),
    );
    fireEvent.click(
      screen.getByRole('button', { name: '리뷰 GitHub 연결 설정으로 이동' }),
    );

    expect(onOpenNodeSettings).toHaveBeenNthCalledWith(
      1,
      'generated-slack',
      'connection',
    );
    expect(onOpenNodeSettings).toHaveBeenNthCalledWith(
      2,
      'generated-github',
      'connection',
    );
  });
});
