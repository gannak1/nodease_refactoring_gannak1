'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  knowledgeApi,
  KnowledgeCollectionItemResponse,
  KnowledgeCollectionLinkCandidate,
  KnowledgeCollectionPermissionResponse,
  KnowledgeCollectionResponse,
  KnowledgeCollectionVisibility,
  KnowledgeDelegationSubjectsResponse,
  KnowledgeDomainAction,
  KnowledgeDomainPermissionListResponse,
} from '@/app/features/knowledge/api/knowledgeApi';
import {
  CollectionDetailPanel,
  CollectionSidebar,
  DomainDelegationPanel,
  type CollectionCapabilities,
  type CollectionFormState,
  type DomainGrantFormState,
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

const CLOSED_COLLECTION_CAPABILITIES: CollectionCapabilities = {
  can_create_collection: false,
  can_change_public_visibility: false,
  can_manage_catalog: false,
  can_delegate_permissions: false,
  can_manage_lifecycle: false,
  can_manage_domain_permissions: false,
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
  const [subjects, setSubjects] = useState<KnowledgeDelegationSubjectsResponse>({
    teams: [],
    users: [],
  });
  const [domainPermissions, setDomainPermissions] = useState<
    KnowledgeDomainPermissionListResponse['permissions']
  >([]);
  const [domainSubjects, setDomainSubjects] =
    useState<KnowledgeDelegationSubjectsResponse>({ teams: [], users: [] });
  const [capabilities, setCapabilities] = useState<CollectionCapabilities>({
    ...CLOSED_COLLECTION_CAPABILITIES,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [form, setForm] = useState<CollectionFormState>({
    name: '',
    description: '',
    safeLabel: '',
  });
  const [editForm, setEditForm] = useState<CollectionFormState>({
    name: '',
    description: '',
    safeLabel: '',
  });
  const [grantForm, setGrantForm] = useState<GrantFormState>({
    subject_type: 'team',
    subject_id: '',
    role_bundle: 'viewer',
  });
  const [acknowledgePublic, setAcknowledgePublic] = useState(false);
  const [domainGrantForm, setDomainGrantForm] = useState<DomainGrantFormState>({
    subject_type: 'team',
    subject_id: '',
    permission_action: 'catalog_manage',
  });

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedId) ?? null,
    [collections, selectedId],
  );

  const loadCollections = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const [data, domainCapabilities] = await Promise.all([
        knowledgeApi.getKnowledgeCollectionsResponse(),
        knowledgeApi.getKnowledgeDomainCapabilities(),
      ]);
      setCollections(data.collections);
      setCapabilities({
        can_create_collection: domainCapabilities.can_create_collection,
        can_change_public_visibility:
          domainCapabilities.can_change_public_visibility,
        can_manage_catalog: domainCapabilities.can_create_collection,
        can_delegate_permissions:
          domainCapabilities.can_delegate_permissions,
        can_manage_lifecycle: domainCapabilities.can_manage_lifecycle,
        can_manage_domain_permissions:
          domainCapabilities.can_manage_domain_permissions,
      });
      if (domainCapabilities.can_manage_domain_permissions) {
        const [permissionData, subjectData] = await Promise.all([
          knowledgeApi.getKnowledgeDomainPermissions(),
          knowledgeApi.getKnowledgeDomainDelegationSubjects(),
        ]);
        setDomainPermissions(permissionData.permissions);
        setDomainSubjects(subjectData);
      } else {
        setDomainPermissions([]);
        setDomainSubjects({ teams: [], users: [] });
      }
      setSelectedId((currentId) => currentId ?? data.collections[0]?.id ?? null);
    } catch (error) {
      setCapabilities({ ...CLOSED_COLLECTION_CAPABILITIES });
      setErrorMessage(errorText(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadCollectionDetail = useCallback(async (
    collection: KnowledgeCollectionResponse,
    currentCapabilities: CollectionCapabilities,
  ) => {
    setIsDetailLoading(true);
    setErrorMessage(null);
    try {
      const canManageCatalog =
        collection.can_manage || currentCapabilities.can_manage_catalog;
      const canDelegate =
        collection.can_manage || currentCapabilities.can_delegate_permissions;
      const [itemData, candidateData, permissionData, subjectData] =
        await Promise.all([
          collection.can_read || canManageCatalog
            ? knowledgeApi.getKnowledgeCollectionItems(collection.id)
            : Promise.resolve({ items: [] }),
          canManageCatalog
            ? knowledgeApi.getKnowledgeCollectionLinkCandidates(collection.id)
            : Promise.resolve({ candidates: [] }),
          canDelegate
            ? knowledgeApi.getKnowledgeCollectionPermissions(collection.id)
            : Promise.resolve({ permissions: [] }),
          canDelegate
            ? knowledgeApi.getKnowledgeCollectionDelegationSubjects(collection.id)
            : Promise.resolve({ teams: [], users: [] }),
        ]);
      setItems(itemData.items);
      setCandidates(candidateData.candidates);
      setPermissions(permissionData.permissions);
      setSubjects(subjectData);
    } catch (error) {
      setItems([]);
      setCandidates([]);
      setPermissions([]);
      setSubjects({ teams: [], users: [] });
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
      safeLabel:
        typeof selectedCollection.safe_metadata.safe_label === 'string'
          ? selectedCollection.safe_metadata.safe_label
          : '',
    });
    setAcknowledgePublic(false);
    loadCollectionDetail(selectedCollection, capabilities);
  }, [capabilities, loadCollectionDetail, selectedCollection]);

  const refreshSelected = async () => {
    await loadCollections();
    if (selectedCollection) {
      await loadCollectionDetail(selectedCollection, capabilities);
    }
  };

  const createCollection = async () => {
    if (!form.name.trim() || !form.safeLabel.trim()) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      const created = await knowledgeApi.createKnowledgeCollection({
        name: form.name.trim(),
        description: form.description.trim() || null,
        safe_metadata: {
          safe_label: form.safeLabel.trim(),
        },
      });
      setForm({ name: '', description: '', safeLabel: '' });
      await loadCollections();
      setSelectedId(created.id);
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const updateCollection = async () => {
    if (
      !selectedCollection ||
      !editForm.name.trim() ||
      !editForm.safeLabel.trim()
    ) {
      return;
    }
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.updateKnowledgeCollection(selectedCollection.id, {
        name: editForm.name.trim(),
        description: editForm.description.trim() || null,
        safe_metadata: {
          ...selectedCollection.safe_metadata,
          safe_label: editForm.safeLabel.trim(),
        },
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
        acknowledged_public_runtime_exposure:
          selectedCollection.visibility === 'public' && acknowledgePublic,
      });
      await loadCollectionDetail(
        selectedCollection,
        capabilities,
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
        selectedCollection.visibility === 'public' && acknowledgePublic,
      );
      await loadCollectionDetail(
        selectedCollection,
        capabilities,
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
      await knowledgeApi.grantKnowledgeCollectionPermissionBundle(
        selectedCollection.id,
        {
          ...grantForm,
          subject_id: grantForm.subject_id.trim(),
        },
      );
      setGrantForm({
        subject_type: 'team',
        subject_id: '',
        role_bundle: 'viewer',
      });
      await loadCollectionDetail(
        selectedCollection,
        capabilities,
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
        selectedCollection,
        capabilities,
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

  const grantDomainPermission = async () => {
    if (!domainGrantForm.subject_id) return;
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.grantKnowledgeDomainPermission(domainGrantForm);
      setDomainGrantForm({
        subject_type: 'team',
        subject_id: '',
        permission_action: 'catalog_manage',
      });
      await loadCollections();
    } catch (error) {
      setErrorMessage(errorText(error));
    } finally {
      setIsSaving(false);
    }
  };

  const revokeDomainPermission = async (
    subjectType: 'team' | 'user',
    subjectId: string,
    permissionAction: KnowledgeDomainAction,
  ) => {
    setIsSaving(true);
    setErrorMessage(null);
    try {
      await knowledgeApi.revokeKnowledgeDomainPermission({
        subject_type: subjectType,
        subject_id: subjectId,
        permission_action: permissionAction,
      });
      await loadCollections();
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

      {capabilities.can_manage_domain_permissions && (
        <DomainDelegationPanel
          form={domainGrantForm}
          isSaving={isSaving}
          permissions={domainPermissions}
          subjects={domainSubjects}
          onGrant={grantDomainPermission}
          onRevoke={revokeDomainPermission}
          setForm={setDomainGrantForm}
        />
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
            subjects={subjects}
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
