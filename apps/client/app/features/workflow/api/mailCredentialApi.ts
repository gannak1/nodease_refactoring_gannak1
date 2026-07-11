import { apiClient } from '@/lib/apiClient';

export interface MailCredentialOption {
  id: string;
  credential_name: string;
  provider: 'gmail' | 'naver' | 'daum' | 'outlook' | 'custom';
  email_preview: string;
  status: 'active' | 'revoked';
}

export const mailCredentialApi = {
  async listAvailable(): Promise<MailCredentialOption[]> {
    const response =
      await apiClient.get<MailCredentialOption[]>('/mail/credentials');
    return response.data;
  },
};
