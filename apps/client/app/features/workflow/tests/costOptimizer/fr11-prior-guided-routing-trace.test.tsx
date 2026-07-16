import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ModelRoutingDecisionDetails } from '../../components/modelRouting/ModelRoutingDecisionDetails';

afterEach(() => {
  cleanup();
});

describe('FR-011 prior-guided model routing trace', () => {
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
});
