import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MyModulePage from './page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/app/features/app/api/moduleOperationsApi', () => ({
  moduleOperationsApi: {
    listModuleOperations: vi.fn(),
  },
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

vi.mock('@/app/features/workflow/api/workflowApi', () => ({
  workflowApi: {
    getDeploymentParameterOptimization: vi.fn(),
  },
}));

const { moduleOperationsApi } = await import(
  '@/app/features/app/api/moduleOperationsApi'
);
const { apiClient } = await import('@/lib/apiClient');

const operationRow = (id: string, name: string) => ({
  app: {
    id,
    name,
    workflow_id: `workflow-${id}`,
    created_at: '2026-07-15T00:00:00.000Z',
    updated_at: '2026-07-15T00:00:00.000Z',
  },
  deployment: { state: 'undeployed' },
  deploymentState: 'undeployed',
  latestRun: { state: 'not_started' },
  permissionStatus: 'loaded',
  permission: { can_read: true },
  permissionSources: [],
  dataQuality: {
    permissionSourcesUnavailable: false,
    latestRunUnavailable: false,
  },
});

describe('내 모듈 데모 목록 순서', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(moduleOperationsApi.listModuleOperations).mockResolvedValue([
      operationRow('app-before', '기존 모듈'),
      operationRow('app-onboarding', '온보딩용 챗봇'),
      operationRow('app-after', '다른 모듈'),
    ] as never);
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { id: 'org-1', name: '데모 조직', is_manager: true },
    } as never);
  });

  afterEach(() => {
    cleanup();
  });

  it('온보딩용 챗봇을 첫 번째 운영 현황 행으로 표시한다', async () => {
    render(<MyModulePage />);

    await screen.findByText('온보딩용 챗봇');

    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('온보딩용 챗봇')).toBeInTheDocument();
    expect(within(rows[2]).getByText('기존 모듈')).toBeInTheDocument();
    expect(within(rows[3]).getByText('다른 모듈')).toBeInTheDocument();
  });
});
