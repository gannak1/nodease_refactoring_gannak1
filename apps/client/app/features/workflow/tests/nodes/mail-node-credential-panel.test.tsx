import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MailNodePanel } from '../../components/nodes/mail/components/MailNodePanel';
import type { MailNodeData } from '../../types/Nodes';

const updateNodeDataMock = vi.hoisted(() => vi.fn());
const listAvailableMock = vi.hoisted(() => vi.fn());

vi.mock('@/app/features/workflow/store/useWorkflowStore', () => ({
  useWorkflowStore: () => ({
    updateNodeData: updateNodeDataMock,
    nodes: [],
    edges: [],
  }),
}));

vi.mock('../../api/mailCredentialApi', () => ({
  mailCredentialApi: {
    listAvailable: listAvailableMock,
  },
}));

vi.mock('../../components/ui/RoundedSelect', () => ({
  RoundedSelect: ({
    value,
    onChange,
    options,
    placeholder,
  }: {
    value: string;
    onChange: (value: string) => void;
    options: Array<{ label: string; value: string }>;
    placeholder: string;
  }) => (
    <select
      aria-label="연결 계정"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{placeholder}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

vi.mock('../../components/nodes/ui/VariableTokenEditor', () => ({
  VariableTokenEditor: () => <textarea aria-label="메일 검색 키워드" />,
}));

const data = (): MailNodeData => ({
  title: '메일 검색',
  credential_id: null,
  folder: 'INBOX',
  unread_only: true,
  mark_as_read: false,
  referenced_variables: [],
});

describe('MailNodePanel credential reference', () => {
  beforeEach(() => {
    updateNodeDataMock.mockReset();
    listAvailableMock.mockResolvedValue([
      {
        id: 'credential-1',
        credential_name: '업무 메일',
        provider: 'gmail',
        email_preview: 'm***@example.com',
        status: 'active',
      },
    ]);
  });

  it('password 입력 없이 safe credential reference만 저장한다', async () => {
    render(<MailNodePanel nodeId="mail-1" data={data()} />);

    await waitFor(() =>
      expect(
        screen.getByRole('option', { name: /업무 메일/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText('비밀번호')).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText('앱 비밀번호'),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getAllByRole('combobox')[0], {
      target: { value: 'credential-1' },
    });

    expect(updateNodeDataMock).toHaveBeenCalledWith('mail-1', {
      credential_id: 'credential-1',
      configuration_state: 'resolved',
    });
  });
});
