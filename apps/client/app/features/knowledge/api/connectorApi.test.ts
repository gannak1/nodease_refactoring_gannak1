import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { connectorApi } from './connectorApi';
import { apiClient } from '@/lib/apiClient';
import type { DBConfig } from '../types/DB';

const dbConfig: DBConfig = {
  connectionName: 'demo-db',
  type: 'postgres',
  host: 'db.internal',
  port: 5432,
  database: 'demo',
  username: 'demo-user',
  password: 'placeholder-password',
  ssh: {
    enabled: true,
    host: 'bastion.internal',
    port: 22,
    username: 'ssh-user',
    authType: 'key',
    password: 'placeholder-ssh-password',
    privateKey: 'placeholder-private-key',
  },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('connectorApi safe failure handling', () => {
  it('normalizes successful connector creation responses to safe fields', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        id: 'connection-1',
        success: true,
        message: 'raw-backend-success-message-should-not-be-shown',
        host: 'raw-host-should-not-be-returned',
      },
    });

    const result = await connectorApi.createConnector(dbConfig);

    expect(result).toEqual({
      id: 'connection-1',
      success: true,
      message: 'DB 연결 정보가 저장되었습니다.',
    });
    expect(result).not.toHaveProperty('host');
  });

  it('does not log raw createConnector errors or return raw response details', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 500,
        data: { detail: 'raw-response-payload-should-not-be-logged' },
      },
      config: {
        data: 'request-config-should-not-be-logged',
      },
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    const result = await connectorApi.createConnector(dbConfig);

    expect(result).toEqual({
      id: '',
      success: false,
      message: 'DB 연결 정보 저장에 실패했습니다. (HTTP 500)',
      status: 500,
    });
    expect(warnSpy).toHaveBeenCalledWith('[connectorApi] request failed', {
      operation: 'createConnector',
      status: 500,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });

  it('maps safe connector failure reason codes without exposing raw details', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 400,
        data: {
          detail: {
            reason_code: 'connector.connection_failed',
            diagnostic: 'raw-diagnostic-should-not-be-logged',
          },
        },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    const result = await connectorApi.createConnector(dbConfig);

    expect(result).toEqual({
      id: '',
      success: false,
      message: 'DB 연결에 실패했습니다. (HTTP 400)',
      status: 400,
      reasonCode: 'connector.connection_failed',
    });
    expect(warnSpy).toHaveBeenCalledWith('[connectorApi] request failed', {
      operation: 'createConnector',
      status: 400,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });

  it('drops unknown connector reason codes from client results', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 400,
        data: {
          detail: {
            reason_code: 'raw.internal.debug_code',
            diagnostic: 'raw-diagnostic-should-not-be-logged',
          },
        },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    const result = await connectorApi.createConnector(dbConfig);

    expect(result).toEqual({
      id: '',
      success: false,
      message: 'DB 연결 정보 저장에 실패했습니다. (HTTP 400)',
      status: 400,
    });
    expect(result).not.toHaveProperty('reasonCode');
    expect(warnSpy).toHaveBeenCalledWith('[connectorApi] request failed', {
      operation: 'createConnector',
      status: 400,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });

  it('does not expose backend messages from failed connection tests', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        success: false,
        message: 'raw-response-payload-should-not-be-shown',
      },
    });

    const result = await connectorApi.testConnection(dbConfig);

    expect(result).toEqual({
      success: false,
      message: 'DB 연결에 실패했습니다.',
    });
  });

  it('normalizes successful connection test responses to a safe message', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        success: true,
        message: 'raw-backend-success-message-should-not-be-shown',
      },
    });

    const result = await connectorApi.testConnection(dbConfig);

    expect(result).toEqual({
      success: true,
      message: 'DB 연결 테스트 성공',
    });
  });

  it('does not log raw testConnection errors or return raw response details', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 403,
        data: { message: 'raw-response-payload-should-not-be-logged' },
      },
      config: {
        data: 'request-config-should-not-be-logged',
      },
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    const result = await connectorApi.testConnection(dbConfig);

    expect(result).toEqual({
      success: false,
      message: 'DB 연결 테스트 중 오류가 발생했습니다. (HTTP 403)',
      status: 403,
    });
    expect(warnSpy).toHaveBeenCalledWith('[connectorApi] request failed', {
      operation: 'testConnection',
      status: 403,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });
});
