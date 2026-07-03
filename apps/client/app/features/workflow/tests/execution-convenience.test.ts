import { describe, expect, it } from 'vitest';
import {
  formatCost,
  formatLatency,
  formatTokens,
  readCost,
  readTokenUsage,
  summarizeWorkflowExecution,
} from '../utils/testExecutionSummary';

describe('workflow test cases: 실행 편의성', () => {
  it('usage.total_tokens가 있으면 해당 토큰 수를 읽는다', () => {
    expect(readTokenUsage({ usage: { total_tokens: 123 } })).toBe(123);
  });

  it('prompt_tokens와 completion_tokens가 있으면 합산 토큰 수를 읽는다', () => {
    expect(
      readTokenUsage({
        usage: { prompt_tokens: 40, completion_tokens: 60 },
      }),
    ).toBe(100);
  });

  it('cost 또는 usage.total_cost가 있으면 비용을 읽는다', () => {
    expect(readCost({ cost: 0.0012 })).toBe(0.0012);
    expect(readCost({ usage: { total_cost: 0.0024 } })).toBe(0.0024);
  });

  it('토큰 또는 비용 정보가 없으면 표시값은 dash가 된다', () => {
    expect(readTokenUsage({ usage: {} })).toBeUndefined();
    expect(readCost({ usage: {} })).toBeUndefined();
    expect(formatTokens(undefined)).toBe('-');
    expect(formatCost(undefined)).toBe('-');
  });

  it('node_start와 node_finish 수신 시각 차이를 ms 또는 s 단위로 표시한다', () => {
    expect(formatLatency(530)).toBe('530ms');
    expect(formatLatency(5200)).toBe('5.2s');
  });

  it('전체 테스트 실행 완료 시 전체 시간, 비용, 토큰 사용량을 계산한다', () => {
    const summary = summarizeWorkflowExecution(
      [
        {
          nodeId: 'llm-1',
          status: 'success',
          latencyMs: 120,
          totalTokens: 100,
          cost: 0.001,
        },
        {
          nodeId: 'llm-2',
          status: 'success',
          latencyMs: 180,
          totalTokens: 250,
          cost: 0.002,
        },
      ],
      1000,
      1450,
    );

    expect(summary).toEqual({
      totalLatencyMs: 450,
      totalTokens: 350,
      totalCost: 0.003,
    });
  });

  it.todo(
    '기존 테스트 실행 스트리밍 API가 node_start/node_finish/workflow_finish 이벤트를 반환한다',
  );
  it.todo('권한 없는 사용자의 테스트 실행 요청은 403으로 거부된다');
  it.todo('scope 밖 workflow 테스트 실행 요청은 404로 처리된다');
  it.todo(
    '빌더가 워크플로우 테스트를 실행하면 테스트 실행 사이드바에 노드별 상태가 표시된다',
  );
  it.todo('캔버스에는 별도 테스트 실행 요약 패널이 표시되지 않는다');
  it.todo('can_execute=false인 사용자는 테스트 버튼을 실행할 수 없다');
  it.todo(
    '프론트에서 테스트 버튼이 disabled여도 API 직접 호출 권한 검증은 Gateway에서 유지된다',
  );
  it.todo(
    '노드 실행 중 스트리밍이 실패하면 전체 실패 상태와 식별 가능한 노드 실패 상태를 함께 표시한다',
  );
});
