'use client';

import { useState } from 'react';
import { isAxiosError } from 'axios';
import { Ban, KeyRound, Pencil, Plus, ShieldCheck, X } from 'lucide-react';
import { toast } from 'sonner';
import { DashboardPanel } from '@/app/features/dashboard/components/DashboardSurface';
import {
  externalActionCredentialApi,
  type ExternalActionCredentialOption,
  type ExternalActionCredentialProvider,
  type ExternalActionCredentialUpdateRequest,
} from '@/app/features/workflow/api/externalActionCredentialApi';

type CredentialEditor = {
  mode: 'create' | 'edit';
  credential?: ExternalActionCredentialOption;
  provider: ExternalActionCredentialProvider;
  credentialName: string;
  secret: string;
};

const PROVIDER_OPTIONS: Array<{
  value: ExternalActionCredentialProvider;
  label: string;
}> = [
  { value: 'github', label: 'GitHub' },
  { value: 'slack_api', label: 'Slack API' },
  { value: 'slack_webhook', label: 'Slack Incoming Webhook' },
];

const providerLabel = (provider: ExternalActionCredentialProvider) =>
  PROVIDER_OPTIONS.find((option) => option.value === provider)?.label ||
  provider;

const errorMessage = (error: unknown) => {
  if (isAxiosError(error)) {
    const data = error.response?.data as
      | { detail?: string; message?: string; error?: { message?: string } }
      | undefined;
    return (
      data?.detail || data?.message || data?.error?.message || error.message
    );
  }
  return error instanceof Error ? error.message : '작업에 실패했습니다.';
};

