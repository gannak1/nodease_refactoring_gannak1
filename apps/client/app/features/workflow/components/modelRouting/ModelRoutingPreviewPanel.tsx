import { AlertTriangle, Route } from 'lucide-react';

import type { ModelRoutingPreviewResponse } from '../../types/Api';

type ModelRoutingPreviewPanelProps = {
  preview: ModelRoutingPreviewResponse;
};

const reasonLabel = (reasonCode: string) => {
  const labels: Record<string, string> = {
    validated_quality_floor_cost_reduction:
      '이 입력군에서 품질 기준을 통과한 모델 중 예상 비용이 가장 낮습니다.',
    policy_rule_matched: '현재 입력이 배포 정책의 입력군 규칙과 일치합니다.',
    policy_default: '일치하는 규칙이 없어 사용자가 정한 기본 모델을 사용합니다.',
    semantic_matched_no_rule_default:
      '입력군은 확인했지만 전용 규칙이 없어 기본 모델을 사용합니다.',
    semantic_ambiguous_default:
      '입력군 판단이 애매해 안전하게 기본 모델을 사용합니다.',
    semantic_unavailable_default:
      '입력군 판단을 사용할 수 없어 기본 모델을 사용합니다.',
  };
  return labels[reasonCode] ?? '배포 정책의 현재 규칙을 기준으로 모델을 선택했습니다.';
};

export function ModelRoutingPreviewPanel({
  preview,
}: ModelRoutingPreviewPanelProps) {
  const usingFallback = preview.decision_source === 'fallback_model';

  return (
    <section className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-900 dark:bg-emerald-950/20">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <Route className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
          <div>
            <h3 className="text-sm font-semibold text-emerald-950 dark:text-emerald-100">
              라우팅 판단 미리보기
            </h3>
            <p className="mt-1 text-xs text-emerald-800 dark:text-emerald-200">
              배포 v{preview.deployment_version} 정책 기준
            </p>
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-emerald-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
          미리보기
        </span>
      </div>

      {!preview.draft_matches_deployment && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          현재 편집 내용은 아직 배포되지 않아 미리보기에 반영되지 않았습니다.
        </div>
      )}

      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border border-emerald-100 bg-white p-2 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="text-emerald-800 dark:text-emerald-200">선택 모델</dt>
          <dd className="mt-1 break-all font-semibold text-gray-900 dark:text-gray-100">
            {preview.selected_model_id}
          </dd>
        </div>
        <div className="rounded-md border border-emerald-100 bg-white p-2 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="text-emerald-800 dark:text-emerald-200">
            규칙 미일치 시 기본 모델
          </dt>
          <dd className="mt-1 break-all font-semibold text-gray-900 dark:text-gray-100">
            {preview.default_model_id || '설정 없음'}
          </dd>
        </div>
        <div className="rounded-md border border-emerald-100 bg-white p-2 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="text-emerald-800 dark:text-emerald-200">
            기본 모델 실패 시 대체 모델
          </dt>
          <dd className="mt-1 break-all font-semibold text-gray-900 dark:text-gray-100">
            {preview.configured_fallback_model_id || '설정 없음'}
          </dd>
        </div>
        <div className="rounded-md border border-emerald-100 bg-white p-2 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="text-emerald-800 dark:text-emerald-200">매칭 입력군</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            {preview.matched_cohort?.label || '규칙 미일치'}
          </dd>
        </div>
        <div className="rounded-md border border-emerald-100 bg-white p-2 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="text-emerald-800 dark:text-emerald-200">매칭 규칙</dt>
          <dd className="mt-1 break-all font-semibold text-gray-900 dark:text-gray-100">
            {preview.matched_rule_id || '기본 모델 규칙'}
          </dd>
        </div>
      </dl>

      <div className="mt-3 rounded-md border border-emerald-100 bg-white p-3 text-xs text-gray-700 dark:border-emerald-900 dark:bg-gray-900 dark:text-gray-200">
        <p className="font-semibold text-gray-900 dark:text-gray-100">
          {usingFallback ? '기본 대체 모델로 전환' : '선택 이유'}
        </p>
        <p className="mt-1 leading-relaxed">{reasonLabel(preview.reason_code)}</p>
        <p className="mt-2 text-gray-500 dark:text-gray-400">
          정책 버전: {preview.policy_version || '알 수 없음'}
        </p>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-emerald-800 dark:text-emerald-200">
        실제 LLM 답변, 실행 로그, LLM 사용량 로그, 정책 점검 카운터를 만들지 않습니다.
        입력군 의미 판정이 필요한 정책은 embedding 호출의 작은 비용이 발생할 수 있습니다.
      </p>
    </section>
  );
}
