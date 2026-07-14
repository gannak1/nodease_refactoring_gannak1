import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { InputStep } from './InputStep';

const defaultProps = {
  deploymentType: 'chatbot' as const,
  deploymentTypeLabel: '공개 챗봇',
  description: '',
  onDescriptionChange: vi.fn(),
  embeddingEnabled: false,
  parentOrigins: [''],
  onEmbeddingEnabledChange: vi.fn(),
  onParentOriginChange: vi.fn(),
  onAddParentOrigin: vi.fn(),
  onRemoveParentOrigin: vi.fn(),
  onCancel: vi.fn(),
  onSubmit: vi.fn(),
  isDeploying: false,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('InputStep browser access controls', () => {
  it('shows policy controls only for public chatbot and widget deployments', () => {
    const { rerender } = render(<InputStep {...defaultProps} />);

    expect(
      screen.getByRole('switch', { name: '외부 사이트에 삽입 허용' }),
    ).toBeVisible();

    rerender(
      <InputStep
        {...defaultProps}
        deploymentType="internal_chatbot"
        deploymentTypeLabel="내부 챗봇"
      />,
    );

    expect(
      screen.queryByRole('switch', { name: '외부 사이트에 삽입 허용' }),
    ).not.toBeInTheDocument();
  });

  it('returns the disabled V1 policy by default', () => {
    render(<InputStep {...defaultProps} />);

    fireEvent.click(screen.getByRole('button', { name: '배포' }));

    expect(defaultProps.onSubmit).toHaveBeenCalledWith({
      contract_version: 'deployment_browser_access.v1',
      embedding: { enabled: false, parent_origins: [] },
    });
  });

  it('blocks enabled submission until an exact parent origin is present', () => {
    const { rerender } = render(
      <InputStep {...defaultProps} embeddingEnabled parentOrigins={['']} />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('1개 이상');
    expect(screen.getByRole('button', { name: '배포' })).toBeDisabled();

    rerender(
      <InputStep
        {...defaultProps}
        embeddingEnabled
        parentOrigins={['https://portal.example.com']}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '배포' }));

    expect(defaultProps.onSubmit).toHaveBeenCalledWith({
      contract_version: 'deployment_browser_access.v1',
      embedding: {
        enabled: true,
        parent_origins: ['https://portal.example.com'],
      },
    });
  });

  it('delegates add, edit, and remove commands without changing policy locally', () => {
    render(
      <InputStep
        {...defaultProps}
        embeddingEnabled
        parentOrigins={['https://portal.example.com']}
      />,
    );

    fireEvent.change(screen.getByLabelText('부모 origin 1'), {
      target: { value: 'https://admin.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'origin 추가' }));
    fireEvent.click(screen.getByRole('button', { name: '부모 origin 1 제거' }));

    expect(defaultProps.onParentOriginChange).toHaveBeenCalledWith(
      0,
      'https://admin.example.com',
    );
    expect(defaultProps.onAddParentOrigin).toHaveBeenCalledOnce();
    expect(defaultProps.onRemoveParentOrigin).toHaveBeenCalledWith(0);
  });
});
