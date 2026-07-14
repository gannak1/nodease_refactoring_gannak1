import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ModelRoutingDecisionDetails } from '../../components/modelRouting/ModelRoutingDecisionDetails';

afterEach(() => {
  cleanup();
});

describe('FR-011 semantic model routing trace', () => {
  it('선택된 입력 유형과 의미 유사도 근거를 사용자 언어로 표시한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4o-mini',
          metadata: {
            model_routing: {
              selected_model: 'gpt-4o-mini',
              fallback_model: 'gpt-4.1-mini',
              decision_source: 'active_policy',
              reason_code: 'quality_gate_passed_cost_reduction',
              matched_cohort_id: 'routine_support',
              semantic_route_label: '단순 사용·안내 문의',
              semantic_similarity: 0.88,
              semantic_threshold: 0.75,
              semantic_runner_up_score: 0.51,
              semantic_margin: 0.37,
              semantic_min_margin: 0.05,
              semantic_cohort_scores: [
                {
                  cohort_id: 'routine_support',
                  label: '단순 사용·안내 문의',
                  similarity: 0.88,
                  threshold: 0.75,
                },
                {
                  cohort_id: 'high_risk_support',
                  label: '보안·보상·장애 문의',
                  similarity: 0.51,
                  threshold: 0.75,
                },
              ],
              semantic_match_status: 'matched',
              route_catalog_version: 'ticket-routing-v1',
              policy_version: 'routing-policy-v3',
              judge_called: false,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('입력 유형')).toBeVisible();
    expect(screen.getAllByText('단순 사용·안내 문의')).toHaveLength(2);
    expect(screen.getByText('입력군별 유사도')).toBeVisible();
    expect(screen.getByText('보안·보상·장애 문의')).toBeVisible();
    expect(screen.getByText('88%')).toBeVisible();
    expect(screen.getByText('51%')).toBeVisible();
    expect(screen.getAllByText('선택 기준 75%')).toHaveLength(2);
    expect(
      screen.getByText('유사도 88% (선택 기준 75%, 2위와 차이 37%p)'),
    ).toBeVisible();
    expect(screen.getByText('gpt-4o-mini')).toBeVisible();
    expect(
      screen.getByText(
        '이 입력 유형에서 품질 기준을 통과한 모델 중 예상 비용이 가장 낮습니다.',
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        '호출 실패 시 검증된 gpt-4.1-mini 모델로 한 번 전환합니다.',
      ),
    ).toBeVisible();
    expect(
      screen.queryByText('quality_gate_passed_cost_reduction'),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/정책 버전: routing-policy-v3/)).toBeVisible();
    expect(screen.getByText('실행 중 Judge 호출 안 함')).toBeVisible();
  });

  it('입력 유형이 애매하면 기본 모델을 유지한 안전 판단으로 설명한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1',
          metadata: {
            model_routing: {
              selected_model: 'gpt-4.1',
              fallback_model: 'gpt-4.1-mini',
              decision_source: 'active_policy',
              reason_code: 'semantic_ambiguous_default',
              semantic_candidate_cohort_id: 'account_billing',
              semantic_candidate_label: '계정·결제 문의',
              semantic_similarity: 0.8,
              semantic_threshold: 0.75,
              semantic_runner_up_score: 0.78,
              semantic_margin: 0.02,
              semantic_match_status: 'ambiguous',
              route_catalog_version: 'ticket-routing-v1',
            },
          },
        }}
      />,
    );

    expect(screen.getByText('명확히 분류하지 못함')).toBeVisible();
    expect(screen.getByText('가장 가까운 유형')).toBeVisible();
    expect(screen.getByText('계정·결제 문의')).toBeVisible();
    expect(
      screen.getByText(
        '1위와 2위 의미 점수 차이가 안전 기준보다 작아 기본 모델을 유지했습니다.',
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        '애매한 입력을 저비용 모델로 보내지 않는 보수적 정책입니다.',
      ),
    ).toBeVisible();
  });

  it('정책의 안전 조건이 우선된 이유를 원문 없이 설명한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-4.1',
          metadata: {
            model_routing: {
              selected_model: 'gpt-4.1',
              fallback_model: 'gpt-4.1-mini',
              decision_source: 'active_policy',
              reason_code: 'semantic_high_risk_quality_floor',
              matched_cohort_id: 'high_risk',
              semantic_route_label: '보안 및 SLA 고위험',
              semantic_similarity: 0.61,
              semantic_threshold: 0.75,
              semantic_match_status: 'matched',
              semantic_decision_source: 'safety_override',
              semantic_lexical_score: 2,
              semantic_lexical_signal_count: 2,
              semantic_safety_override: true,
              route_catalog_version: 'ticket-routing-v7',
              judge_called: false,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('보안 및 SLA 고위험')).toBeVisible();
    expect(
      screen.getByText(
        '정책의 안전 조건 2개와 일치해 안전 유형을 우선했습니다.',
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        '비용 절감보다 사고 대응 품질을 우선해 검증된 모델을 선택했습니다.',
      ),
    ).toBeVisible();
    expect(screen.queryByText(/credential leak/i)).not.toBeInTheDocument();
  });

  it('실제 fallback이 발생하면 최초 모델, 안전한 실패 이유, 실제 대체 모델을 구분한다', () => {
    render(
      <ModelRoutingDecisionDetails
        output={{
          model: 'gpt-5.6-terra',
          metadata: {
            fallback_used: true,
            model_routing: {
              selected_model: 'gpt-5.6-luna',
              fallback_model: 'gpt-5.6-terra',
              fallback_used: true,
              fallback_from_model: 'gpt-5.6-luna',
              fallback_reason_code: 'provider_call_failed',
              decision_source: 'active_policy',
              reason_code: 'quality_gate_passed_cost_reduction',
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
});
