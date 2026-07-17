import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ModelRoutingDecisionDetails } from '../../components/modelRouting/ModelRoutingDecisionDetails';

afterEach(() => {
  cleanup();
});

describe('FR-011 prior-guided model routing trace', () => {
  it('회귀형 복잡도 점수와 후보 선택 근거를 세 구간 등급 없이 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5-mini',
          metadata: {
            model_routing: {
              strategy_id: 'bootstrap_request_complexity_regression_v4',
              selected_model: 'gpt-5-mini',
              fallback_model: 'gpt-5.4',
              reason_code: 'complexity_regression_global_profile',
              policy_version: 'bootstrap-regression-v1',
              decision_factors: {
                routing_basis: 'request_prompt_complexity_regression',
                complexity_score: 64,
                complexity_uncertainty: 4,
                compared_model_count: 4,
                quality_floor: 0.8088,
                selected_quality_lower_bound: 0.8244,
                selected_expected_cost_usd: 0.0012,
                selected_expected_latency_ms: 600,
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('요청 복잡도 점수 기반 자동 라우팅')).toBeVisible();
    expect(screen.getByText('복잡도 점수 64/100')).toBeVisible();
    expect(screen.getByText('예측 오차 ±4점')).toBeVisible();
    expect(screen.getByText('검토 모델 4개')).toBeVisible();
    expect(screen.getByText('품질 하한 82.4%')).toBeVisible();
    expect(screen.getByText('예상 비용 $0.001200')).toBeVisible();
    expect(screen.getByText('예상 지연 600ms')).toBeVisible();
    expect(
      screen.getByText(
        '요청 복잡도 점수에 필요한 품질을 만족한 후보 중 예상 비용과 지연이 가장 적절한 모델을 선택했습니다.',
      ),
    ).toBeVisible();
    expect(screen.queryByText(/등급 /)).not.toBeInTheDocument();
  });

  it('입력군 유사도 대신 일반 제약과 사전 지식 기반 선택 근거를 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1-mini',
          metadata: {
            model_routing: {
              strategy_id: 'prior_guided_adaptive_v1',
              selected_model: 'gpt-4.1-mini',
              fallback_model: 'gpt-4.1',
              decision_source: 'active_policy',
              reason_code: 'prior_guided_utility_selected',
              matched_rule_id: 'prior-guided-short',
              policy_version: 'prior-guided-v3',
              runtime_context: {
                input_length_bucket: 'short',
                output_format: 'json',
                schema_required: true,
                knowledge_enabled: false,
                has_file_input: false,
              },
              decision_factors: {
                profile: 'short',
                evaluated_candidate_count: 3,
                excluded_candidate_count: 1,
                selected_model_score: {
                  quality_lower_bound: 0.92,
                  expected_total_cost_usd: 0.00042,
                  expected_latency_ms: 640,
                  prior_source: 'model_catalog_family_prior',
                },
              },
              judge_called: false,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('사전 지식 기반 적응형 라우팅')).toBeVisible();
    expect(screen.getByText('짧은 입력')).toBeVisible();
    expect(screen.getByText('JSON 스키마 필요')).toBeVisible();
    expect(screen.getByText('지식 베이스 사용 안 함')).toBeVisible();
    expect(screen.getByText('gpt-4.1-mini')).toBeVisible();
    expect(screen.getByText('검토 모델 3개')).toBeVisible();
    expect(screen.getByText('조건 제외 1개')).toBeVisible();
    expect(screen.getByText('품질 하한 92.0%')).toBeVisible();
    expect(screen.getByText('예상 비용 $0.000420')).toBeVisible();
    expect(screen.getByText('예상 지연 640ms')).toBeVisible();
    expect(
      screen.getByText('근거 출처: 모델 카탈로그 사전 지식'),
    ).toBeVisible();
    expect(
      screen.getByText(
        '품질 하한을 만족한 후보 중 예상 비용과 지연 시간을 함께 비교해 선택했습니다.',
      ),
    ).toBeVisible();
    expect(screen.queryByText('입력군별 유사도')).not.toBeInTheDocument();
    expect(screen.queryByText(/선택 기준 \d+%/)).not.toBeInTheDocument();
    expect(screen.getByText(/정책 버전: prior-guided-v3/)).toBeVisible();
    expect(screen.getByText('실행 중 Judge 호출 안 함')).toBeVisible();
  });

  it('실제 fallback이 발생하면 최초 모델과 실제 대체 모델을 구분한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5.6-terra',
          metadata: {
            fallback_used: true,
            model_routing: {
              strategy_id: 'prior_guided_adaptive_v1',
              selected_model: 'gpt-5.6-luna',
              fallback_model: 'gpt-5.6-terra',
              fallback_used: true,
              fallback_from_model: 'gpt-5.6-luna',
              fallback_reason_code: 'provider_call_failed',
              decision_source: 'active_policy',
              reason_code: 'prior_guided_utility_selected',
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

  it('새로고침으로 복원한 trace_metadata.llm에서도 선택 근거를 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1-mini',
          metadata: {
            llm: {
              strategy_id: 'prior_guided_adaptive_v1',
              selected_model: 'gpt-4.1-mini',
              reason_code: 'prior_guided_utility_selected',
              policy_version: 'prior-guided-v4',
              input_length_bucket: 'medium',
              decision_factors: {
                profile: 'medium',
                evaluated_candidate_count: 2,
                excluded_candidate_count: 1,
                selected_model_score: {
                  quality_lower_bound: 0.9,
                  expected_total_cost_usd: 0.0008,
                  expected_latency_ms: 720,
                },
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByText('보통 입력')).toBeVisible();
    expect(screen.getByText('검토 모델 2개')).toBeVisible();
    expect(screen.getByText('품질 하한 90.0%')).toBeVisible();
    expect(screen.getByText(/정책 버전: prior-guided-v4/)).toBeVisible();
  });

  it('Judge-first 배포 실행은 Judge 선택과 로컬 학습 상태를 함께 표시한다', () => {
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
            judge: {
              model: 'gpt-4.1-mini',
              confidence: 0.84,
              reason_code: 'structured_reasoning_required',
              cost: 0.00013,
            },
            decision_factors: {
              learning_mode: 'judge_first',
              judged_request_count: 7,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('Judge 기반 점진 학습 자동 라우팅')).toBeVisible();
    expect(screen.getByText('이번 Judge 판단')).toBeVisible();
    expect(screen.getByText(/Judge 모델: gpt-4.1-mini/)).toBeVisible();
    expect(screen.getByText(/판단 확신도 84.0%/)).toBeVisible();
    expect(screen.getByText(/Judge 비용 \$0.000130/)).toBeVisible();
    expect(screen.getByText('학습 방식: Judge 학습 중')).toBeVisible();
  });

  it('Judge-first 테스트 미리보기는 실제 Judge 선택 결과처럼 표시하지 않는다', () => {
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
              judge_called: false,
            },
          },
        }}
      />,
    );

    expect(
      screen.getByText(
        '테스트 화면에서는 Judge를 호출하지 않습니다. 실제 배포 실행 전에 예상 기본 모델만 표시합니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('실행 중 Judge 호출 안 함')).toBeVisible();
    expect(screen.queryByText('이번 Judge 판단')).not.toBeInTheDocument();
  });
});
