'use client';

import { Sparkles } from 'lucide-react';

import type { DeploymentParameterOptimizationConfig } from '../../types/Deployment';
import type { DeploymentOptimizationNode } from './types';

interface ParameterOptimizationStepProps {
  nodes: DeploymentOptimizationNode[];
  value: DeploymentParameterOptimizationConfig;
  onChange: (value: DeploymentParameterOptimizationConfig) => void;
  onBack: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  isDeploying: boolean;
}

const formatBudget = (value: number) => `$${value.toFixed(value % 1 ? 1 : 0)}`;

export function ParameterOptimizationStep({
  nodes,
  value,
  onChange,
  onBack,
  onCancel,
  onSubmit,
  isDeploying,
}: ParameterOptimizationStepProps) {
  const noLlmNode = nodes.length === 0;
  const selectedNodeIds = new Set(value.node_ids);

  const update = (patch: Partial<DeploymentParameterOptimizationConfig>) =>
    onChange({ ...value, ...patch });

  const toggleNode = (nodeId: string) => {
    const next = new Set(selectedNodeIds);
    if (next.has(nodeId)) {
      next.delete(nodeId);
    } else {
      next.add(nodeId);
    }
    update({ node_ids: [...next] });
  };

  return (
    <>
      <div className="border-b border-slate-200 px-6 py-5">
        <div className="flex items-start gap-3 pr-24">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-50 text-emerald-700">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-xl font-semibold text-slate-900">
              운영 비용 자동 최적화
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              배포 후 운영 로그를 모아 검증 가능한 응답 길이와 RAG 컨텍스트
              설정을 점검합니다. 모델 선택, 자동 모델 라우팅, 프롬프트는 바꾸지
              않습니다.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-5 px-6 py-5">
        <label className="flex items-start justify-between gap-4 rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <span>
            <span className="block text-sm font-semibold text-slate-900">
              운영 비용 자동 최적화 사용
            </span>
            <span className="mt-1 block text-xs leading-5 text-slate-600">
              충분한 배포 후 운영 로그가 쌓이면 후보 설정을 검증할 수 있습니다.
            </span>
          </span>
          <input
            aria-label="운영 비용 자동 최적화 사용"
            type="checkbox"
            role="switch"
            checked={value.enabled}
            disabled={noLlmNode}
            onChange={(event) => update({ enabled: event.target.checked })}
            className="mt-1 h-4 w-4 accent-emerald-600 disabled:cursor-not-allowed"
          />
        </label>

        {noLlmNode ? (
          <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            이 워크플로우에는 자동 최적화 대상으로 지정할 LLM 노드가 없습니다.
          </p>
        ) : value.enabled ? (
          <div className="space-y-5">
            <section aria-labelledby="optimization-node-targets">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3
                    id="optimization-node-targets"
                    className="text-sm font-semibold text-slate-900"
                  >
                    최적화 대상 LLM 노드
                  </h3>
                  <p className="mt-1 text-xs text-slate-600">
                    선택한 노드의 운영 실행만 수집합니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    update({
                      node_ids:
                        value.node_ids.length === nodes.length
                          ? []
                          : nodes.map((node) => node.id),
                    })
                  }
                  className="text-xs font-semibold text-emerald-700 hover:text-emerald-800"
                >
                  {value.node_ids.length === nodes.length ? '전체 해제' : '전체 선택'}
                </button>
              </div>
              <div className="mt-3 divide-y divide-slate-100 rounded-md border border-slate-200">
                {nodes.map((node) => (
                  <label
                    key={node.id}
                    className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2.5 hover:bg-slate-50"
                  >
                    <span className="min-w-0 truncate text-sm font-medium text-slate-800">
                      {node.title}
                    </span>
                    <input
                      aria-label={`${node.title} 자동 최적화 대상`}
                      type="checkbox"
                      checked={selectedNodeIds.has(node.id)}
                      onChange={() => toggleNode(node.id)}
                      className="h-4 w-4 shrink-0 accent-emerald-600"
                    />
                  </label>
                ))}
              </div>
            </section>

            <section aria-labelledby="optimization-check-interval">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3
                    id="optimization-check-interval"
                    className="text-sm font-semibold text-slate-900"
                  >
                    자동 점검 주기
                  </h3>
                  <p className="mt-1 text-xs text-slate-600">
                    성공한 배포 후 운영 실행이 이 횟수만큼 쌓이면 다음 점검 대상이 됩니다.
                  </p>
                </div>
                <output className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-sm font-semibold text-emerald-800">
                  {value.check_every_runs}회
                </output>
              </div>
              <input
                aria-label="자동 점검 주기"
                type="range"
                min="20"
                max="200"
                step="10"
                value={value.check_every_runs}
                onChange={(event) =>
                  update({ check_every_runs: Number(event.target.value) })
                }
                className="mt-3 w-full accent-emerald-600"
              />
              <div className="flex justify-between text-[11px] text-slate-500">
                <span>자주 점검</span>
                <span>권장: 50회</span>
                <span>보수적 점검</span>
              </div>
            </section>

            <section aria-labelledby="optimization-validation-budget">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3
                    id="optimization-validation-budget"
                    className="text-sm font-semibold text-slate-900"
                  >
                    월간 검증 예산
                  </h3>
                  <p className="mt-1 text-xs text-slate-600">
                    후보 설정을 재실행해 검증할 때만 사용합니다. 워크플로우 운영 예산과는 별도입니다.
                  </p>
                </div>
                <output className="rounded border border-violet-200 bg-violet-50 px-2 py-1 text-sm font-semibold text-violet-800">
                  {formatBudget(value.monthly_validation_budget_usd)}
                </output>
              </div>
              <input
                aria-label="월간 검증 예산"
                type="range"
                min="0.5"
                max="10"
                step="0.5"
                value={value.monthly_validation_budget_usd}
                onChange={(event) =>
                  update({
                    monthly_validation_budget_usd: Number(event.target.value),
                  })
                }
                className="mt-3 w-full accent-violet-600"
              />
              <div className="flex justify-between text-[11px] text-slate-500">
                <span>최소 $0.5</span>
                <span>권장: $3</span>
                <span>최대 $10</span>
              </div>
            </section>
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-600">
            자동 최적화를 사용하지 않으면 현재 배포 설정 그대로 실행하며, 검증 비용도 발생하지 않습니다.
          </p>
        )}
      </div>

      <div className="flex justify-between gap-3 border-t border-slate-200 px-6 py-4">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          이전
        </button>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isDeploying || (value.enabled && value.node_ids.length === 0)}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
          >
            {isDeploying ? '배포 중...' : '배포하기'}
          </button>
        </div>
      </div>
    </>
  );
}
