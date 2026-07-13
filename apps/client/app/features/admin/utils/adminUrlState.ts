export type AdminTab =
  | 'members'
  | 'teams'
  | 'permissions'
  | 'permission-requests'
  | 'usage'
  | 'credentials'
  | 'knowledge'
  | 'security-alerts'
  | 'audit'
  | 'organization';

const ADMIN_TABS = new Set<AdminTab>([
  'members',
  'teams',
  'permissions',
  'permission-requests',
  'usage',
  'credentials',
  'knowledge',
  'security-alerts',
  'audit',
  'organization',
]);

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type AdminUrlState = {
  tab: AdminTab;
  alertId: string | null;
  notice: string | null;
  normalizedQuery: URLSearchParams | null;
};

export const parseAdminUrlState = (
  searchParams: URLSearchParams,
): AdminUrlState => {
  const rawTab = searchParams.get('tab');
  const tab = rawTab && ADMIN_TABS.has(rawTab as AdminTab)
    ? (rawTab as AdminTab)
    : 'members';
  const normalizedQuery = new URLSearchParams(searchParams);
  let needsNormalization = false;

  if (rawTab && tab === 'members' && rawTab !== 'members') {
    normalizedQuery.set('tab', 'members');
    normalizedQuery.delete('alertId');
    needsNormalization = true;
  }

  const rawAlertId = normalizedQuery.get('alertId');
  if (tab !== 'security-alerts' && rawAlertId) {
    normalizedQuery.delete('alertId');
    needsNormalization = true;
  }

  if (tab === 'security-alerts' && rawAlertId && !UUID_PATTERN.test(rawAlertId)) {
    normalizedQuery.delete('alertId');
    return {
      tab,
      alertId: null,
      notice: '알림을 찾을 수 없습니다.',
      normalizedQuery,
    };
  }

  return {
    tab,
    alertId: tab === 'security-alerts' ? rawAlertId : null,
    notice: null,
    normalizedQuery: needsNormalization ? normalizedQuery : null,
  };
};

export const buildAdminTabUrl = (
  pathname: string,
  searchParams: URLSearchParams,
  tab: AdminTab,
) => {
  const nextSearchParams = new URLSearchParams(searchParams);
  nextSearchParams.set('tab', tab);
  if (tab !== 'security-alerts') nextSearchParams.delete('alertId');
  return `${pathname}?${nextSearchParams.toString()}`;
};

export const isAdminTabVisible = (tab: AdminTab, isManager: boolean) =>
  tab !== 'security-alerts' || isManager;
