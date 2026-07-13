import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AuthenticatedDeploymentRunPage from './page';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';

const { routerPush, routerReplace } = vi.hoisted(() => ({
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'workflow-1' }),
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
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
      type: 'internal_chatbot',
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
    window.history.replaceState({}, '', '/');
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
        {
          question: '개발팀 신입 연봉 기준을 알려줘',
        },
        expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        ),
      );
    });
    expect(
      await screen.findByText(
        '개발팀 신입 연봉 기준은 사내 문서 기준을 따릅니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('최종 답변')).toBeVisible();
  });

  it('내부 실행 화면의 뒤로가기는 운영 현황이 아닌 대시보드로 이동한다', async () => {
    render(<AuthenticatedDeploymentRunPage />);

    await screen.findByRole('heading', { name: '사내 문서 질문 응답 봇' });
    fireEvent.click(screen.getByRole('button', { name: '대시보드로 돌아가기' }));

    expect(routerPush).toHaveBeenCalledWith('/dashboard');
  });

  it('비로그인 사용자는 원래 내부 실행 링크를 보존한 로그인 화면으로 이동한다', async () => {
    window.history.replaceState(
      {},
      '',
      '/modules/workflow-1/run?deploymentId=deployment-1&tab=history#result',
    );
    mockedWorkflowApi.getDeploymentRunInfo.mockRejectedValueOnce({
      response: { status: 401 },
    });

    render(<AuthenticatedDeploymentRunPage />);

    await waitFor(() => {
      expect(routerReplace).toHaveBeenCalledWith(
        '/auth/login?next=%2Fmodules%2Fworkflow-1%2Frun%3FdeploymentId%3Ddeployment-1%26tab%3Dhistory%23result',
      );
    });
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

  it('문서화되지 않은 backend detail 원문을 실행 오류로 표시하지 않는다', async () => {
    mockedWorkflowApi.runDeployment.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { detail: 'source_url=https://private.example/internal' },
      },
    });

    render(<AuthenticatedDeploymentRunPage />);
    await screen.findByRole('heading', { name: '사내 문서 질문 응답 봇' });

    fireEvent.change(screen.getByLabelText('질문'), {
      target: { value: '질문' },
    });
    fireEvent.click(screen.getByRole('button', { name: '실행' }));

    expect(
      await screen.findByText('실행 입력이 올바르지 않습니다.'),
    ).toBeVisible();
    expect(
      screen.queryByText('source_url=https://private.example/internal'),
    ).not.toBeInTheDocument();
  });
});
