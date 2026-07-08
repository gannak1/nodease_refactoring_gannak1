import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AuthenticatedDeploymentRunPage from './page';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';

const { routerPush } = vi.hoisted(() => ({
  routerPush: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'workflow-1' }),
  useRouter: () => ({ push: routerPush }),
  useSearchParams: () => new URLSearchParams('deploymentId=deployment-1'),
}));

vi.mock('@/app/features/workflow/api/workflowApi', () => ({
  workflowApi: {
    getDeploymentRunInfo: vi.fn(),
    runDeployment: vi.fn(),
  },
}));

const mockedWorkflowApi = vi.mocked(workflowApi);

describe('AuthenticatedDeploymentRunPage', () => {
  beforeEach(() => {
    mockedWorkflowApi.getDeploymentRunInfo.mockResolvedValue({
      deployment_id: 'deployment-1',
      app_id: 'app-1',
      workflow_id: 'workflow-1',
      name: '사내 문서 질문 응답 봇',
      version: 1,
      type: 'chatbot',
      input_schema: {
        variables: [
          {
            name: 'question',
            type: 'paragraph',
            label: '질문',
          },
        ],
      },
      output_schema: {
        outputs: [{ variable: 'final_answer', label: '최종 답변' }],
      },
    });
    mockedWorkflowApi.runDeployment.mockResolvedValue({
      status: 'success',
      results: {
        final_answer: '개발팀 신입 연봉 기준은 사내 문서 기준을 따릅니다.',
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('safe run-info로 입력 폼을 만들고 인증 배포 실행 결과를 최종 응답으로 표시한다', async () => {
    render(<AuthenticatedDeploymentRunPage />);

    expect(
      await screen.findByRole('heading', { name: '사내 문서 질문 응답 봇' }),
    ).toBeVisible();
    expect(screen.getByRole('main')).toHaveClass('h-full', 'overflow-y-auto');
    expect(mockedWorkflowApi.getDeploymentRunInfo).toHaveBeenCalledWith(
      'deployment-1',
    );

    fireEvent.change(screen.getByLabelText('질문'), {
      target: { value: '개발팀 신입 연봉 기준을 알려줘' },
    });
    fireEvent.click(screen.getByRole('button', { name: '실행' }));

    await waitFor(() => {
      expect(mockedWorkflowApi.runDeployment).toHaveBeenCalledWith(
        'deployment-1',
        expect.objectContaining({
          question: '개발팀 신입 연봉 기준을 알려줘',
          memory_mode: true,
          conversation_id: expect.any(String),
        }),
      );
    });
    expect(
      await screen.findByText(
        '개발팀 신입 연봉 기준은 사내 문서 기준을 따릅니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('최종 답변')).toBeVisible();
  });

  it('URL workflow와 run-info workflow가 다르면 실행을 막는다', async () => {
    mockedWorkflowApi.getDeploymentRunInfo.mockResolvedValueOnce({
      deployment_id: 'deployment-1',
      app_id: 'app-1',
      workflow_id: 'other-workflow',
      name: '다른 워크플로우 배포',
      version: 1,
      type: 'chatbot',
      input_schema: { variables: [] },
      output_schema: { outputs: [] },
    });

    render(<AuthenticatedDeploymentRunPage />);

    expect(
      await screen.findByText('요청한 workflow와 배포 정보가 일치하지 않습니다.'),
    ).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '실행' }));
    expect(mockedWorkflowApi.runDeployment).not.toHaveBeenCalled();
  });
});
