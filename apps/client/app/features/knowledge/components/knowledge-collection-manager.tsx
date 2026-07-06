'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Archive,
  Check,
  Eye,
  EyeOff,
  FolderPlus,
  Link2,
  Loader2,
  Plus,
  ShieldAlert,
  Trash2,
  Users,
} from 'lucide-react';
import {
  knowledgeApi,
  KnowledgeCollectionAction,
  KnowledgeCollectionItemResponse,
  KnowledgeCollectionLinkCandidate,
  KnowledgeCollectionPermissionResponse,
  KnowledgeCollectionResponse,
  KnowledgeCollectionVisibility,
} from '@/app/features/knowledge/api/knowledgeApi';

const collectionActions: KnowledgeCollectionAction[] = [
  'read',
  'route',
  'manage',
  'sync',
];

const errorText = (error: unknown) => {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { data?: { error?: { message?: string } } } })
      .response?.data?.error?.message === 'string'
  ) {
    return (error as { response: { data: { error: { message: string } } } })
      .response.data.error.message;
  }
  return '요청을 처리하지 못했습니다.';
};

export default function KnowledgeCollectionManager() {
  const [collections, setCollections] = useState<KnowledgeCollectionResponse[]>(
    [],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<KnowledgeCollectionItemResponse[]>([]);
  const [candidates, setCandidates] = useState<KnowledgeCollectionLinkCandidate[]>(
    [],
  );
  const [permissions, setPermissions] = useState<
    KnowledgeCollectionPermissionResponse[]
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [form, setForm] = useState({ name: '', description: '' });
  const [editForm, setEditForm] = useState({ name: '', description: '' });
  const [grantForm, setGrantForm] = useState<{
    subject_type: 'team' | 'user';
    subject_id: string;
    permission_action: KnowledgeCollectionAction;
  }>({ subject_type: 'team', subject_id: '', permission_action: 'read' });
  const [acknowledgePublic, setAcknowledgePublic] = useState(false);

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedId) ?? null,
    [collections, selectedId],
  );

  const loadCollections = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const data = await knowledgeApi.getKnowledgeCollections();
      setCollections(data);
      setSelectedId((currentId) => currentId ?? data[0]?.id ?? null);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadCollectionDetail = useCallback(async (collectionId: string) => {
    setIsDetailLoading(true);
    setErrorMessage(null);
    try {
      const [itemData, candidateData, permissionData] = await Promise.all([
        knowledgeApi.getKnowledgeCollectionItems(collectionId),
        knowledgeApi.getKnowledgeCollectionLinkCandidates(collectionId),
        knowledgeApi.getKnowledgeCollectionPermissions(collectionId),
      ]);
      setItems(itemData.items);
      setCandidates(candidateData.candidates);
      setPermissions(permissionData.permissions);
    } catch (error) {
      setItems([]);
      setCandidates([]);
      setPermissions([]);
      setErrorMessage(errorText(error));
    } finally {
      setIsDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCollections();
  }, [loadCollections]);

  useEffect(() => {
    if (!selectedCollection) return;
    setEditForm({
      name: selectedCollection.name,
      description: selectedCollection.description ?? '',
    });
    setAcknowledgePublic(false);
    loadCollectionDetail(selectedCollection.id);
  }, [loadCollectionDetail, selectedCollection]);

  const refreshSelected = async () => {
    await loadCollections();
    if (selectedId) {
      await loadCollectionDetail(selectedId);
    }
  };

  const createCollection = async () => {
    if (!form.name.trim()) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      const created = await knowledgeApi.createKnowledgeCollection({
        name: form.name.trim(),
        description: form.description.trim() || null,
      });
      setForm({ name: '', description: '' });
      await loadCollections();
      setSelectedId(created.id);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const updateCollection = async () => {
    if (!selectedCollection || !editForm.name.trim()) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.updateKnowledgeCollection(selectedCollection.id, {
        name: editForm.name.trim(),
        description: editForm.description.trim() || null,
      });
      await refreshSelected();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const archiveCollection = async () => {
    if (!selectedCollection) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.archiveKnowledgeCollection(selectedCollection.id);
      setSelectedId(null);
      await loadCollections();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const linkCandidate = async (candidateId: string) => {
    if (!selectedCollection) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.linkKnowledgeCollectionItem(selectedCollection.id, {
        knowledge_base_id: candidateId,
      });
      await loadCollectionDetail(selectedCollection.id);
      await loadCollections();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const unlinkItem = async (itemId: string) => {
    if (!selectedCollection) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.unlinkKnowledgeCollectionItem(
        selectedCollection.id,
        itemId,
      );
      await loadCollectionDetail(selectedCollection.id);
      await loadCollections();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const grantPermission = async () => {
    if (!selectedCollection || !grantForm.subject_id.trim()) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.grantKnowledgeCollectionPermission(
        selectedCollection.id,
        {
          ...grantForm,
          subject_id: grantForm.subject_id.trim(),
        },
      );
      setGrantForm({
        subject_type: 'team',
        subject_id: '',
        permission_action: 'read',
      });
      await loadCollectionDetail(selectedCollection.id);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const revokePermission = async (permissionId: string) => {
    if (!selectedCollection) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.revokeKnowledgeCollectionPermission(
        selectedCollection.id,
        permissionId,
      );
      await loadCollectionDetail(selectedCollection.id);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const updateVisibility = async (visibility: KnowledgeCollectionVisibility) => {
    if (!selectedCollection) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.updateKnowledgeCollectionVisibility(selectedCollection.id, {
        visibility,
        acknowledged_public_runtime_exposure:
          visibility === 'public' ? acknowledgePublic : true,
      });
      setAcknowledgePublic(false);
      await refreshSelected();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {errorMessage && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {errorMessage}
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2">
              <FolderPlus className="h-4 w-4 text-blue-600" />
              <h2 className="text-sm font-bold text-slate-900">
                Collection 생성
              </h2>
            </div>
            <div className="space-y-3">
              <input
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder="Collection 이름"
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <textarea
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
                placeholder="설명"
                rows={3}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <button
                type="button"
                onClick={createCollection}
                disabled={isSaving || !form.name.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {isSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                생성
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-bold text-slate-900">
                Knowledge Collections
              </h2>
            </div>
            {isLoading ? (
              <div className="flex h-32 items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
              </div>
            ) : collections.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-500">
                등록된 Collection이 없습니다.
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {collections.map((collection) => (
                  <button
                    key={collection.id}
                    type="button"
                    onClick={() => setSelectedId(collection.id)}
                    className={`w-full px-4 py-3 text-left transition-colors ${
                      selectedId === collection.id
                        ? 'bg-blue-50'
                        : 'hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-semibold text-slate-900">
                        {collection.name}
                      </span>
                      <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                        {collection.visibility === 'public' ? 'public' : 'private'}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-500">
                      {collection.description || '설명 없음'}
                    </p>
                    <div className="mt-2 flex gap-2 text-xs text-slate-500">
                      <span>KB {collection.linked_kb_count_bucket}</span>
                      <span>{collection.is_system_managed ? 'system' : 'manual'}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="min-h-[480px] rounded-lg border border-slate-200 bg-white">
          {!selectedCollection ? (
            <div className="flex h-full items-center justify-center p-8 text-sm text-slate-500">
              Collection을 선택하세요.
            </div>
          ) : (
            <div className="space-y-6 p-5">
              <header className="flex flex-col gap-3 border-b border-slate-100 pb-5 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0">
                  <h2 className="truncate text-lg font-bold text-slate-950">
                    {selectedCollection.name}
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {selectedCollection.description || '설명 없음'}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
                      {selectedCollection.lifecycle_state}
                    </span>
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
                      {selectedCollection.sync_state}
                    </span>
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
                      KB {selectedCollection.linked_kb_count_bucket}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={archiveCollection}
                  disabled={isSaving || !selectedCollection.can_manage}
                  className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:text-slate-300"
                >
                  <Archive className="h-4 w-4" />
                  Archive
                </button>
              </header>

              <section className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-slate-200 p-4">
                  <h3 className="mb-3 text-sm font-bold text-slate-900">정보</h3>
                  <div className="space-y-3">
                    <input
                      value={editForm.name}
                      onChange={(event) =>
                        setEditForm((current) => ({
                          ...current,
                          name: event.target.value,
                        }))
                      }
                      disabled={
                        !selectedCollection.can_manage ||
                        selectedCollection.is_system_managed
                      }
                      className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
                    />
                    <textarea
                      value={editForm.description}
                      onChange={(event) =>
                        setEditForm((current) => ({
                          ...current,
                          description: event.target.value,
                        }))
                      }
                      disabled={
                        !selectedCollection.can_manage ||
                        selectedCollection.is_system_managed
                      }
                      rows={3}
                      className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
                    />
                    <button
                      type="button"
                      onClick={updateCollection}
                      disabled={
                        isSaving ||
                        !selectedCollection.can_manage ||
                        selectedCollection.is_system_managed ||
                        !editForm.name.trim()
                      }
                      className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      <Check className="h-4 w-4" />
                      저장
                    </button>
                  </div>
                </div>

                <div className="rounded-lg border border-slate-200 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    {selectedCollection.visibility === 'public' ? (
                      <Eye className="h-4 w-4 text-emerald-600" />
                    ) : (
                      <EyeOff className="h-4 w-4 text-slate-500" />
                    )}
                    <h3 className="text-sm font-bold text-slate-900">공개 상태</h3>
                  </div>
                  <p className="text-sm font-semibold text-slate-700">
                    {selectedCollection.visibility === 'public'
                      ? 'public'
                      : 'private'}
                  </p>
                  <label className="mt-4 flex items-start gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={acknowledgePublic}
                      onChange={(event) =>
                        setAcknowledgePublic(event.target.checked)
                      }
                      className="mt-1"
                    />
                    <span>
                      public 전환 시 execution subject 없는 RAG 후보가 될 수
                      있음을 확인했습니다.
                    </span>
                  </label>
                  <div className="mt-4 flex gap-2">
                    <button
                      type="button"
                      onClick={() => updateVisibility('public')}
                      disabled={
                        isSaving ||
                        !acknowledgePublic ||
                        selectedCollection.visibility === 'public'
                      }
                      className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      public
                    </button>
                    <button
                      type="button"
                      onClick={() => updateVisibility('private')}
                      disabled={isSaving || selectedCollection.visibility === 'private'}
                      className="rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:text-slate-300"
                    >
                      private
                    </button>
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Link2 className="h-4 w-4 text-blue-600" />
                  <h3 className="text-sm font-bold text-slate-900">연결된 KB</h3>
                  {isDetailLoading && (
                    <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                  )}
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-2">
                    {items.length === 0 ? (
                      <p className="text-sm text-slate-500">연결된 KB가 없습니다.</p>
                    ) : (
                      items.map((item) => (
                        <div
                          key={item.item_id}
                          className="flex items-center justify-between gap-3 rounded-md border border-slate-100 px-3 py-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-slate-800">
                              {item.safe_label || 'Knowledge Base'}
                            </p>
                            <p className="text-xs text-slate-500">
                              use {item.can_use_kb ? '가능' : '불가'} · manage{' '}
                              {item.can_manage_kb ? '가능' : '불가'}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() => unlinkItem(item.item_id)}
                            disabled={isSaving || !item.can_manage_kb}
                            className="rounded-md p-2 text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:text-slate-300"
                            aria-label="KB 연결 해제"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                  <div className="space-y-2">
                    {candidates.length === 0 ? (
                      <p className="text-sm text-slate-500">연결 후보가 없습니다.</p>
                    ) : (
                      candidates.map((candidate) => (
                        <div
                          key={candidate.knowledge_base_id}
                          className="flex items-center justify-between gap-3 rounded-md border border-slate-100 px-3 py-2"
                        >
                          <span className="truncate text-sm font-semibold text-slate-800">
                            {candidate.safe_label || 'Knowledge Base'}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              linkCandidate(candidate.knowledge_base_id)
                            }
                            disabled={isSaving || candidate.disabled}
                            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                          >
                            추가
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Users className="h-4 w-4 text-slate-600" />
                  <h3 className="text-sm font-bold text-slate-900">권한</h3>
                </div>
                <div className="mb-4 grid gap-2 md:grid-cols-[120px_1fr_140px_auto]">
                  <select
                    value={grantForm.subject_type}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        subject_type: event.target.value as 'team' | 'user',
                      }))
                    }
                    className="rounded-md border border-slate-200 px-3 py-2 text-sm"
                  >
                    <option value="team">team</option>
                    <option value="user">user</option>
                  </select>
                  <input
                    value={grantForm.subject_id}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        subject_id: event.target.value,
                      }))
                    }
                    placeholder="subject id"
                    className="rounded-md border border-slate-200 px-3 py-2 text-sm"
                  />
                  <select
                    value={grantForm.permission_action}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        permission_action: event.target
                          .value as KnowledgeCollectionAction,
                      }))
                    }
                    className="rounded-md border border-slate-200 px-3 py-2 text-sm"
                  >
                    {collectionActions.map((action) => (
                      <option key={action} value={action}>
                        {action}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={grantPermission}
                    disabled={isSaving || !grantForm.subject_id.trim()}
                    className="rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    부여
                  </button>
                </div>
                {permissions.length === 0 ? (
                  <p className="text-sm text-slate-500">표시할 권한이 없습니다.</p>
                ) : (
                  <div className="space-y-2">
                    {permissions.map((permission) => (
                      <div
                        key={permission.permission_id}
                        className="flex items-center justify-between gap-3 rounded-md border border-slate-100 px-3 py-2"
                      >
                        <div className="min-w-0 text-sm">
                          <span className="font-semibold text-slate-800">
                            {permission.subject_safe_label ||
                              permission.subject_id}
                          </span>
                          <span className="ml-2 text-slate-500">
                            {permission.subject_type} ·{' '}
                            {permission.permission_action}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            revokePermission(permission.permission_id)
                          }
                          disabled={isSaving}
                          className="rounded-md p-2 text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:text-slate-300"
                          aria-label="권한 회수"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {selectedCollection.visibility === 'public' && (
                <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    public Collection은 anonymous public-only RAG 후보에 포함될 수
                    있습니다. 인증 사용자 KB use 권한을 부여하는 것은 아닙니다.
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
