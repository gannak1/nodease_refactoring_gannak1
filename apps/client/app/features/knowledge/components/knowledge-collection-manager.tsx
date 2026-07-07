'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  knowledgeApi,
  KnowledgeCollectionItemResponse,
  KnowledgeCollectionLinkCandidate,
  KnowledgeCollectionPermissionResponse,
  KnowledgeCollectionResponse,
  KnowledgeCollectionVisibility,
} from '@/app/features/knowledge/api/knowledgeApi';
import {
  CollectionDetailPanel,
  CollectionSidebar,
  type CollectionCapabilities,
  type CollectionFormState,
  type GrantFormState,
} from './knowledge-collection-manager-panels';

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
  const [capabilities, setCapabilities] = useState<CollectionCapabilities>({
    can_create_collection: false,
    can_change_public_visibility: false,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [form, setForm] = useState<CollectionFormState>({
    name: '',
    description: '',
  });
  const [editForm, setEditForm] = useState<CollectionFormState>({
    name: '',
    description: '',
  });
  const [grantForm, setGrantForm] = useState<GrantFormState>({
    subject_type: 'team',
    subject_id: '',
    permission_action: 'read',
  });
  const [acknowledgePublic, setAcknowledgePublic] = useState(false);

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedId) ?? null,
    [collections, selectedId],
  );

  const loadCollections = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const data = await knowledgeApi.getKnowledgeCollectionsResponse();
      setCollections(data.collections);
      setCapabilities({
        can_create_collection: data.can_create_collection,
        can_change_public_visibility: data.can_change_public_visibility,
      });
      setSelectedId((currentId) => currentId ?? data.collections[0]?.id ?? null);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadCollectionDetail = useCallback(async (
    collectionId: string,
    canManage: boolean,
  ) => {
    setIsDetailLoading(true);
    setErrorMessage(null);
    try {
      const itemData = await knowledgeApi.getKnowledgeCollectionItems(collectionId);
      setItems(itemData.items);
      if (!canManage) {
        setCandidates([]);
        setPermissions([]);
        return;
      }
      try {
        const [candidateData, permissionData] = await Promise.all([
          knowledgeApi.getKnowledgeCollectionLinkCandidates(collectionId),
          knowledgeApi.getKnowledgeCollectionPermissions(collectionId),
        ]);
        setCandidates(candidateData.candidates);
        setPermissions(permissionData.permissions);
      } catch (error) {
        setCandidates([]);
        setPermissions([]);
        setErrorMessage(errorText(error));
      }
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
    loadCollectionDetail(selectedCollection.id, selectedCollection.can_manage);
  }, [loadCollectionDetail, selectedCollection]);

  const refreshSelected = async () => {
    await loadCollections();
    if (selectedId) {
      await loadCollectionDetail(selectedId, selectedCollection?.can_manage ?? false);
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
      await loadCollectionDetail(
        selectedCollection.id,
        selectedCollection.can_manage,
      );
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
      await loadCollectionDetail(
        selectedCollection.id,
        selectedCollection.can_manage,
      );
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
      await loadCollectionDetail(
        selectedCollection.id,
        selectedCollection.can_manage,
      );
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
      await loadCollectionDetail(
        selectedCollection.id,
        selectedCollection.can_manage,
      );
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
        <CollectionSidebar
          capabilities={capabilities}
          collections={collections}
          form={form}
          isLoading={isLoading}
          isSaving={isSaving}
          selectedId={selectedId}
          onCreate={createCollection}
          onSelect={setSelectedId}
          setForm={setForm}
        />

        <div className="min-h-[480px] rounded-lg border border-slate-200 bg-white">
          <CollectionDetailPanel
            acknowledgePublic={acknowledgePublic}
            candidates={candidates}
            capabilities={capabilities}
            collection={selectedCollection}
            editForm={editForm}
            grantForm={grantForm}
            isDetailLoading={isDetailLoading}
            isSaving={isSaving}
            items={items}
            permissions={permissions}
            onArchive={archiveCollection}
            onGrantPermission={grantPermission}
            onLinkCandidate={linkCandidate}
            onRevokePermission={revokePermission}
            onUnlinkItem={unlinkItem}
            onUpdateCollection={updateCollection}
            onUpdateVisibility={updateVisibility}
            setAcknowledgePublic={setAcknowledgePublic}
            setEditForm={setEditForm}
            setGrantForm={setGrantForm}
          />
        </div>
      </section>
    </div>
  );
}
