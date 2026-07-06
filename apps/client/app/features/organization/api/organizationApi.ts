import { apiClient, publicApiClient } from '@/lib/apiClient';
import { activeOrganizationHeaders } from '@/lib/activeOrganization';

import type {
  MembershipState,
  OrganizationMember,
  OrganizationMemberInviteRequest,
  OrganizationMemberRemoveResponse,
  OrganizationMemberUpdateRequest,
  OrganizationResponse,
  OrganizationSummary,
  PermissionRequestCreateRequest,
  PermissionRequestResponse,
} from '../types/Organization';

export const organizationApi = {
  listOrganizations: async (): Promise<OrganizationResponse[]> => {
    const response = await apiClient.get('/organizations');
    return response.data;
  },

  listMemberships: async (): Promise<OrganizationSummary[]> => {
    const response = await apiClient.get('/organizations/memberships');
    return response.data;
  },

  getCurrentOrganization: async (): Promise<OrganizationResponse> => {
    const response = await apiClient.get('/organizations/current');
    return response.data;
  },

  listMembers: async (
    organizationId: string,
    state?: MembershipState,
  ): Promise<OrganizationMember[]> => {
    const response = await apiClient.get(
      `/organizations/${organizationId}/members`,
      {
        headers: activeOrganizationHeaders(organizationId),
        params: state ? { state } : undefined,
      },
    );
    return response.data;
  },

  inviteMember: async (
    organizationId: string,
    payload: OrganizationMemberInviteRequest,
  ): Promise<OrganizationMember> => {
    const response = await apiClient.post(
      `/organizations/${organizationId}/members/invitations`,
      payload,
      { headers: activeOrganizationHeaders(organizationId) },
    );
    return response.data;
  },

  acceptInvitation: async (
    organizationId: string,
  ): Promise<OrganizationMember> => {
    const response = await publicApiClient.post(
      `/organizations/${organizationId}/members/me/accept`,
    );
    return response.data;
  },

  updateMember: async (
    organizationId: string,
    userId: string,
    payload: OrganizationMemberUpdateRequest,
  ): Promise<OrganizationMember> => {
    const response = await apiClient.patch(
      `/organizations/${organizationId}/members/${userId}`,
      payload,
      { headers: activeOrganizationHeaders(organizationId) },
    );
    return response.data;
  },

  removeMember: async (
    organizationId: string,
    userId: string,
  ): Promise<OrganizationMemberRemoveResponse> => {
    const response = await apiClient.delete(
      `/organizations/${organizationId}/members/${userId}`,
      { headers: activeOrganizationHeaders(organizationId) },
    );
    return response.data;
  },

  submitPermissionRequest: async (
    payload: PermissionRequestCreateRequest,
  ): Promise<PermissionRequestResponse> => {
    const response = await apiClient.post('/permission-requests', {
      requested_permission: 'app.create',
      ...payload,
    });
    return response.data;
  },
};
