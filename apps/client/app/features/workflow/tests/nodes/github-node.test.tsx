import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import type { Node, NodeProps } from '@xyflow/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GithubNode } from '../../components/nodes/github/components/GithubNode';
import { GithubNodePanel } from '../../components/nodes/github/components/GithubNodePanel';
import type { GithubNodeData } from '../../types/Nodes';

const updateNodeDataMock = vi.hoisted(() => vi.fn());
const listAvailableMock = vi.hoisted(() => vi.fn());

vi.mock('@/app/features/workflow/store/useWorkflowStore', () => ({
  useWorkflowStore: () => ({
    updateNodeData: updateNodeDataMock,
    nodes: [],
    edges: [],
  }),
}));

vi.mock('../../components/nodes/BaseNode', () => ({
  BaseNode: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('../../components/ui/ValidationBadge', () => ({
  ValidationBadge: () => <div data-testid="validation-badge" />,
}));

vi.mock('../../components/nodes/ui/VariableTokenEditor', () => ({
  VariableTokenEditor: ({ value }: { value: string }) => (
    <textarea value={value} readOnly />
  ),
}));

vi.mock('../../api/externalActionCredentialApi', () => ({
  externalActionCredentialApi: {
    listAvailable: listAvailableMock,
  },
}));

const data = (overrides: Partial<GithubNodeData> = {}): GithubNodeData => ({
  title: 'GitHub',
  action: 'get_pr',
  credential_id: 'credential-1',
  configuration_state: 'resolved',
  repo_owner: 'nodease',
  repo_name: 'mbased',
  pr_number: '1',
  referenced_variables: [],
  ...overrides,
});

const props = (
  overrides: Partial<GithubNodeData>,
): NodeProps<Node<GithubNodeData>> => ({
  id: 'github-1',
  type: 'githubNode',
  selected: false,
  dragging: false,
  selectable: true,
  deletable: true,
  draggable: true,
  zIndex: 0,
  isConnectable: true,
  positionAbsoluteX: 0,
  positionAbsoluteY: 0,
  data: data(overrides),
});

describe('GitHub credential reference boundary', () => {
  beforeEach(() => {
    updateNodeDataMock.mockReset();
    listAvailableMock.mockResolvedValue([
      {
        id: 'credential-1',
        credential_name: '운영 GitHub',
        provider: 'github',
        revision: 1,
        status: 'active',
      },
    ]);
  });

  it('legacy token/authConfig가 남은 노드를 configured로 표시하지 않는다', () => {
    render(<GithubNode {...props({ authConfig: {} })} />);

    expect(screen.getByTestId('validation-badge')).toBeInTheDocument();
  });

  it('legacy direct credential 제거 action은 모든 legacy field를 비운다', () => {
    render(
      <GithubNodePanel
        nodeId="github-1"
        data={data({ api_token: 'legacy', token: 'legacy', authConfig: {} })}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: '기존 직접 인증 설정 제거' }),
    );

    expect(updateNodeDataMock).toHaveBeenCalledWith('github-1', {
      api_token: undefined,
      token: undefined,
      authConfig: undefined,
      configuration_state: 'resolved',
    });
  });
});
