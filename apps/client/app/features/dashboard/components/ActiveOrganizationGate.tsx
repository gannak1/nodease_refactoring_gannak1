'use client';

import { ReactNode, useEffect, useState } from 'react';
import {
  getStoredActiveOrganizationId,
  setActiveOrganizationId,
} from '@/lib/activeOrganization';
import { publicApiClient } from '@/lib/apiClient';

type OrganizationResponse = {
  id: string;
  name: string;
  is_manager?: boolean;
};

type ActiveOrganizationState =
  | { status: 'loading' }
  | { status: 'ready' }
  | { status: 'select'; organizations: OrganizationResponse[] }
  | { status: 'error'; message: string };

const ORGANIZATION_RESOLVE_MAX_ATTEMPTS = 5;
const ORGANIZATION_RESOLVE_RETRY_DELAY_MS = 750;
const TRANSIENT_ORGANIZATION_STATUS = new Set([502, 503, 504]);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const errorStatus = (error: unknown) => {
  if (!error || typeof error !== 'object') return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
};

const isTransientOrganizationError = (error: unknown) => {
  const status = errorStatus(error);
  if (status === null) {
    return true;
  }
  return TRANSIENT_ORGANIZATION_STATUS.has(status);
};

const organizationErrorMessage = (error: unknown) => {
  if (isTransientOrganizationError(error)) {
    return '조직 API가 아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요.';
  }
  return error instanceof Error
    ? error.message
    : '조직 정보를 확인하지 못했습니다.';
};

export default function ActiveOrganizationGate({
  children,
}: {
  children: ReactNode;
}) {
  const [state, setState] = useState<ActiveOrganizationState>({
    status: 'loading',
  });

  useEffect(() => {
    let ignore = false;

    const resolveOrganization = async () => {
      let lastError: unknown = null;

      for (
        let attempt = 1;
        attempt <= ORGANIZATION_RESOLVE_MAX_ATTEMPTS;
        attempt += 1
      ) {
        try {
          const response =
            await publicApiClient.get<OrganizationResponse[]>('/organizations');
          const organizations = response.data;

          if (!Array.isArray(organizations)) {
            throw new Error('조직 목록을 불러오지 못했습니다.');
          }

          const storedOrganizationId = getStoredActiveOrganizationId();
          const storedOrganization = organizations.find(
            (organization) => organization.id === storedOrganizationId,
          );
          if (storedOrganization) {
            if (!ignore) setState({ status: 'ready' });
            return;
          }

          if (organizations.length === 1) {
            setActiveOrganizationId(organizations[0].id);
            if (!ignore) setState({ status: 'ready' });
            return;
          }

          if (organizations.length > 1) {
            if (!ignore) {
              setState({ status: 'select', organizations });
            }
            return;
          }

          throw new Error('접근 가능한 조직이 없습니다.');
        } catch (err) {
          lastError = err;
          if (
            ignore ||
            !isTransientOrganizationError(err) ||
            attempt === ORGANIZATION_RESOLVE_MAX_ATTEMPTS
          ) {
            break;
          }
          await sleep(ORGANIZATION_RESOLVE_RETRY_DELAY_MS * attempt);
        }
      }

      if (!ignore) {
        setState({
          status: 'error',
          message: organizationErrorMessage(lastError),
        });
      }
    };

    resolveOrganization();

    return () => {
      ignore = true;
    };
  }, []);

  const selectOrganization = (organizationId: string) => {
    setActiveOrganizationId(organizationId);
    setState({ status: 'ready' });
  };

  if (state.status === 'ready') {
    return <>{children}</>;
  }

  return (
    <div className="grid h-screen place-items-center bg-slate-50 px-6 text-slate-950">
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        {state.status === 'loading' && (
          <>
            <h1 className="text-lg font-semibold">조직 확인 중</h1>
            <p className="mt-2 text-sm text-slate-600">
              현재 작업할 조직을 확인하고 있습니다.
            </p>
          </>
        )}

        {state.status === 'error' && (
          <>
            <h1 className="text-lg font-semibold">조직을 확인할 수 없습니다</h1>
            <p className="mt-2 text-sm text-slate-600">{state.message}</p>
          </>
        )}

        {state.status === 'select' && (
          <>
            <h1 className="text-lg font-semibold">작업 조직 선택</h1>
            <p className="mt-2 text-sm text-slate-600">
              Nodease에서 사용할 조직을 선택해주세요.
            </p>
            <div className="mt-5 space-y-2">
              {state.organizations.map((organization) => (
                <button
                  key={organization.id}
                  onClick={() => selectOrganization(organization.id)}
                  className="flex w-full items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-left text-sm font-medium hover:border-blue-300 hover:bg-blue-50"
                >
                  <span className="truncate">{organization.name}</span>
                  <span className="ml-3 shrink-0 text-xs text-slate-500">
                    {organization.is_manager ? '관리자' : '멤버'}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
