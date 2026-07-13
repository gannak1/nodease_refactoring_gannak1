import { describe, expect, it } from 'vitest';

import {
  buildLoginRedirectPath,
  resolveSafeAuthReturnPath,
} from './authReturn';

describe('auth return path', () => {
  it('preserves an internal path with its query string', () => {
    const returnPath =
      '/modules/workflow-1/run?deploymentId=deployment-1';

    expect(resolveSafeAuthReturnPath(returnPath)).toBe(returnPath);
    expect(buildLoginRedirectPath(returnPath)).toBe(
      '/auth/login?next=%2Fmodules%2Fworkflow-1%2Frun%3FdeploymentId%3Ddeployment-1',
    );
  });

  it.each([
    undefined,
    '',
    'https://evil.example/steal',
    '//evil.example/steal',
    '/\\evil.example/steal',
    '/%2e%2e//evil.example/steal',
  ])('falls back to the dashboard for unsafe return path %s', (returnPath) => {
    expect(resolveSafeAuthReturnPath(returnPath)).toBe('/dashboard');
  });
});
