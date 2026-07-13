'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  AlertCircle,
  ArrowLeft,
  Loader2,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';

import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import { FinalResponseCard } from '@/app/features/workflow/components/execution/FinalResponseCard';
import type {
  DeploymentRunInfoResponse,
  InputVariable,
} from '@/app/features/workflow/types/Deployment';
import { getDeploymentRunFinalPreview } from '@/app/features/workflow/utils/deploymentRunResult';
import {
  claimLoginRedirectPath,
  getCurrentAuthReturnPath,
} from '@/lib/authReturn';

const isCheckboxVariable = (variable: InputVariable) =>
  variable.type === 'boolean' || variable.type === 'checkbox';

const readErrorMessage = (error: unknown) => {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { status?: unknown } }).response?.status ===
      'number'
  ) {
    const response = (error as { response: { status: number } }).response;
    if (response.status === 400 || response.status === 422) {
      return '실행 입력이 올바르지 않습니다.';
    }
    if (response.status === 401) return '로그인이 필요합니다.';
    if (response.status === 403) return '이 배포를 실행할 권한이 없습니다.';
    if (response.status === 404) {
      return '현재 조직에서 실행 가능한 배포를 찾을 수 없습니다.';
    }
    if (response.status === 409) {
      return '배포 상태가 변경되었습니다. 화면을 새로고침해 주세요.';
    }
    if (response.status === 429) {
      return '현재 실행 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.';
    }
    if (response.status === 504) {
      return '배포 실행 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.';
    }
    if (response.status >= 500) {
      return '배포 실행 중 서버 오류가 발생했습니다. 실행 로그를 확인하세요.';
    }
  }

  return '배포 실행에 실패했습니다.';
};

const isUnauthorized = (error: unknown) =>
  typeof error === 'object' &&
  error !== null &&
  'response' in error &&
  (error as { response?: { status?: unknown } }).response?.status === 401;

const defaultValueFor = (variable: InputVariable) =>
  isCheckboxVariable(variable) ? false : '';

const placeholderFor = (variable: InputVariable) =>
  variable.name === 'question' || variable.name === 'message'
    ? '질문을 입력하세요'
    : '';

