import { apiClient } from '@/lib/apiClient';
import { DBConfig } from '../types/DB';

const api = apiClient;

const getHttpStatus = (error: unknown): number | undefined => {
  if (typeof error !== 'object' || error === null) return undefined;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : undefined;
};

const logConnectorApiFailure = (operation: string, error: unknown) => {
  console.warn('[connectorApi] request failed', {
    operation,
    status: getHttpStatus(error),
  });
};

const withStatus = (message: string, status?: number) =>
  status ? `${message} (HTTP ${status})` : message;

const SAFE_MESSAGE_BY_REASON_CODE: Record<string, string> = {
  'connector.connection_failed': 'DB 연결에 실패했습니다.',
  'connection_config.encrypt_failed': 'DB 연결 정보 암호화에 실패했습니다.',
};

const SAFE_BACKEND_MESSAGES = new Set([
  '데이터베이스 연결에 성공했습니다.',
  '데이터베이스 연결에 실패했습니다.',
  '연결 실패',
  '연결 정보가 안전하게 저장되었습니다.',
]);

const safeBackendMessage = (message: unknown, fallback: string): string => {
  if (typeof message !== 'string') return fallback;
  const trimmed = message.trim();
  return SAFE_BACKEND_MESSAGES.has(trimmed) ? trimmed : fallback;
};

const reasonCodeFromPayload = (payload: unknown): string | undefined => {
  if (typeof payload !== 'object' || payload === null) return undefined;
  const data = payload as {
    reason_code?: unknown;
    reasonCode?: unknown;
    detail?: unknown;
  };
  if (
    typeof data.reason_code === 'string' &&
    data.reason_code in SAFE_MESSAGE_BY_REASON_CODE
  )
    return data.reason_code;
  if (
    typeof data.reasonCode === 'string' &&
    data.reasonCode in SAFE_MESSAGE_BY_REASON_CODE
  )
    return data.reasonCode;
  if (typeof data.detail === 'object' && data.detail !== null) {
    const detail = data.detail as { reason_code?: unknown; reasonCode?: unknown };
    if (
      typeof detail.reason_code === 'string' &&
      detail.reason_code in SAFE_MESSAGE_BY_REASON_CODE
    )
      return detail.reason_code;
    if (
      typeof detail.reasonCode === 'string' &&
      detail.reasonCode in SAFE_MESSAGE_BY_REASON_CODE
    )
      return detail.reasonCode;
  }
  return undefined;
};

const responsePayload = (error: unknown): unknown => {
  if (typeof error !== 'object' || error === null) return undefined;
  return (error as { response?: { data?: unknown } }).response?.data;
};

const safeFailureMessage = (
  fallback: string,
  options: { status?: number; reasonCode?: string } = {},
) => {
  const { status, reasonCode } = options;
  return withStatus(
    (reasonCode && SAFE_MESSAGE_BY_REASON_CODE[reasonCode]) || fallback,
    status,
  );
};

type ConnectorCreationResult = {
  id: string;
  success: boolean;
  message: string;
  status?: number;
  reasonCode?: string;
};

type ConnectionTestResult = {
  success: boolean;
  message: string;
  status?: number;
  reasonCode?: string;
};

export const connectorApi = {
  /**
   * DB 연결 정보 저장 및 Connector 생성 요청
   *
   * @param config - 사용자가 입력한 DB 연결 정보
   * @returns 생성된 커넥터 정보
   */
  createConnector: async (
    config: DBConfig,
  ): Promise<ConnectorCreationResult> => {
    try {
      const payload = {
        connection_name: config.connectionName,
        type: config.type,
        host: config.host,
        port: config.port,
        database: config.database,
        username: config.username,
        password: config.password,
        ssh: config.ssh?.enabled
          ? {
              enabled: true,
              host: config.ssh.host,
              port: config.ssh.port,
              username: config.ssh.username,
              auth_type: config.ssh.authType === 'key' ? 'key' : 'password',
              password: config.ssh.password,
              private_key: config.ssh.privateKey,
            }
          : null,
      };

      const response = await api.post('/connectors', payload);
      const id = typeof response.data?.id === 'string' ? response.data.id : '';
      const success = response.data?.success === true && Boolean(id);
      const reasonCode = reasonCodeFromPayload(response.data);
      if (!success) {
        return {
          id: '',
          success: false,
          message: safeFailureMessage('DB 연결 정보 저장에 실패했습니다.', {
            reasonCode,
          }),
          ...(reasonCode ? { reasonCode } : {}),
        };
      }
      return {
        id,
        success: true,
        message: safeBackendMessage(
          response.data?.message,
          'DB 연결 정보가 저장되었습니다.',
        ),
      };
    } catch (error) {
      const status = getHttpStatus(error);
      const reasonCode = reasonCodeFromPayload(responsePayload(error));
      logConnectorApiFailure('createConnector', error);
      return {
        id: '',
        success: false,
        message: safeFailureMessage('DB 연결 정보 저장에 실패했습니다.', {
          status,
          reasonCode,
        }),
        ...(status ? { status } : {}),
        ...(reasonCode ? { reasonCode } : {}),
      };
    }
  },

  /**
   * DB 연결 테스트
   * @param config - DB 연결 정보
   * @returns 성공 여부 및 메시지
   */
  testConnection: async (
    config: DBConfig,
  ): Promise<ConnectionTestResult> => {
    try {
      const payload = {
        connection_name: config.connectionName,
        type: config.type,
        host: config.host,
        port: config.port,
        database: config.database,
        username: config.username,
        password: config.password,
        ssh: config.ssh?.enabled
          ? {
              enabled: true,
              host: config.ssh.host,
              port: config.ssh.port,
              username: config.ssh.username,
              auth_type: config.ssh.authType === 'key' ? 'key' : 'password',
              password: config.ssh.password,
              private_key: config.ssh.privateKey,
            }
          : null,
      };

      const response = await api.post('/connectors/test', payload);
      const success = response.data?.success === true;
      const reasonCode = reasonCodeFromPayload(response.data);
      return {
        success,
        message: success
          ? safeBackendMessage(response.data?.message, 'DB 연결 테스트 성공')
          : safeFailureMessage('DB 연결에 실패했습니다.', { reasonCode }),
        ...(reasonCode ? { reasonCode } : {}),
      };
    } catch (error) {
      const status = getHttpStatus(error);
      const reasonCode = reasonCodeFromPayload(responsePayload(error));
      logConnectorApiFailure('testConnection', error);
      return {
        success: false,
        message: safeFailureMessage('DB 연결 테스트 중 오류가 발생했습니다.', {
          status,
          reasonCode,
        }),
        ...(status ? { status } : {}),
        ...(reasonCode ? { reasonCode } : {}),
      };
    }
  },

  getSchema: async (connectionId: string): Promise<any> => {
    const response = await api.get(`/connectors/${connectionId}/schema`);
    return response.data;
  },

  /**
   * DB 연결 상세 정보 조회 (비밀번호 제외)
   *
   * @param connectedId - 연결 ID
   * @returns 저장된 DB연결 정보
   */
  getConnectionDetails: async (connectionId: string): Promise<any> => {
    const response = await api.get(`/connectors/${connectionId}`);
    return response.data;
  },
};
