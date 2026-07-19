import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMemoryMode } from './MemoryModeControls';

const mockPush = vi.fn();

vi.mock('next/navigation', () => ({
  usePathname: () => '/modules/workflow-1',
  useRouter: () => ({ push: mockPush }),
}));

describe('useMemoryMode credential status', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('등록된 credential이 있으면 사용 가능한 상태로 표시한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [{ id: 'credential-1' }],
      }),
    );

    const { result } = renderHook(() => useMemoryMode());

    await waitFor(() => {
      expect(result.current.providerKeyStatus).toBe('available');
    });
    expect(result.current.hasProviderKey).toBe(true);
  });

  it('정상 응답이 빈 목록이면 credential이 없는 상태로 표시한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [],
      }),
    );

    const { result } = renderHook(() => useMemoryMode());

    await waitFor(() => {
      expect(result.current.providerKeyStatus).toBe('missing');
    });
    expect(result.current.hasProviderKey).toBe(false);
  });

  it('credential 조회 실패를 credential 없음으로 오판하지 않는다', async () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    const toaster = {
      error: vi.fn(),
      info: vi.fn(),
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
      }),
    );

    const { result } = renderHook(() =>
      useMemoryMode(undefined, toaster as never),
    );

    await waitFor(() => {
      expect(result.current.providerKeyStatus).toBe('unavailable');
    });
    expect(result.current.hasProviderKey).toBeNull();
    expect(consoleError).not.toHaveBeenCalled();

    act(() => result.current.toggleMemoryMode());
    expect(toaster.error).toHaveBeenCalledWith(
      '프로바이더 키 상태를 확인하지 못했습니다. 로그인 상태와 서버 연결을 확인해 주세요.',
      { duration: 3000 },
    );
  });
});
