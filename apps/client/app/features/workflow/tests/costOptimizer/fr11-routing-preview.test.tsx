import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ModelRoutingPreviewPanel } from '../../components/modelRouting/ModelRoutingPreviewPanel';

afterEach(() => {
  cleanup();
});

describe('FR-011 routing preview panel', () => {
  it('배포 정책 기준의 선택 모델과 입력군 근거를 테스트 실행 결과와 분리해 표시한다', () => {
    render(
      <ModelRoutingPreviewPanel
        preview={{
          deployment_version: 2,
          policy_version: 'router-policy-v4',
          decision_source: 'matched_rule',
          selected_model_id: 'gpt-4o-mini',
          fallback_model_id: 'gpt-4.1-mini',
          default_model_id: 'gpt-4.1',
          configured_fallback_model_id: 'gpt-4.1-mini',
          matched_cohort: {
            id: 'routine-support',
            label: '단순 사용 안내',
          },
          matched_rule_id: 'route-routine-support',
          reason_code: 'validated_quality_floor_cost_reduction',
          availability: 'available',
          semantic_evaluation: 'embedding_used',
          draft_matches_deployment: true,
        }}
      />,
    );

    expect(screen.getByText('라우팅 판단 미리보기')).toBeVisible();
    expect(screen.getByText('배포 v2 정책 기준')).toBeVisible();
    expect(screen.getByText('gpt-4o-mini')).toBeVisible();
    expect(screen.getByText('규칙 미일치 시 기본 모델')).toBeVisible();
    expect(screen.getByText('기본 모델 실패 시 대체 모델')).toBeVisible();
    expect(screen.getAllByText('gpt-4.1').length).toBeGreaterThan(0);
    expect(screen.getByText('단순 사용 안내')).toBeVisible();
    expect(screen.getByText('route-routine-support')).toBeVisible();
    expect(
      screen.getByText(
        '이 입력군에서 품질 기준을 통과한 모델 중 예상 비용이 가장 낮습니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('정책 버전: router-policy-v4')).toBeVisible();
    expect(screen.getByText(/실제 LLM 답변, 실행 로그/)).toBeVisible();
    expect(screen.getByText(/embedding 호출의 작은 비용/)).toBeVisible();
    expect(screen.queryByText('테스트 실행 결과')).not.toBeInTheDocument();
  });

  it('기본 모델이 사용 불가하면 대체 모델을 선택했고 draft 차이가 있음을 표시한다', () => {
    render(
      <ModelRoutingPreviewPanel
        preview={{
          deployment_version: 2,
          policy_version: 'router-policy-v4',
          decision_source: 'fallback_model',
          selected_model_id: 'gpt-4.1-mini',
          fallback_model_id: null,
          default_model_id: 'gpt-4.1',
          configured_fallback_model_id: 'gpt-4.1-mini',
          matched_cohort: null,
          matched_rule_id: null,
          reason_code: 'policy_default',
          availability: 'fallback',
          semantic_evaluation: 'not_required',
          draft_matches_deployment: false,
        }}
      />,
    );

    expect(screen.getByText('기본 대체 모델로 전환')).toBeVisible();
    expect(screen.getAllByText('gpt-4.1-mini').length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        '현재 편집 내용은 아직 배포되지 않아 미리보기에 반영되지 않았습니다.',
      ),
    ).toBeVisible();
  });
});
