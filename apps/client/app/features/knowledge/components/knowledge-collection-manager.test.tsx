import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import KnowledgeCollectionManager from './knowledge-collection-manager';

const knowledgeApiMock = vi.hoisted(() => ({
  getKnowledgeCollectionsResponse: vi.fn(),
  getKnowledgeDomainCapabilities: vi.fn(),
  getKnowledgeDomainPermissions: vi.fn(),
  getKnowledgeDomainDelegationSubjects: vi.fn(),
  getKnowledgeCollectionItems: vi.fn(),
  getKnowledgeCollectionLinkCandidates: vi.fn(),
  getKnowledgeCollectionPermissions: vi.fn(),
  getKnowledgeCollectionDelegationSubjects: vi.fn(),
  createKnowledgeCollection: vi.fn(),
  updateKnowledgeCollection: vi.fn(),
  archiveKnowledgeCollection: vi.fn(),
  linkKnowledgeCollectionItem: vi.fn(),
  unlinkKnowledgeCollectionItem: vi.fn(),
  grantKnowledgeCollectionPermission: vi.fn(),
  grantKnowledgeCollectionPermissionBundle: vi.fn(),
  grantKnowledgeDomainPermission: vi.fn(),
  revokeKnowledgeDomainPermission: vi.fn(),
  revokeKnowledgeCollectionPermission: vi.fn(),
  updateKnowledgeCollectionVisibility: vi.fn(),
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: knowledgeApiMock,
}));

describe('KnowledgeCollectionManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps read-only item view available without calling manage-only APIs', async () => {
    knowledgeApiMock.getKnowledgeDomainCapabilities.mockResolvedValueOnce({
      actions: [],
      can_manage_domain_permissions: false,
      can_create_collection: false,
      can_delegate_permissions: false,
      can_manage_lifecycle: false,
      can_manage_sync: false,
      can_change_public_visibility: false,
    });
    knowledgeApiMock.getKnowledgeCollectionsResponse.mockResolvedValueOnce({
      collections: [
        {
          id: 'collection-1',
          organization_id: 'org-1',
          name: 'HR',
          description: '인사 문서',
          is_system_managed: false,
          sync_state: 'manual',
          lifecycle_state: 'active',
          visibility: 'private',
          linked_kb_count_bucket: '1',
          active_kb_count_bucket: '1',
          can_read: true,
          can_route: false,
          can_manage: false,
          can_sync: false,
          safe_metadata: {},
          created_at: '2026-07-07T00:00:00Z',
          updated_at: '2026-07-07T00:00:00Z',
        },
      ],
      can_create_collection: false,
      can_change_public_visibility: false,
    });
    knowledgeApiMock.getKnowledgeCollectionItems.mockResolvedValueOnce({
      items: [
        {
          item_id: 'item-1',
          knowledge_base_id: 'kb-1',
          safe_label: '휴가 정책',
          lifecycle_state: 'active',
          sync_state: 'manual',
          rank: 0,
          can_manage_kb: true,
          can_use_kb: true,
        },
      ],
    });

    render(<KnowledgeCollectionManager />);

    expect(await screen.findByText('휴가 정책')).toBeInTheDocument();
    expect(screen.queryByText('Collection 생성')).not.toBeInTheDocument();
    expect(
      screen.getByText('공개 상태 전환은 organization manager만 수행할 수 있습니다.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        '권한 관리는 collection.manage 또는 Knowledge permission_delegate가 필요합니다.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('부여')).not.toBeInTheDocument();
    expect(screen.getByLabelText('KB 연결 해제')).toBeDisabled();
    await waitFor(() => {
      expect(knowledgeApiMock.getKnowledgeCollectionLinkCandidates).not.toHaveBeenCalled();
      expect(knowledgeApiMock.getKnowledgeCollectionPermissions).not.toHaveBeenCalled();
      expect(
        knowledgeApiMock.getKnowledgeCollectionDelegationSubjects,
      ).not.toHaveBeenCalled();
    });
  });

  it('uses delegated catalog and permission capabilities with Team-first bundles', async () => {
    knowledgeApiMock.getKnowledgeDomainCapabilities.mockResolvedValueOnce({
      actions: ['catalog_manage', 'permission_delegate', 'lifecycle_manage'],
      can_manage_domain_permissions: false,
      can_create_collection: true,
      can_delegate_permissions: true,
      can_manage_lifecycle: true,
      can_manage_sync: false,
      can_change_public_visibility: false,
    });
    knowledgeApiMock.getKnowledgeCollectionsResponse.mockResolvedValueOnce({
      collections: [
        {
          id: 'collection-1',
          organization_id: 'org-1',
          name: 'HR',
          description: '인사 문서',
          is_system_managed: false,
          sync_state: 'manual',
          lifecycle_state: 'active',
          visibility: 'private',
          linked_kb_count_bucket: '0',
          active_kb_count_bucket: '0',
          can_read: false,
          can_route: false,
          can_manage: false,
          can_sync: false,
          safe_metadata: {},
          created_at: '2026-07-07T00:00:00Z',
          updated_at: '2026-07-07T00:00:00Z',
        },
      ],
      can_create_collection: true,
      can_change_public_visibility: false,
    });
    knowledgeApiMock.getKnowledgeCollectionItems.mockResolvedValue({ items: [] });
    knowledgeApiMock.getKnowledgeCollectionLinkCandidates.mockResolvedValue({
      candidates: [],
    });
    knowledgeApiMock.getKnowledgeCollectionPermissions.mockResolvedValue({
      permissions: [],
    });
    knowledgeApiMock.getKnowledgeCollectionDelegationSubjects.mockResolvedValue({
      teams: [
        {
          subject_type: 'team',
          subject_id: 'team-1',
          subject_safe_label: 'Knowledge 전담 Team',
        },
      ],
      users: [],
    });
    knowledgeApiMock.grantKnowledgeCollectionPermissionBundle.mockResolvedValueOnce({
      permissions: [],
    });

    render(<KnowledgeCollectionManager />);

    expect(await screen.findByText('Knowledge 전담 Team')).toBeInTheDocument();
    expect(screen.getByText('Collection 생성')).toBeInTheDocument();
    const targetSelect = screen
      .getAllByRole('combobox')
      .find((element) => element.querySelector('option[value="team-1"]'));
    expect(targetSelect).toBeDefined();
    fireEvent.change(targetSelect!, { target: { value: 'team-1' } });
    fireEvent.click(screen.getByRole('button', { name: '부여' }));

    await waitFor(() =>
      expect(
        knowledgeApiMock.grantKnowledgeCollectionPermissionBundle,
      ).toHaveBeenCalledWith('collection-1', {
        subject_type: 'team',
        subject_id: 'team-1',
        role_bundle: 'viewer',
      }),
    );
  });
});
