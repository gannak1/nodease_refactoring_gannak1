import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MyModulePage from './page';

const routerMock = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
}));

vi.mock('@/app/features/app/api/moduleOperationsApi', () => ({
  moduleOperationsApi: {
    getModuleOperationsCostSummary: vi.fn(),
    listModuleOperations: vi.fn(),
  },
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

const { moduleOperationsApi } =
  await import('@/app/features/app/api/moduleOperationsApi');
const { apiClient } = await import('@/lib/apiClient');

const operationRow = {
  app: {
    id: 'app-1',
    name: '신입사원 온보딩',
    description: '새 동료의 입사 절차를 안내합니다.',
    workflow_id: 'workflow-1',
    created_at: '2026-07-11T00:00:00.000Z',
    updated_at: '2026-07-17T00:00:00.000Z',
    budget_status: { status: 'normal', usage_ratio: 0.42 },
    operation_metrics: {
      current_month_cost: 1,
      projected_month_cost: 2,
      previous_month_cost: 1,
      trend_percent: 10,
    },
  },
  deployment: { state: 'active', deployment_id: 'deployment-1' },
  deploymentState: 'active',
  latestRun: { state: 'success' },
  permissionStatus: 'loaded',
  permission: {
    can_read: true,
    can_execute: true,
    can_write: true,
    can_deploy: true,
    can_manage: true,
  },
  permissionSources: [],
  dataQuality: {
    permissionSourcesUnavailable: false,
    latestRunUnavailable: false,
  },
};

describe('워크플로우 운영 현황 보기 전환', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(moduleOperationsApi.listModuleOperations).mockResolvedValue([
      operationRow,
    ] as never);
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { id: 'org-1', name: '데모 조직', is_manager: true },
    } as never);
  });

  afterEach(() => {
    cleanup();
  });

  it('상단 비용 요약 카드를 표시하거나 전체 비용 요약 API를 호출하지 않는다', async () => {
    render(<MyModulePage />);

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: '워크플로우 목록',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: '워크플로우 목록',
      }).firstElementChild,
    ).toHaveClass('lucide-workflow');
    expect(
      screen.queryByRole('heading', { level: 1, name: '내 모듈' }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole('heading', {
        level: 3,
        name: '신입사원 온보딩',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '새 워크플로우' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('예상 월 비용')).not.toBeInTheDocument();
    expect(screen.queryByText('평균 증가 추세')).not.toBeInTheDocument();
    expect(screen.queryByText('예산 위험')).not.toBeInTheDocument();
    expect(screen.queryByText('비용 위험 신호')).not.toBeInTheDocument();
    expect(
      moduleOperationsApi.getModuleOperationsCostSummary,
    ).not.toHaveBeenCalled();
  });

  it('기본 그리드에서 리스트로 전환하고 선택을 저장한다', async () => {
    render(<MyModulePage />);

    expect(
      await screen.findByRole('heading', {
        level: 3,
        name: '신입사원 온보딩',
      }),
    ).toHaveClass('text-xl');
    expect(screen.getByRole('button', { name: '그리드 보기' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    fireEvent.click(screen.getByRole('button', { name: '리스트 보기' }));

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '리스트 보기' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(window.localStorage.getItem('mymodule:operations-view')).toBe(
      'list',
    );
  });

  it('저장된 그리드 보기를 다음 방문에 복원한다', async () => {
    window.localStorage.setItem('mymodule:operations-view', 'grid');

    render(<MyModulePage />);

    await waitFor(() => {
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      expect(
        screen.getByRole('heading', { level: 3, name: '신입사원 온보딩' }),
      ).toBeInTheDocument();
    });
  });
});
