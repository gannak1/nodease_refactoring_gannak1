import axios from 'axios';
import { attachActiveOrganizationHeader } from './activeOrganization';
import {
  buildLoginRedirectPath,
  getCurrentAuthReturnPath,
} from './authReturn';

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL
  ? `${process.env.NEXT_PUBLIC_API_URL}/api/v1`
  : '/api/v1';

const createApiClient = () =>
  axios.create({
    baseURL: apiBaseUrl,
    withCredentials: true,
  });

const attachAuthRedirectInterceptor = (
  client: ReturnType<typeof createApiClient>,
) => {
  client.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        // 로그인/회원가입 페이지에서는 리다이렉트하지 않음 (에러 메시지를 보여주기 위해)
        if (
          typeof window !== 'undefined' &&
          !window.location.pathname.startsWith('/auth') &&
          window.location.pathname !== '/'
        ) {
          window.location.href = buildLoginRedirectPath(
            getCurrentAuthReturnPath(),
          );
        }
      }
      return Promise.reject(error);
    },
  );
};

export const publicApiClient = createApiClient();

export const apiClient = createApiClient();

attachActiveOrganizationHeader(apiClient);

attachAuthRedirectInterceptor(publicApiClient);
attachAuthRedirectInterceptor(apiClient);