export function ExternalActionCredentialsPanel({
  credentials,
  onRefresh,
  onManagePermission,
}: {
  credentials: ExternalActionCredentialOption[];
  onRefresh: () => Promise<unknown>;
  onManagePermission: (credentialId: string) => void;
}) {
  const [editor, setEditor] = useState<CredentialEditor | null>(null);
  const [revokeTarget, setRevokeTarget] =
    useState<ExternalActionCredentialOption | null>(null);
  const [pending, setPending] = useState(false);

  const closeEditor = () => {
    if (!pending) setEditor(null);
  };

  const refreshAfterMutation = async () => {
    try {
      await onRefresh();
    } catch {
      toast.error(
        '변경은 저장됐지만 목록을 새로고치지 못했습니다. 다시 조회해 주세요.',
      );
    }
  };

  const submit = async () => {
    if (!editor || pending) return;
    const credentialName = editor.credentialName.trim();
    const nameChanged =
      editor.mode === 'edit' &&
      credentialName !== editor.credential?.credential_name;
    if (
      !credentialName ||
      (editor.mode === 'create' && !editor.secret) ||
      (editor.mode === 'edit' && !nameChanged && !editor.secret)
    ) {
      return;
    }

    setPending(true);
    try {
      if (editor.mode === 'create') {
        await externalActionCredentialApi.create({
          credential_name: credentialName,
          provider: editor.provider,
          secret: editor.secret,
        });
        setEditor(null);
        toast.success('외부 연동 Credential을 등록했습니다.');
      } else if (editor.credential) {
        const payload: ExternalActionCredentialUpdateRequest = {
          expected_revision: editor.credential.revision,
        };
        if (nameChanged) payload.credential_name = credentialName;
        if (editor.secret) payload.secret = editor.secret;
        await externalActionCredentialApi.update(editor.credential.id, payload);
        setEditor(null);
        toast.success('외부 연동 Credential을 수정했습니다.');
      }
      await refreshAfterMutation();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPending(false);
    }
  };

  const revoke = async () => {
    if (!revokeTarget || pending) return;
    setPending(true);
    try {
      await externalActionCredentialApi.revoke(
        revokeTarget.id,
        revokeTarget.revision,
      );
      setRevokeTarget(null);
      toast.success('외부 연동 Credential을 폐기했습니다.');
      await refreshAfterMutation();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPending(false);
    }
  };

  const editorName = editor?.credentialName.trim() || '';
  const editorNameChanged =
    editor?.mode === 'edit' &&
    editorName !== editor.credential?.credential_name;
  const submitDisabled =
    pending ||
    !editorName ||
    (editor?.mode === 'create'
      ? !editor.secret
      : !editorNameChanged && !editor?.secret);

  return (
    <>
      <DashboardPanel
        title="외부 연동 Credentials"
        icon={KeyRound}
        aside={
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-slate-500">
              Slack·GitHub 전용
            </span>
            <button
              type="button"
              onClick={() =>
                setEditor({
                  mode: 'create',
                  provider: 'github',
                  credentialName: '',
                  secret: '',
                })
              }
              disabled={pending}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Plus className="h-4 w-4" />
              외부 Credential 등록
            </button>
          </div>
        }
      >
        {credentials.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-500">
            등록된 외부 연동 Credential이 없습니다.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {credentials.map((credential) => (
              <div
                key={credential.id}
                className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-semibold text-slate-950">
                      {credential.credential_name}
                    </p>
                    <span
                      className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                        credential.status === 'active'
                          ? 'bg-green-50 text-green-700'
                          : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {credential.status === 'active' ? '사용 가능' : '폐기됨'}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {providerLabel(credential.provider)} · revision{' '}
                    {credential.revision}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    aria-label={`${credential.credential_name} 권한`}
                    onClick={() => onManagePermission(credential.id)}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    권한
                  </button>
                  {credential.status === 'active' && (
                    <>
                      <button
                        type="button"
                        aria-label={`${credential.credential_name} 수정`}
                        onClick={() =>
                          setEditor({
                            mode: 'edit',
                            credential,
                            provider: credential.provider,
                            credentialName: credential.credential_name,
                            secret: '',
                          })
                        }
                        disabled={pending}
                        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        수정
                      </button>
                      <button
                        type="button"
                        aria-label={`${credential.credential_name} 폐기`}
                        onClick={() => setRevokeTarget(credential)}
                        disabled={pending}
                        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-200 px-2.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-40"
                      >
                        <Ban className="h-3.5 w-3.5" />
                        폐기
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </DashboardPanel>

      {editor && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="external-credential-editor-title"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 px-4"
        >
          <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h2
                id="external-credential-editor-title"
                className="text-base font-semibold text-slate-950"
              >
                {editor.mode === 'create'
                  ? '외부 Credential 등록'
                  : '외부 Credential 수정'}
              </h2>
              <button
                type="button"
                aria-label="편집기 닫기"
                onClick={closeEditor}
                disabled={pending}
                className="rounded-md p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-slate-800">
                  Provider
                </span>
                <select
                  aria-label="Provider"
                  value={editor.provider}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      provider: event.target
                        .value as ExternalActionCredentialProvider,
                    })
                  }
                  disabled={editor.mode === 'edit' || pending}
                  className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 disabled:bg-slate-100"
                >
                  {PROVIDER_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-slate-800">
                  Credential 이름
                </span>
                <input
                  aria-label="Credential 이름"
                  value={editor.credentialName}
                  onChange={(event) =>
                    setEditor({ ...editor, credentialName: event.target.value })
                  }
                  disabled={pending}
                  maxLength={255}
                  className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-900"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-slate-800">
                  {editor.mode === 'create' ? 'Secret' : '새 Secret (선택)'}
                </span>
                <input
                  type="password"
                  autoComplete="new-password"
                  aria-label={
                    editor.mode === 'create' ? 'Secret' : '새 Secret (선택)'
                  }
                  value={editor.secret}
                  onChange={(event) =>
                    setEditor({ ...editor, secret: event.target.value })
                  }
                  disabled={pending}
                  maxLength={4096}
                  className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-900"
                />
              </label>
              <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
                <button
                  type="button"
                  onClick={closeEditor}
                  disabled={pending}
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                >
                  취소
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={submitDisabled}
                  className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {editor.mode === 'create' ? '등록' : '저장'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {revokeTarget && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="external-credential-revoke-title"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 px-4"
        >
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
            <h2
              id="external-credential-revoke-title"
              className="text-base font-semibold text-slate-950"
            >
              외부 Credential을 폐기할까요?
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              폐기 즉시 이 Credential을 참조하는 신규 실행과 provider 호출이
              차단됩니다.
            </p>
            <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
              {revokeTarget.credential_name}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRevokeTarget(null)}
                disabled={pending}
                className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 disabled:opacity-40"
              >
                취소
              </button>
              <button
                type="button"
                onClick={revoke}
                disabled={pending}
                className="h-9 rounded-md bg-red-600 px-3 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-40"
              >
                폐기 확인
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
