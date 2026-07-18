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

export const externalActionCredentialApi = {
  async listAvailable(): Promise<ExternalActionCredentialOption[]> {
    const response = await apiClient.get<ExternalActionCredentialOption[]>(
      '/external-action-credentials/credentials',
    );
    return response.data;
  },
};
