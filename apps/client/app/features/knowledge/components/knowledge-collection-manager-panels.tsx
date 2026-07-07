'use client';

import type { Dispatch, SetStateAction } from 'react';
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
import type {
  KnowledgeCollectionAction,
  KnowledgeCollectionItemResponse,
  KnowledgeCollectionLinkCandidate,
  KnowledgeCollectionPermissionResponse,
  KnowledgeCollectionResponse,
  KnowledgeCollectionVisibility,
} from '@/app/features/knowledge/api/knowledgeApi';

export type CollectionCapabilities = {
  can_create_collection: boolean;
  can_change_public_visibility: boolean;
};

export type CollectionFormState = {
  name: string;
  description: string;
};

export type GrantFormState = {
  subject_type: 'team' | 'user';
  subject_id: string;
  permission_action: KnowledgeCollectionAction;
};

const collectionActions: KnowledgeCollectionAction[] = [
  'read',
  'route',
  'manage',
  'sync',
];

type CollectionSidebarProps = {
  capabilities: CollectionCapabilities;
  collections: KnowledgeCollectionResponse[];
  form: CollectionFormState;
  isLoading: boolean;
  isSaving: boolean;
  selectedId: string | null;
  onCreate: () => void;
  onSelect: (collectionId: string) => void;
  setForm: Dispatch<SetStateAction<CollectionFormState>>;
};

export function CollectionSidebar({
  capabilities,
  collections,
  form,
  isLoading,
  isSaving,
  selectedId,
  onCreate,
  onSelect,
  setForm,
}: CollectionSidebarProps) {
  return (
    <div className="space-y-4">
      {capabilities.can_create_collection && (
        <CollectionCreatePanel
          form={form}
          isSaving={isSaving}
          onCreate={onCreate}
          setForm={setForm}
        />
      )}

      <CollectionListPanel
        collections={collections}
        isLoading={isLoading}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  );
}

type CollectionCreatePanelProps = {
  form: CollectionFormState;
  isSaving: boolean;
  onCreate: () => void;
  setForm: Dispatch<SetStateAction<CollectionFormState>>;
};

function CollectionCreatePanel({
  form,
  isSaving,
  onCreate,
  setForm,
}: CollectionCreatePanelProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <FolderPlus className="h-4 w-4 text-blue-600" />
        <h2 className="text-sm font-bold text-slate-900">Collection 생성</h2>
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
          onClick={onCreate}
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
  );
}

type CollectionListPanelProps = {
  collections: KnowledgeCollectionResponse[];
  isLoading: boolean;
  selectedId: string | null;
  onSelect: (collectionId: string) => void;
};

