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

    expect(screen.getByText('모델 선택 결과')).toBeVisible();
    expect(screen.getByText('Judge 실행 성공')).toBeVisible();
    expect(screen.getByText(/Judge 모델: gpt-4.1-mini/)).toBeVisible();
    expect(screen.getByText(/판단 확신도 84.0%/)).toBeVisible();
    expect(screen.getByText('근거 종합 필요')).toBeVisible();
    expect(screen.getByText('2개')).toBeVisible();
    expect(screen.getByText(/Judge 비용 \$0.000130/)).toBeVisible();
    expect(
      screen.getByText(
        (_, element) =>
          element?.textContent === '학습 방식: Judge 학습 중 · 기준 78.0%',
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

  it('중첩된 실행 trace의 model_routing과 Judge 사유를 읽는다', () => {
    render(
      <ModelRoutingDecisionDetails
        traceMetadata={{
          llm: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-5.4-mini',
              decision_source: 'runtime_judge',
              reason_code: 'structured_reasoning_required',
              judge: {
                model: 'gpt-4.1-mini',
                reason_code: 'structured_reasoning_required',
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('선택 모델')).toBeVisible();
    expect(screen.getByText('gpt-5.4-mini')).toBeVisible();
    expect(screen.getByText('구조적 추론 필요')).toBeVisible();
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
      screen.getByText('로컬 라우터가 충분한 확신으로 모델을 선택했습니다.'),
    ).toBeVisible();
    expect(screen.getByText(/학습 방식: 로컬 라우터 우선/)).toBeVisible();
    expect(screen.getByText(/로컬 확신도 86.0%/)).toBeVisible();
    expect(screen.getByText(/선택 기준 78.0%/)).toBeVisible();
    expect(screen.getByText('Judge 호출 안 함')).toBeVisible();
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

    expect(screen.getByText('모델 호출 대체 실행')).toBeVisible();
    expect(screen.getByText('gpt-5.6-luna')).toBeVisible();
    expect(screen.getByText('Provider 호출 실패')).toBeVisible();
    expect(screen.getByText('gpt-5.6-terra')).toBeVisible();
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
        '이 테스트 실행은 배포 정책을 미리 적용한 결과이며, 정책 학습에는 포함되지 않습니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('Judge 호출 안 함')).toBeVisible();
  });

  it('Judge 호출 성공이면 선택 근거, 확신도, 비용을 하나의 Judge 실행 영역에 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1-mini',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-4.1-mini',
              decision_source: 'runtime_judge',
              reason_code: 'balanced_quality',
              judge_called: true,
              judge: {
                status: 'selected',
                attempted: true,
                model: 'gpt-5.4-mini',
                confidence: 0.89,
                reason_short: '균형 품질 판단',
                candidate_model_count: 11,
                cost: 0.003131,
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('모델 선택 결과')).toBeVisible();
    expect(screen.getByText('Judge가 모델 선택')).toBeVisible();
    expect(screen.getByText('Judge 실행 성공')).toBeVisible();
    expect(screen.getByText(/판단 확신도 89.0%/)).toBeVisible();
    expect(screen.getByText(/Judge 비용 \$0.003131/)).toBeVisible();
  });

  it('Judge 호출 후 실패해 기본 모델로 회귀한 경우와 Judge 미호출을 구분한다', () => {
    const { rerender } = render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5.4-mini',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-5.4-mini',
              decision_source: 'stored_model',
              reason_code: 'runtime_judge_unavailable',
              judge_called: true,
              judge: {
                status: 'failed',
                attempted: true,
                model: 'gpt-5.4-mini',
                candidate_model_count: 11,
                error_code: 'responses_incomplete',
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('Judge 호출 실패')).toBeVisible();
    expect(
      screen.getByText('Judge 결과를 사용할 수 없어 기본 모델로 실행했습니다.'),
    ).toBeVisible();
    expect(screen.getByText('응답이 완료되기 전에 종료됨')).toBeVisible();

    rerender(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1-mini',
          metadata: {
            model_routing: {
              strategy_id: 'judge_bootstrap_incremental_v1',
              selected_model: 'gpt-4.1-mini',
              decision_source: 'local_router',
              reason_code: 'local_router_confident',
              judge_called: false,
              judge: {
                status: 'not_called',
                attempted: false,
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('Judge 호출 안 함')).toBeVisible();
    expect(
      screen.getByText('로컬 라우터가 충분한 확신으로 모델을 선택했습니다.'),
    ).toBeVisible();
  });
});
