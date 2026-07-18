import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SlackPostNodePanel } from '../../components/nodes/slack/components/SlackPostNodePanel';
import type { SlackPostNodeData } from '../../types/Nodes';

const updateNodeDataMock = vi.hoisted(() => vi.fn());
const listAvailableMock = vi.hoisted(() => vi.fn());

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

vi.mock('../../api/externalActionCredentialApi', () => ({
  externalActionCredentialApi: {
    listAvailable: listAvailableMock,
  },
}));

const data = (
  overrides: Partial<SlackPostNodeData> = {},
): SlackPostNodeData => ({
  title: 'Slack',
  slackMode: 'api',
  credential_id: 'credential-1',
  channel: 'C123',
  message: 'hello',
  referenced_variables: [],
  ...overrides,
});

describe('SlackPostNodePanel', () => {
  beforeEach(() => {
    updateNodeDataMock.mockReset();
    listAvailableMock.mockResolvedValue([
      {
        id: 'credential-1',
        credential_name: 'Slack 운영 알림',
        provider: 'slack_api',
        revision: 1,
        status: 'active',
      },
    ]);
  });

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
      credential_id: null,
      configuration_state: 'unresolved',
      url: undefined,
      authConfig: undefined,
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
      screen.getByText('기존 직접 인증 설정은 사용할 수 없습니다.'),
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