const coerceInputValue = (variable: InputVariable, value: unknown) => {
  if (variable.type === 'number') {
    if (value === '' || value === null || value === undefined) return undefined;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (isCheckboxVariable(variable)) return Boolean(value);
  return typeof value === 'string' ? value : String(value ?? '');
};

const makeConversationId = () => {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
};

export default function AuthenticatedDeploymentRunPage() {
  const { push, replace } = useRouter();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const workflowId = params.id;
  const deploymentId = searchParams.get('deploymentId') || '';
  const [deployment, setDeployment] =
    useState<DeploymentRunInfoResponse | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [conversationId] = useState(makeConversationId);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [runError, setRunError] = useState('');
  const [runResult, setRunResult] = useState<unknown>(null);

  const variables = useMemo(
    () => deployment?.input_schema?.variables || [],
    [deployment?.input_schema?.variables],
  );
  const finalPreview = useMemo(
    () => getDeploymentRunFinalPreview(deployment, runResult),
    [deployment, runResult],
  );

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setLoadError('');

    if (!deploymentId) {
      setLoadError('실행할 배포 ID가 없습니다.');
      setIsLoading(false);
      return () => {
        active = false;
      };
    }

    workflowApi
      .getDeploymentRunInfo(deploymentId)
      .then((nextDeployment) => {
        if (!active) return;
        if (nextDeployment.workflow_id !== workflowId) {
          setDeployment(null);
          setInputs({});
          setLoadError('요청한 workflow와 배포 정보가 일치하지 않습니다.');
          return;
        }
        setDeployment(nextDeployment);
        const nextInputs: Record<string, unknown> = {};
        for (const variable of nextDeployment.input_schema?.variables || []) {
          nextInputs[variable.name] = defaultValueFor(variable);
        }
        setInputs(nextInputs);
      })
      .catch((error) => {
        if (!active) return;
        if (isUnauthorized(error)) {
          const redirectPath = claimLoginRedirectPath(
            getCurrentAuthReturnPath(),
          );
          if (redirectPath) replace(redirectPath);
          return;
        }
        setLoadError(readErrorMessage(error));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [deploymentId, replace, workflowId]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!deploymentId || isRunning) return;

    setRunError('');
    setRunResult(null);
    setIsRunning(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const variable of variables) {
        const value = inputs[variable.name];
        if (
          variable.required &&
          (value === '' || value === null || value === undefined)
        ) {
          throw new Error(`${variable.label || variable.name} 값을 입력하세요.`);
        }
        const coerced = coerceInputValue(variable, value);
        if (coerced !== undefined) payload[variable.name] = coerced;
      }

      const usesConversationControl =
        deployment?.type === 'chatbot' ||
        deployment?.type === 'internal_chatbot';

      setRunResult(
        await workflowApi.runDeployment(
          deploymentId,
          payload,
          usesConversationControl ? conversationId : undefined,
        ),
      );
    } catch (error) {
      setRunError(
        error instanceof Error && !('response' in error)
          ? error.message
          : readErrorMessage(error),
      );
    } finally {
      setIsRunning(false);
    }
  };

  const title = deployment?.name || '배포된 워크플로우 실행';

  return (
    <main className="h-full overflow-y-auto bg-slate-50 px-6 py-8 text-slate-900">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => push('/dashboard')}
              className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900"
            >
              <ArrowLeft className="h-4 w-4" />
              대시보드로 돌아가기
            </button>
            <p className="text-xs font-semibold text-emerald-700">
              내부 배포 실행
            </p>
            <h1 className="mt-2 truncate text-2xl font-bold text-slate-950">
              {title}
            </h1>
          </div>
          <span className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
            <ShieldCheck className="h-4 w-4" />
            사용자 권한 적용
          </span>
        </header>

        {loadError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
            {loadError}
          </div>
        )}

        {isLoading ? (
          <div className="flex min-h-56 items-center justify-center rounded-lg border border-slate-200 bg-white">
            <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
          </div>
        ) : (
          <section className="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <form
              onSubmit={handleSubmit}
              className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-slate-950">
                  실행 입력
                </h2>
                <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                  {workflowId}
                </span>
              </div>

              <div className="mt-5 flex flex-col gap-4">
                {variables.length === 0 ? (
                  <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-600">
                    이 배포는 입력 변수가 없습니다.
                  </p>
                ) : (
                  variables.map((variable) => (
                    <label key={variable.name} className="block">
                      <span className="text-sm font-semibold text-slate-700">
                        {variable.label || variable.name}
                        {variable.required && (
                          <span className="ml-1 text-red-500">*</span>
                        )}
                      </span>
                      {isCheckboxVariable(variable) ? (
                        <input
                          type="checkbox"
                          checked={Boolean(inputs[variable.name])}
                          onChange={(event) =>
                            setInputs((current) => ({
                              ...current,
                              [variable.name]: event.target.checked,
                            }))
                          }
                          className="mt-2 h-5 w-5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                        />
                      ) : variable.type === 'paragraph' ? (
                        <textarea
                          value={String(inputs[variable.name] ?? '')}
                          onChange={(event) =>
                            setInputs((current) => ({
                              ...current,
                              [variable.name]: event.target.value,
                            }))
                          }
                          rows={5}
                          placeholder={placeholderFor(variable)}
                          className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-100"
                        />
                      ) : (
                        <input
                          type={variable.type === 'number' ? 'number' : 'text'}
                          value={String(inputs[variable.name] ?? '')}
                          placeholder={placeholderFor(variable)}
                          onChange={(event) =>
                            setInputs((current) => ({
                              ...current,
                              [variable.name]: event.target.value,
                            }))
                          }
                          className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-100"
                        />
                      )}
                    </label>
                  ))
                )}
              </div>

              <button
                type="submit"
                disabled={isRunning || Boolean(loadError)}
                className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {isRunning ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {isRunning ? '실행 중' : '실행'}
              </button>
            </form>

            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-slate-950">
                  사용자 응답
                </h2>
                {runResult !== null && (
                  <button
                    type="button"
                    onClick={() => setRunResult(null)}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-900"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    초기화
                  </button>
                )}
              </div>

              {runError ? (
                <div className="mt-5 flex items-start gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="font-semibold">{runError}</span>
                </div>
              ) : runResult !== null ? (
                <div className="mt-5">
                  <FinalResponseCard preview={finalPreview} />
                </div>
              ) : (
                <div className="mt-5 rounded-md border border-dashed border-slate-300 bg-slate-50 px-4 py-12 text-center text-sm text-slate-500">
                  실행하면 최종 사용자가 받는 응답이 이 영역에 표시됩니다.
                </div>
              )}
            </section>
          </section>
        )}
      </div>
    </main>
  );
}
