import { AxiosHeaders, type AxiosInstance } from 'axios';

const ACTIVE_ORGANIZATION_ID_STORAGE_KEY = 'moduly_active_organization_id';

type OrganizationLike = {
  id: string;
};

export const getStoredActiveOrganizationId = () => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ACTIVE_ORGANIZATION_ID_STORAGE_KEY);
};

export const setActiveOrganizationId = (organizationId?: string | null) => {
  if (typeof window === 'undefined') return;
  if (!organizationId) {
    window.localStorage.removeItem(ACTIVE_ORGANIZATION_ID_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(
    ACTIVE_ORGANIZATION_ID_STORAGE_KEY,
    organizationId,
  );
};

export const resolveActiveOrganizationId = <T extends OrganizationLike>(
  organizations: T[],
) => {
  const storedOrganizationId = getStoredActiveOrganizationId();
  if (
    storedOrganizationId &&
    organizations.some((organization) => organization.id === storedOrganizationId)
  ) {
    return storedOrganizationId;
  }

  if (organizations.length === 1) {
    const [onlyOrganization] = organizations;
    setActiveOrganizationId(onlyOrganization.id);
    return onlyOrganization.id;
  }

  return null;
};

export const activeOrganizationHeaders = (
  organizationId?: string | null,
): Record<string, string> =>
  organizationId ? { 'X-Organization-Id': organizationId } : {};

export const attachActiveOrganizationHeader = (api: AxiosInstance) => {
  api.interceptors.request.use((config) => {
    const organizationId = getStoredActiveOrganizationId();
    if (organizationId) {
      config.headers = AxiosHeaders.from(config.headers);
      config.headers.set('X-Organization-Id', organizationId);
    }
    return config;
  });
};