function CollectionListPanel({
  collections,
  isLoading,
  selectedId,
  onSelect,
}: CollectionListPanelProps) {
  return (
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
              onClick={() => onSelect(collection.id)}
              className={`w-full px-4 py-3 text-left transition-colors ${
                selectedId === collection.id ? 'bg-blue-50' : 'hover:bg-slate-50'
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
  );
}

type CollectionDetailPanelProps = {
  acknowledgePublic: boolean;
  candidates: KnowledgeCollectionLinkCandidate[];
  capabilities: CollectionCapabilities;
  collection: KnowledgeCollectionResponse | null;
  editForm: CollectionFormState;
  grantForm: GrantFormState;
  isDetailLoading: boolean;
  isSaving: boolean;
  items: KnowledgeCollectionItemResponse[];
  permissions: KnowledgeCollectionPermissionResponse[];
  onArchive: () => void;
  onGrantPermission: () => void;
  onLinkCandidate: (candidateId: string) => void;
  onRevokePermission: (permissionId: string) => void;
  onUnlinkItem: (itemId: string) => void;
  onUpdateCollection: () => void;
  onUpdateVisibility: (visibility: KnowledgeCollectionVisibility) => void;
  setAcknowledgePublic: Dispatch<SetStateAction<boolean>>;
  setEditForm: Dispatch<SetStateAction<CollectionFormState>>;
  setGrantForm: Dispatch<SetStateAction<GrantFormState>>;
};

export function CollectionDetailPanel({
  acknowledgePublic,
  candidates,
  capabilities,
  collection,
  editForm,
  grantForm,
  isDetailLoading,
  isSaving,
  items,
  permissions,
  onArchive,
  onGrantPermission,
  onLinkCandidate,
  onRevokePermission,
  onUnlinkItem,
  onUpdateCollection,
  onUpdateVisibility,
  setAcknowledgePublic,
  setEditForm,
  setGrantForm,
}: CollectionDetailPanelProps) {
  if (!collection) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-slate-500">
        Collection을 선택하세요.
      </div>
    );
  }

  return (
    <div className="space-y-6 p-5">
      <CollectionHeader
        collection={collection}
        isSaving={isSaving}
        onArchive={onArchive}
      />

      <section className="grid gap-4 md:grid-cols-2">
        <CollectionInfoPanel
          collection={collection}
          editForm={editForm}
          isSaving={isSaving}
          onUpdateCollection={onUpdateCollection}
          setEditForm={setEditForm}
        />
        <CollectionVisibilityPanel
          acknowledgePublic={acknowledgePublic}
          canChangeVisibility={capabilities.can_change_public_visibility}
          collection={collection}
          isSaving={isSaving}
          onUpdateVisibility={onUpdateVisibility}
          setAcknowledgePublic={setAcknowledgePublic}
        />
      </section>

      <CollectionItemsPanel
        candidates={candidates}
        collection={collection}
        isDetailLoading={isDetailLoading}
        isSaving={isSaving}
        items={items}
        onLinkCandidate={onLinkCandidate}
        onUnlinkItem={onUnlinkItem}
      />

      <CollectionPermissionsPanel
        collection={collection}
        grantForm={grantForm}
        isSaving={isSaving}
        permissions={permissions}
        onGrantPermission={onGrantPermission}
        onRevokePermission={onRevokePermission}
        setGrantForm={setGrantForm}
      />

      {collection.visibility === 'public' && <PublicCollectionWarning />}
    </div>
  );
}

type CollectionHeaderProps = {
  collection: KnowledgeCollectionResponse;
  isSaving: boolean;
  onArchive: () => void;
};

function CollectionHeader({
  collection,
  isSaving,
  onArchive,
}: CollectionHeaderProps) {
  return (
    <header className="flex flex-col gap-3 border-b border-slate-100 pb-5 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <h2 className="truncate text-lg font-bold text-slate-950">
          {collection.name}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {collection.description || '설명 없음'}
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
            {collection.lifecycle_state}
          </span>
          <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
            {collection.sync_state}
          </span>
          <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">
            KB {collection.linked_kb_count_bucket}
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onArchive}
        disabled={isSaving || !collection.can_manage}
        className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:text-slate-300"
      >
        <Archive className="h-4 w-4" />
        Archive
      </button>
    </header>
  );
}

type CollectionInfoPanelProps = {
  collection: KnowledgeCollectionResponse;
  editForm: CollectionFormState;
  isSaving: boolean;
  onUpdateCollection: () => void;
  setEditForm: Dispatch<SetStateAction<CollectionFormState>>;
};

function CollectionInfoPanel({
  collection,
  editForm,
  isSaving,
  onUpdateCollection,
  setEditForm,
}: CollectionInfoPanelProps) {
  const isEditable = collection.can_manage && !collection.is_system_managed;

  return (
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
          disabled={!isEditable}
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
          disabled={!isEditable}
          rows={3}
          className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
        />
        <button
          type="button"
          onClick={onUpdateCollection}
          disabled={isSaving || !isEditable || !editForm.name.trim()}
          className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Check className="h-4 w-4" />
          저장
        </button>
      </div>
    </div>
  );
}

type CollectionVisibilityPanelProps = {
  acknowledgePublic: boolean;
  canChangeVisibility: boolean;
  collection: KnowledgeCollectionResponse;
  isSaving: boolean;
  onUpdateVisibility: (visibility: KnowledgeCollectionVisibility) => void;
  setAcknowledgePublic: Dispatch<SetStateAction<boolean>>;
};

function CollectionVisibilityPanel({
  acknowledgePublic,
  canChangeVisibility,
  collection,
  isSaving,
  onUpdateVisibility,
  setAcknowledgePublic,
}: CollectionVisibilityPanelProps) {
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex items-center gap-2">
        {collection.visibility === 'public' ? (
          <Eye className="h-4 w-4 text-emerald-600" />
        ) : (
          <EyeOff className="h-4 w-4 text-slate-500" />
        )}
        <h3 className="text-sm font-bold text-slate-900">공개 상태</h3>
      </div>
      <p className="text-sm font-semibold text-slate-700">
        {collection.visibility === 'public' ? 'public' : 'private'}
      </p>
      {canChangeVisibility ? (
        <>
          <label className="mt-4 flex items-start gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={acknowledgePublic}
              onChange={(event) => setAcknowledgePublic(event.target.checked)}
              className="mt-1"
            />
            <span>
              public 전환 시 execution subject 없는 RAG 후보가 될 수 있음을
              확인했습니다.
            </span>
          </label>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => onUpdateVisibility('public')}
              disabled={
                isSaving ||
                !acknowledgePublic ||
                collection.visibility === 'public'
              }
              className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              public
            </button>
            <button
              type="button"
              onClick={() => onUpdateVisibility('private')}
              disabled={isSaving || collection.visibility === 'private'}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              private
            </button>
          </div>
        </>
      ) : (
        <p className="mt-4 text-sm text-slate-500">
          공개 상태 전환은 organization manager만 수행할 수 있습니다.
        </p>
      )}
    </div>
  );
}

type CollectionItemsPanelProps = {
  candidates: KnowledgeCollectionLinkCandidate[];
  collection: KnowledgeCollectionResponse;
  isDetailLoading: boolean;
  isSaving: boolean;
  items: KnowledgeCollectionItemResponse[];
  onLinkCandidate: (candidateId: string) => void;
  onUnlinkItem: (itemId: string) => void;
};

function CollectionItemsPanel({
  candidates,
  collection,
  isDetailLoading,
  isSaving,
  items,
  onLinkCandidate,
  onUnlinkItem,
}: CollectionItemsPanelProps) {
  return (
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
                  onClick={() => onUnlinkItem(item.item_id)}
                  disabled={
                    isSaving ||
                    !collection.can_manage ||
                    !item.can_manage_kb
                  }
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
                  onClick={() => onLinkCandidate(candidate.knowledge_base_id)}
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
  );
}

type CollectionPermissionsPanelProps = {
  collection: KnowledgeCollectionResponse;
  grantForm: GrantFormState;
  isSaving: boolean;
  permissions: KnowledgeCollectionPermissionResponse[];
  onGrantPermission: () => void;
  onRevokePermission: (permissionId: string) => void;
  setGrantForm: Dispatch<SetStateAction<GrantFormState>>;
};

function CollectionPermissionsPanel({
  collection,
  grantForm,
  isSaving,
  permissions,
  onGrantPermission,
  onRevokePermission,
  setGrantForm,
}: CollectionPermissionsPanelProps) {
  return (
    <section className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Users className="h-4 w-4 text-slate-600" />
        <h3 className="text-sm font-bold text-slate-900">권한</h3>
      </div>
      {collection.can_manage ? (
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
                permission_action: event.target.value as KnowledgeCollectionAction,
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
            onClick={onGrantPermission}
            disabled={isSaving || !grantForm.subject_id.trim()}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            부여
          </button>
        </div>
      ) : (
        <p className="mb-4 text-sm text-slate-500">
          권한 관리는 collection.manage 권한이 필요합니다.
        </p>
      )}
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
                  {permission.subject_safe_label || permission.subject_id}
                </span>
                <span className="ml-2 text-slate-500">
                  {permission.subject_type} · {permission.permission_action}
                </span>
              </div>
              <button
                type="button"
                onClick={() => onRevokePermission(permission.permission_id)}
                disabled={isSaving || !collection.can_manage}
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
  );
}

function PublicCollectionWarning() {
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        public Collection은 anonymous public-only RAG 후보에 포함될 수 있습니다.
        인증 사용자 KB use 권한을 부여하는 것은 아닙니다.
      </span>
    </div>
  );
}
