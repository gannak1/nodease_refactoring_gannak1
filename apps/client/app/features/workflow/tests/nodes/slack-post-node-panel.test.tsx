import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SlackPostNodePanel } from '../../components/nodes/slack/components/SlackPostNodePanel';
import type { SlackPostNodeData } from '../../types/Nodes';

const updateNodeDataMock = vi.hoisted(() => vi.fn());

vi.mock('@/app/features/workflow/store/useWorkflowStore', () => ({
  useWorkflowStore: () => ({
    updateNodeData: updateNodeDataMock,
    nodes: [],
    edges: [],
  }),
}));

vi.mock('../../components/nodes/ui/VariableTokenEditor', () => ({
  VariableTokenEditor: ({ value }: { value: string }) => (
    <textarea aria-label="Slack 메시지" value={value} readOnly />
  ),
}));

const data = (
  overrides: Partial<SlackPostNodeData> = {},
): SlackPostNodeData => ({
  title: 'Slack',
  slackMode: 'api',
  channel: 'C123',
  message: 'hello',
  authConfig: { token: 'fixture-token' },
  referenced_variables: [],
  ...overrides,
});

describe('SlackPostNodePanel', () => {
  beforeEach(() => updateNodeDataMock.mockReset());

  it('API endpoint를 webhook credential로 잘못 보존하지 않는다', () => {
    render(
      <SlackPostNodePanel
        nodeId="slack-1"
        data={data({ url: 'https://slack.com/api/chat.postMessage' })}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Incoming Webhook' }));

    expect(updateNodeDataMock).toHaveBeenCalledWith('slack-1', {
      slackMode: 'webhook',
      channel: '',
      url: undefined,
      authConfig: {},
      authType: 'none',
    });
  });

  it('blocks 안의 미등록 template 변수도 경고한다', () => {
    render(
      <SlackPostNodePanel
        nodeId="slack-1"
        data={data({
          blocks:
            '[{"type":"section","text":{"type":"plain_text","text":"{{block_value}}"}}]',
        })}
      />,
    );

    expect(screen.getByText('block_value')).toBeInTheDocument();
  });

  it('API mode의 legacy URL과 잘못된 authType을 migration 경고로 표시한다', () => {
    render(
      <SlackPostNodePanel
        nodeId="slack-1"
        data={data({
          url: 'https://example.invalid/slack',
          authType: 'none',
        })}
      />,
    );

    expect(
      screen.getByText('기존 HTTP 설정은 Slack 전송에 사용되지 않습니다.'),
    ).toBeInTheDocument();
  });

  it('attachments JSON을 canonical 전송 필드로 수정한다', () => {
    render(<SlackPostNodePanel nodeId="slack-1" data={data()} />);

    fireEvent.change(screen.getByLabelText('Slack 첨부 JSON'), {
      target: { value: '[{"text":"alert"}]' },
    });

    expect(updateNodeDataMock).toHaveBeenCalledWith('slack-1', {
      attachments: '[{"text":"alert"}]',
    });
  });
});
