import { apiClient } from '@/lib/apiClient';

export type ExternalActionCredentialProvider =
  | 'github'
  | 'slack_api'
  | 'slack_webhook';

export interface ExternalActionCredentialOption {
  id: string;
  credential_name: string;
  provider: ExternalActionCredentialProvider;
  revision: number;
  status: 'active' | 'revoked';
}

export interface ExternalActionCredentialResponse extends ExternalActionCredentialOption {
  organization_id: string;
  created_at: string;
  updated_at: string;
  revoked_at: string | null;
}

export interface ExternalActionCredentialCreateRequest {
  credential_name: string;
  provider: ExternalActionCredentialProvider;
  secret: string;
}

export interface ExternalActionCredentialUpdateRequest {
  expected_revision: number;
  credential_name?: string;
  secret?: string;
}

export const externalActionCredentialApi = {
  async listAvailable(): Promise<ExternalActionCredentialOption[]> {
    const response = await apiClient.get<ExternalActionCredentialOption[]>(
      '/external-action-credentials/credentials',
    );
    return response.data;
  },

  async listManageable(): Promise<ExternalActionCredentialOption[]> {
    const response = await apiClient.get<ExternalActionCredentialOption[]>(
      '/external-action-credentials/credentials/management-options',
    );
    return response.data;
  },

  async create(
    payload: ExternalActionCredentialCreateRequest,
  ): Promise<ExternalActionCredentialResponse> {
    const response = await apiClient.post<ExternalActionCredentialResponse>(
      '/external-action-credentials/credentials',
      payload,
    );
    return response.data;
  },

  async update(
    credentialId: string,
    payload: ExternalActionCredentialUpdateRequest,
  ): Promise<ExternalActionCredentialResponse> {
    const response = await apiClient.patch<ExternalActionCredentialResponse>(
      `/external-action-credentials/credentials/${credentialId}`,
      payload,
    );
    return response.data;
  },

  async revoke(
    credentialId: string,
    expectedRevision: number,
  ): Promise<ExternalActionCredentialResponse> {
    const response = await apiClient.post<ExternalActionCredentialResponse>(
      `/external-action-credentials/credentials/${credentialId}/revoke`,
      { expected_revision: expectedRevision },
    );
    return response.data;
  },
};
