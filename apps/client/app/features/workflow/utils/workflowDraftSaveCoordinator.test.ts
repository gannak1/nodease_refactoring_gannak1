import { afterEach, describe, expect, it } from 'vitest';

import {
  acquireWorkflowDraftSave,
  clearWorkflowDraftSaveCoordinatorForTests,
  getWorkflowDraftSaveOwner,
  startWorkflowExecutionFromPreflight,
  tryAcquireWorkflowDraftSave,
} from './workflowDraftSaveCoordinator';

describe('workflowDraftSaveCoordinator', () => {
  afterEach(() => {
    clearWorkflowDraftSaveCoordinatorForTests();
  });

  it('같은 workflow의 두 저장을 동시에 허용하지 않는다', () => {
    const releaseAgentBuilder = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'agent_builder',
    );

    expect(releaseAgentBuilder).not.toBeNull();
    expect(getWorkflowDraftSaveOwner('workflow-1')).toBe('agent_builder');
    expect(
      tryAcquireWorkflowDraftSave('workflow-1', 'test_preflight'),
    ).toBeNull();

    releaseAgentBuilder?.();

    const releaseTest = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'test_preflight',
    );
    expect(releaseTest).not.toBeNull();
    releaseTest?.();
  });

  it('대기 저장은 앞선 저장 해제 뒤에만 시작한다', async () => {
    const releaseTest = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'test_preflight',
    );
    let acquired = false;
    const waiting = acquireWorkflowDraftSave(
      'workflow-1',
      'agent_builder',
    ).then((release) => {
      acquired = true;
      return release;
    });

    await Promise.resolve();
    expect(acquired).toBe(false);

    releaseTest?.();
    const releaseAgentBuilder = await waiting;
    expect(acquired).toBe(true);
    expect(getWorkflowDraftSaveOwner('workflow-1')).toBe('agent_builder');
    releaseAgentBuilder();
  });

  it('다른 workflow의 저장은 서로 차단하지 않는다', () => {
    const releaseFirst = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'agent_builder',
    );
    const releaseSecond = tryAcquireWorkflowDraftSave(
      'workflow-2',
      'test_preflight',
    );

    expect(releaseFirst).not.toBeNull();
    expect(releaseSecond).not.toBeNull();
    releaseFirst?.();
    releaseSecond?.();
  });

  it('Agent Builder 저장이 대기하면 test stream을 시작하지 않고 owner를 넘긴다', async () => {
    const releaseTest = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'test_preflight',
    );
    const waitingAgentBuilder = acquireWorkflowDraftSave(
      'workflow-1',
      'agent_builder',
    );
    let started = false;

    const result = startWorkflowExecutionFromPreflight(
      'workflow-1',
      releaseTest!,
      () => {
        started = true;
        return Promise.resolve();
      },
    );

    expect(result.started).toBe(false);
    expect(started).toBe(false);
    const releaseAgentBuilder = await waitingAgentBuilder;
    expect(getWorkflowDraftSaveOwner('workflow-1')).toBe('agent_builder');
    releaseAgentBuilder();
  });

  it('대기 저장이 없으면 test stream을 시작한 뒤 preflight owner를 해제한다', () => {
    const releaseTest = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'test_preflight',
    );

    const result = startWorkflowExecutionFromPreflight(
      'workflow-1',
      releaseTest!,
      () => {
        expect(getWorkflowDraftSaveOwner('workflow-1')).toBe('test_preflight');
        return 'stream-started';
      },
    );

    expect(result).toEqual({ started: true, value: 'stream-started' });
    expect(getWorkflowDraftSaveOwner('workflow-1')).toBeNull();
  });

  it('version restore participates in the same workflow save queue', async () => {
    const releaseAgentBuilder = tryAcquireWorkflowDraftSave(
      'workflow-1',
      'agent_builder',
    );
    let acquired = false;
    const waitingRestore = acquireWorkflowDraftSave(
      'workflow-1',
      'version_restore',
    ).then((release) => {
      acquired = true;
      return release;
    });

    await Promise.resolve();
    expect(acquired).toBe(false);

    releaseAgentBuilder?.();
    const releaseRestore = await waitingRestore;
    expect(acquired).toBe(true);
    expect(getWorkflowDraftSaveOwner('workflow-1')).toBe('version_restore');
    releaseRestore();
  });
});
