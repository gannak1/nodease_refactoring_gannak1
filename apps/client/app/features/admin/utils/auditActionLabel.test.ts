import { describe, expect, it } from 'vitest';
import { auditActionLabel } from './auditActionLabel';

describe('auditActionLabel', () => {
  it('canonical action의 사용자 친화 라벨을 반환한다', () => {
    expect(auditActionLabel('permission_request.approved')).toBe(
      '권한 신청 승인',
    );
    expect(auditActionLabel('workflow.deploy')).toBe('Workflow 배포');
    expect(auditActionLabel('permission.denied')).toBe('권한 차단');
  });

  it('알려진 동사 suffix로 라벨을 파생한다', () => {
    expect(auditActionLabel('team_workflow_permission.created')).toBe(
      'team_workflow_permission 생성',
    );
    expect(auditActionLabel('user_llm_permission.deleted')).toBe(
      'user_llm_permission 삭제',
    );
  });

  it('파생할 수 없는 action은 null을 반환한다', () => {
    expect(auditActionLabel('unknown.verb_without_mapping')).toBeNull();
    expect(auditActionLabel('noseparator')).toBeNull();
  });
});
