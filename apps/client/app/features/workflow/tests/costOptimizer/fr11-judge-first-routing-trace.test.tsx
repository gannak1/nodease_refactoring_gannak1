import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ModelRoutingDecisionDetails } from '../../components/modelRouting/ModelRoutingDecisionDetails';

afterEach(() => {
  cleanup();
});

describe('FR-011 Judge-first model routing trace', () => {
  it('Judge가 고른 모델과 점진 학습 상태를 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        traceMetadata={{
          llm: {
            strategy_id: 'judge_bootstrap_incremental_v1',
            selected_model: 'gpt-5-mini',
            fallback_model: 'gpt-4.1',
            decision_source: 'runtime_judge',
            reason_code: 'judge_bootstrap_required',
            policy_version: 'judge-bootstrap-v1',
            judge_called: true,
            learning_status: 'pending_contract',
            judge: {
              model: 'gpt-4.1-mini',
              confidence: 0.84,
              reason_short: '근거 종합 필요',
              candidate_model_count: 2,
              reason_code: 'structured_reasoning_required',
              cost: 0.00013,
            },
            runtime_context: {
              input_length_bucket: 'long',
              output_format: 'json',
              schema_required: true,
              knowledge_enabled: true,
              has_file_input: false,
            },
            decision_factors: {
              learning_mode: 'judge_first',
              judged_request_count: 7,
              local_confidence_threshold: 0.78,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('Judge-first + 점진적 로컬 학습')).toBeVisible();
    expect(screen.getByText('이번 Judge 판단')).toBeVisible();
    expect(screen.getByText(/Judge 모델: gpt-4.1-mini/)).toBeVisible();
    expect(screen.getByText(/판단 확신도 84.0%/)).toBeVisible();
    expect(screen.getByText('사유: 근거 종합 필요')).toBeVisible();
    expect(screen.getByText('검토 후보 모델 2개')).toBeVisible();
    expect(screen.getByText(/Judge 비용 \$0.000130/)).toBeVisible();
    expect(
      screen.getByText(
        (_, element) =>
          element?.textContent === '학습 방식: Judge 학습 중 · 선택 기준 78.0%',
      ),
    ).toBeVisible();
    expect(screen.getByText('JSON 스키마 필요')).toBeVisible();
    expect(screen.getByText('지식 베이스 사용')).toBeVisible();
    expect(
      screen.getByText('실행 결과 계약을 확인한 뒤 학습에 반영합니다.'),
    ).toBeVisible();
  });

  it('계약 실패로 제외된 Judge 선택은 학습에 쓰지 않았다고 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5-mini',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-5-mini',
              decision_source: 'runtime_judge',
              reason_code: 'multi_constraint',
              learning_status: 'rejected',
              learning_outcome_reason: 'schema_failed',
            },
          },
        }}
      />,
    );

    expect(
      screen.getByText('스키마 또는 후속 단계 조건을 통과하지 못해 학습에서 제외되었습니다.'),
    ).toBeVisible();
  });

  it('로컬 라우터가 충분히 확신하면 Judge를 호출하지 않은 근거를 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1-mini',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-4.1-mini',
              fallback_model: 'gpt-4.1',
              decision_source: 'local_router',
              reason_code: 'local_router_confident',
              policy_version: 'judge-bootstrap-v4',
              judge_called: false,
              decision_factors: {
                learning_mode: 'local_first',
                judged_request_count: 31,
                local_confidence: 0.86,
                local_confidence_threshold: 0.78,
              },
            },
          },
        }}
      />,
    );

    expect(
      screen.getByText('누적된 Judge 선택을 학습한 로컬 라우터가 먼저 선택했습니다.'),
    ).toBeVisible();
    expect(screen.getByText(/학습 방식: 로컬 라우터 우선/)).toBeVisible();
    expect(screen.getByText(/로컬 확신도 86.0%/)).toBeVisible();
    expect(screen.getByText(/선택 기준 78.0%/)).toBeVisible();
    expect(screen.getByText('실행 중 Judge 호출 안 함')).toBeVisible();
  });

  it('실제 fallback이 발생하면 최초 모델과 대체 모델을 구분한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5.6-terra',
          metadata: {
            fallback_used: true,
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-5.6-luna',
              fallback_model: 'gpt-5.6-terra',
              fallback_used: true,
              fallback_from_model: 'gpt-5.6-luna',
              fallback_reason_code: 'provider_call_failed',
              decision_source: 'runtime_judge',
              reason_code: 'judge_bootstrap_required',
            },
          },
        }}
      />,
    );

    expect(screen.getByText('실제 대체 실행')).toBeVisible();
    expect(screen.getByText('최초 선택: gpt-5.6-luna')).toBeVisible();
    expect(screen.getByText('사유: Provider 호출 실패')).toBeVisible();
    expect(screen.getByText('실제 사용: gpt-5.6-terra')).toBeVisible();
  });

  it('배포 정책 테스트는 실제 Judge 실행이나 학습으로 오인되지 않게 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-4.1',
              decision_source: 'test_policy_preview',
              reason_code: 'judge_bootstrap_required',
              policy_source: 'active_deployment',
              included_in_policy_learning: false,
              judge_called: false,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('배포 정책 기준 테스트')).toBeVisible();
    expect(
      screen.getByText(
        '활성 배포 정책을 테스트에만 적용했습니다. 이 결과는 로컬 라우터 학습에 포함되지 않습니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('실행 중 Judge 호출 안 함')).toBeVisible();
    expect(screen.queryByText('이번 Judge 판단')).not.toBeInTheDocument();
  });
});
