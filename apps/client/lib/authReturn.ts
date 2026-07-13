const AUTH_RETURN_ORIGIN = 'https://nodease.local';

export const DEFAULT_AUTH_RETURN_PATH = '/dashboard';

export const resolveSafeAuthReturnPath = (
  returnPath: string | null | undefined,
): string => {
  if (!returnPath || !returnPath.startsWith('/')) {
    return DEFAULT_AUTH_RETURN_PATH;
  }

  try {
    const resolved = new URL(returnPath, AUTH_RETURN_ORIGIN);
    if (resolved.origin !== AUTH_RETURN_ORIGIN) {
      return DEFAULT_AUTH_RETURN_PATH;
    }

    const normalized = `${resolved.pathname}${resolved.search}${resolved.hash}`;
    const verified = new URL(normalized, AUTH_RETURN_ORIGIN);
    if (verified.origin !== AUTH_RETURN_ORIGIN) {
      return DEFAULT_AUTH_RETURN_PATH;
    }
    return `${verified.pathname}${verified.search}${verified.hash}`;
  } catch {
    return DEFAULT_AUTH_RETURN_PATH;
  }
};

export const getCurrentAuthReturnPath = (): string => {
  if (typeof window === 'undefined') {
    return DEFAULT_AUTH_RETURN_PATH;
  }

  return resolveSafeAuthReturnPath(
    `${window.location.pathname}${window.location.search}${window.location.hash}`,
  );
};

export const buildLoginRedirectPath = (
  returnPath: string | null | undefined,
): string =>
  `/auth/login?next=${encodeURIComponent(resolveSafeAuthReturnPath(returnPath))}`;
