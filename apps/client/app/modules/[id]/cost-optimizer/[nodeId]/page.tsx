'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  BarChart3,
  Clock3,
  FileText,
  FlaskConical,
  Play,
} from 'lucide-react';

import { CostOptimizerBaselineSelection } from '@/app/features/workflow/components/costOptimizer/CostOptimizerBaselineSelection';
import { NodeSettingsComparisonPanel } from '@/app/features/workflow/components/costOptimizer/NodeSettingsComparisonPanel';
import {
  baselineOptionsOf,
  candidateFromNode,
  candidateFromOptions,
  findTargetNode,
  type BaselineNodeOptions,
  type CandidateDraft,
  type SettingsTab,
} from '@/app/features/workflow/components/costOptimizer/costOptimizerPlaygroundModel';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import {
  fitPanelWidths,
  getDefaultPanelWidthsForLayout,
  getNodeEditorMaxLayoutWidth,
  type HorizontalResizeHandle,
  NODE_EDITOR_PANEL_WIDTHS,
  type NodeEditorPanelWidths,
  resizePanelWidths,
  sumPanelWidths,
} from '@/app/features/workflow/utils/nodeEditorPanelLayout';
import type { CostOptimizerBaselineRow } from '@/app/features/workflow/types/Api';
import type { AppNode, LLMNodeData } from '@/app/features/workflow/types/Nodes';

type PlaygroundMode = 'setup' | 'report';

const formatMetric = (value: number, suffix = '') => {
  if (!Number.isFinite(value)) return '-';
  return `${value.toLocaleString('ko-KR')}${suffix}`;
};

const formatCost = (value: number) => {
  if (!Number.isFinite(value)) return '-';
  return `$${value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
};

const formatLatency = (latencyMs: number) => {
  if (!Number.isFinite(latencyMs)) return '-';
  if (latencyMs < 1000) return `${latencyMs}ms`;
  return `${(latencyMs / 1000).toFixed(1)}s`;
};

type PreviewRow = {
  label: string;
  value: string;
};

const normalizePreviewValue = (value: string) => value.replace(/\s+/g, ' ').trim();

const parseJsonPreview = (value: string): unknown => {
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) {
    return value;
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
};

const collectPreviewRows = (
  value: unknown,
  prefix = '',
  rows: PreviewRow[] = [],
) => {
  if (rows.length >= 6 || value === null || value === undefined) return rows;

  if (typeof value !== 'object') {
    const label = prefix.split('.').pop() || prefix || '내용';
    const text = normalizePreviewValue(String(value));
    if (text) rows.push({ label, value: text });
    return rows;
  }

  if (Array.isArray(value)) {
    value.slice(0, 4).forEach((item, index) => {
      collectPreviewRows(item, `${prefix}[${index}]`, rows);
    });
    return rows;
  }

  Object.entries(value as Record<string, unknown>)
    .slice(0, 8)
    .forEach(([key, item]) => {
      const nextPrefix = prefix ? `${prefix}.${key}` : key;
      collectPreviewRows(item, nextPrefix, rows);
    });
  return rows;
};

const getPreviewRows = (value: string) => {
  if (!value) return [];
  return collectPreviewRows(parseJsonPreview(value));
};

const PreviewSection = ({
  title,
  value,
}: {
  title: string;
  value: string;
}) => {
  const rows = getPreviewRows(value);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="text-xs font-bold text-slate-700">{title}</h3>
      {rows.length > 0 ? (
        <dl className="mt-3 space-y-2">
          {rows.map((row, index) => (
            <div key={`${row.label}-${index}`} className="grid gap-1">
              <dt className="text-[11px] font-bold text-slate-400">
                {row.label}
              </dt>
              <dd className="break-words rounded-md bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-700">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-400">
          보관된 preview가 없습니다.
        </p>
      )}
    </section>
  );
};

const PanelResizeHandle = ({
  label,
  onPointerDown,
  onKeyDown,
}: {
  label: string;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
}) => (
  <div
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    tabIndex={0}
    onPointerDown={onPointerDown}
    onKeyDown={onKeyDown}
    className="group relative z-10 w-2 shrink-0 cursor-col-resize bg-slate-100 transition-colors hover:bg-emerald-50 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-inset"
  >
    <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-slate-200 transition-colors group-hover:bg-emerald-400" />
    <div className="absolute left-1/2 top-1/2 h-10 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300 transition-colors group-hover:bg-emerald-400" />
  </div>
);

export default function CostOptimizerPlaygroundPage() {
  const router = useRouter();
  const params = useParams<{ id: string; nodeId: string }>();
  const workflowId = params.id;
  const nodeId = params.nodeId;

  const [targetNode, setTargetNode] = useState<AppNode | null>(null);
  const [baseline, setBaseline] = useState<CostOptimizerBaselineRow | null>(
    null,
  );
  const [candidate, setCandidate] = useState<CandidateDraft>(() =>
    candidateFromNode(null),
  );
  const [baselineSettingsTab, setBaselineSettingsTab] =
    useState<SettingsTab>('basic');
  const [candidateSettingsTab, setCandidateSettingsTab] =
    useState<SettingsTab>('basic');
  const [testName, setTestName] = useState('');
  const [activeMode, setActiveMode] = useState<PlaygroundMode>('setup');
  const [isLoadingNode, setIsLoadingNode] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [isStale, setIsStale] = useState(false);
  const [panelWidths, setPanelWidths] = useState<NodeEditorPanelWidths>(
    NODE_EDITOR_PANEL_WIDTHS.default,
  );
  const [layoutWidth, setLayoutWidth] = useState<number>(
    sumPanelWidths(NODE_EDITOR_PANEL_WIDTHS.default) +
      NODE_EDITOR_PANEL_WIDTHS.resizeHandleWidth * 2,
  );
  const [isResizableLayout, setIsResizableLayout] = useState(true);
  const layoutShellRef = useRef<HTMLElement>(null);
  const hasCustomPanelWidthsRef = useRef(false);

  useEffect(() => {
    let active = true;

    const loadDraft = async () => {
      setIsLoadingNode(true);
      setLoadError('');
      try {
        const draft = await workflowApi.getDraftWorkflow(workflowId);
        if (!active) return;
        const node = findTargetNode(draft, nodeId);
        setTargetNode(node);
        setCandidate(candidateFromNode(node));
      } catch {
        if (!active) return;
        setLoadError('워크플로우 정보를 불러오지 못했습니다.');
      } finally {
        if (active) setIsLoadingNode(false);
      }
    };

    void loadDraft();

    return () => {
      active = false;
    };
  }, [nodeId, workflowId]);

  useEffect(() => {
    const layoutShell = layoutShellRef.current;
    if (!layoutShell) return;

    const updateLayoutWidth = () => {
      const shellWidth = layoutShell.getBoundingClientRect().width;
      const nextLayoutWidth = getNodeEditorMaxLayoutWidth(shellWidth);
      const minResizableWidth =
        sumPanelWidths(NODE_EDITOR_PANEL_WIDTHS.min) +
        NODE_EDITOR_PANEL_WIDTHS.resizeHandleWidth * 2;
      const nextIsResizableLayout = nextLayoutWidth >= minResizableWidth;

      setIsResizableLayout(nextIsResizableLayout);
      setLayoutWidth(nextLayoutWidth);

      if (!hasCustomPanelWidthsRef.current) {
        setPanelWidths(getDefaultPanelWidthsForLayout(nextLayoutWidth));
      }
    };

    updateLayoutWidth();
    const resizeObserver = new ResizeObserver(updateLayoutWidth);
    resizeObserver.observe(layoutShell);

    return () => resizeObserver.disconnect();
  }, []);

  const nodeTitle = useMemo(() => {
    const data = targetNode?.data as { title?: string; label?: string } | null;
    return data?.title || data?.label || nodeId;
  }, [nodeId, targetNode]);
  const targetNodeDetailPath = useMemo(
    () => `/modules/${workflowId}?node=${encodeURIComponent(nodeId)}`,
    [nodeId, workflowId],
  );

  const baselineNodeOptions = baselineOptionsOf(baseline);

  const updateCandidate = <K extends keyof CandidateDraft>(
    key: K,
    value: CandidateDraft[K],
  ) => {
    setCandidate((current) => ({ ...current, [key]: value }));
    setIsStale(Boolean(baseline));
  };

  const updateCandidateNodeData = (updates: Partial<LLMNodeData>) => {
    const params = updates.parameters || {};
    setCandidate((current) => ({
      ...current,
      model_id: updates.model_id ?? current.model_id,
      fallback_model_id:
        updates.fallback_model_id ?? current.fallback_model_id,
      system_prompt: updates.system_prompt ?? current.system_prompt,
      user_prompt: updates.user_prompt ?? current.user_prompt,
      assistant_prompt: updates.assistant_prompt ?? current.assistant_prompt,
      max_tokens:
        typeof params.max_tokens === 'number'
          ? params.max_tokens
          : current.max_tokens,
      temperature:
        typeof params.temperature === 'number'
          ? params.temperature
          : current.temperature,
      top_p: typeof params.top_p === 'number' ? params.top_p : current.top_p,
      presence_penalty:
        typeof params.presence_penalty === 'number'
          ? params.presence_penalty
          : current.presence_penalty,
      frequency_penalty:
        typeof params.frequency_penalty === 'number'
          ? params.frequency_penalty
          : current.frequency_penalty,
      stop: Array.isArray(params.stop)
        ? params.stop.filter((item): item is string => typeof item === 'string')
        : current.stop,
      knowledgeBases: updates.knowledgeBases ?? current.knowledgeBases,
      topK: typeof updates.topK === 'number' ? updates.topK : current.topK,
      scoreThreshold:
        typeof updates.scoreThreshold === 'number'
          ? updates.scoreThreshold
          : current.scoreThreshold,
    }));
    setIsStale(Boolean(baseline));
  };

  const fittedPanelWidths = fitPanelWidths(panelWidths, layoutWidth);
  const fittedLayoutWidth =
    sumPanelWidths(fittedPanelWidths) +
    NODE_EDITOR_PANEL_WIDTHS.resizeHandleWidth * 2;

  const updateHorizontalPanelWidths = useCallback(
    (handle: HorizontalResizeHandle, deltaX: number) => {
      hasCustomPanelWidthsRef.current = true;
      setPanelWidths((current) =>
        resizePanelWidths(handle, current, deltaX, layoutWidth),
      );
    },
    [layoutWidth],
  );

  const handleHorizontalResizeStart = useCallback(
    (handle: HorizontalResizeHandle, event: PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);

      const startX = event.clientX;
      const startWidths = fittedPanelWidths;

      const handlePointerMove = (moveEvent: globalThis.PointerEvent) => {
        const deltaX = moveEvent.clientX - startX;
        hasCustomPanelWidthsRef.current = true;
        setPanelWidths(
          resizePanelWidths(handle, startWidths, deltaX, layoutWidth),
        );
      };

      const handlePointerUp = () => {
        window.removeEventListener('pointermove', handlePointerMove);
        window.removeEventListener('pointerup', handlePointerUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    },
    [fittedPanelWidths, layoutWidth],
  );

  const handleHorizontalResizeKeyDown = useCallback(
    (
      handle: HorizontalResizeHandle,
      event: KeyboardEvent<HTMLDivElement>,
    ) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const direction = event.key === 'ArrowLeft' ? -1 : 1;
      updateHorizontalPanelWidths(
        handle,
        direction * NODE_EDITOR_PANEL_WIDTHS.keyboardStep,
      );
    },
    [updateHorizontalPanelWidths],
  );

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-slate-100 text-slate-950">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-6 py-4 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => router.push(targetNodeDetailPath)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <ArrowLeft className="h-4 w-4" />
              워크플로우로 돌아가기
            </button>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">
                Cost Optimizer Playground
              </p>
              <h1 className="truncate text-lg font-bold">
                {isLoadingNode ? 'LLM 노드 확인 중' : nodeTitle}
              </h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
            {baseline ? (
              <>
                <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-1">
                  {(
                    [
                      ['setup', '실험 설정'],
                      ['report', '결과 분석'],
                    ] as const
                  ).map(([mode, label]) => (
                    <button
                      key={mode}
                      type="button"
                      aria-pressed={activeMode === mode}
                      onClick={() => setActiveMode(mode)}
                      className={`rounded-md px-3 py-1.5 text-xs font-bold transition-colors ${
                        activeMode === mode
                          ? 'bg-white text-emerald-700 shadow-sm'
                          : 'text-slate-500 hover:text-slate-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-blue-700">
                  같은 입력 기준
                </span>
              </>
            ) : (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-amber-700">
                테스트 기준 선택 필요
              </span>
            )}
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
              workflow {workflowId.slice(0, 8)}
            </span>
          </div>
        </div>
      </header>

      <section
        ref={layoutShellRef}
        className="flex min-h-0 flex-1 justify-center overflow-hidden p-4"
      >
        {!baseline ? (
          <div className="flex h-full min-h-0 w-full max-w-[760px] flex-col justify-center">
            <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-5 rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3">
                <div className="text-sm font-bold text-emerald-950">
                  먼저 A/B 테스트 기준을 선택하세요
                </div>
                <p className="mt-1 text-xs leading-relaxed text-emerald-800">
                  기준 실행 로그가 정해지면 B 후보 설정과 Inspector가 열립니다.
                  같은 입력을 기준으로 비교해야 비용, 출력, trace 차이가 의미를
                  갖습니다.
                </p>
              </div>
              <CostOptimizerBaselineSelection
                workflowId={workflowId}
                nodeId={nodeId}
                onBaselineSelected={(selectedBaseline) => {
                  setBaseline(selectedBaseline);
                  setCandidate(
                    candidateFromOptions(
                      baselineOptionsOf(selectedBaseline) ||
                        ((targetNode?.data || {}) as BaselineNodeOptions),
                    ),
                  );
                  setActiveMode('setup');
                  setIsStale(false);
                }}
                onClose={() => router.push(targetNodeDetailPath)}
              />
            </div>
          </div>
        ) : activeMode === 'setup' ? (
          <div
            className="grid h-full min-h-0 w-full grid-cols-1 gap-4 overflow-hidden xl:gap-0"
            style={
              isResizableLayout
                ? {
                    width: `${fittedLayoutWidth}px`,
                    gridTemplateColumns: `${fittedPanelWidths.left}px 8px ${fittedPanelWidths.center}px 8px ${fittedPanelWidths.right}px`,
                  }
                : undefined
            }
          >
        <aside className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Clock3 className="h-4 w-4 text-emerald-600" />
              <h2 className="text-sm font-bold">A 실행 시점 옵션</h2>
            </div>
            {baseline ? (
              <button
                type="button"
                onClick={() => {
                  setBaseline(null);
                  setActiveMode('setup');
                  setIsStale(false);
                }}
                className="shrink-0 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                다시 선택
              </button>
            ) : null}
          </div>
          {baseline ? (
            <div className="space-y-4">
              {baselineNodeOptions ? (
                <NodeSettingsComparisonPanel
                  title="실행 시점 옵션"
                  nodeId={`${nodeId}-baseline`}
                  tab={baselineSettingsTab}
                  onTabChange={setBaselineSettingsTab}
                  draft={candidateFromOptions(baselineNodeOptions)}
                  readOnly
                />
              ) : (
                <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">
                  이 baseline에는 실행 시점 노드 옵션 스냅샷이 없습니다. B 후보는
                  현재 노드 설정을 기준으로 유지됩니다.
                </p>
              )}
            </div>
          ) : (
            <CostOptimizerBaselineSelection
              workflowId={workflowId}
              nodeId={nodeId}
              onBaselineSelected={(selectedBaseline) => {
                setBaseline(selectedBaseline);
                setCandidate(
                  candidateFromOptions(
                    baselineOptionsOf(selectedBaseline) ||
                      ((targetNode?.data || {}) as BaselineNodeOptions),
                  ),
                );
                setIsStale(false);
              }}
              onClose={() => router.push(targetNodeDetailPath)}
            />
          )}
        </aside>

        {isResizableLayout ? (
          <PanelResizeHandle
            label="baseline 패널과 candidate 패널 사이 폭 조절"
            onPointerDown={(event) =>
              handleHorizontalResizeStart('left-center', event)
            }
            onKeyDown={(event) =>
              handleHorizontalResizeKeyDown('left-center', event)
            }
          />
        ) : null}

        <section className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="sticky top-0 z-[1] flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-bold">
                <FlaskConical className="h-4 w-4 text-emerald-600" />
                B candidate
              </div>
              <p className="mt-1 text-xs text-slate-500">
                현재 LLM 노드 설정 복사본을 기준으로 후보 옵션을 조정합니다.
              </p>
              <label className="mt-3 grid max-w-md gap-1 text-xs font-semibold text-slate-600">
                <span>테스트명</span>
                <input
                  value={testName}
                  onChange={(event) => setTestName(event.target.value)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-900 outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
                  placeholder="예: gpt-4.1-mini 비용 절감 테스트"
                />
              </label>
            </div>
            <button
              type="button"
              disabled
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-200 px-3 py-2 text-xs font-bold text-slate-500"
              title="B 후보 실행 API 연결 후 활성화됩니다."
            >
              <Play className="h-3.5 w-3.5" />
              B 실행 준비 중
            </button>
          </div>

          {loadError ? (
            <p className="m-5 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {loadError}
            </p>
          ) : null}

          {isStale ? (
            <p className="mx-5 mt-5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
              후보 설정이 마지막 기준 선택 이후 변경되었습니다. B 실행 API가
              연결되면 이 설정으로 다시 실행해야 합니다.
            </p>
          ) : null}

          <div className="p-5">
            <NodeSettingsComparisonPanel
              title="후보 옵션"
              hideTitle
              nodeId={`${nodeId}-candidate`}
              tab={candidateSettingsTab}
              onTabChange={setCandidateSettingsTab}
              draft={candidate}
              onChange={updateCandidate}
              onNodeDataChange={updateCandidateNodeData}
            />
          </div>
        </section>

        {isResizableLayout ? (
          <PanelResizeHandle
            label="candidate 패널과 inspector 패널 사이 폭 조절"
            onPointerDown={(event) =>
              handleHorizontalResizeStart('center-right', event)
            }
            onKeyDown={(event) =>
              handleHorizontalResizeKeyDown('center-right', event)
            }
          />
        ) : null}

        <aside className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-bold">기준 실행 정보</h2>
          </div>
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <div className="text-xs font-semibold text-emerald-700">
                선택된 기준 실행
              </div>
              <div className="mt-1 text-sm font-bold text-emerald-950">
                {baseline.model}
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div className="rounded-md bg-white/70 p-2">
                  <dt className="text-emerald-700">비용</dt>
                  <dd className="font-bold">{formatCost(baseline.cost)}</dd>
                </div>
                <div className="rounded-md bg-white/70 p-2">
                  <dt className="text-emerald-700">토큰</dt>
                  <dd className="font-bold">
                    {formatMetric(baseline.total_tokens)}
                  </dd>
                </div>
                <div className="rounded-md bg-white/70 p-2">
                  <dt className="text-emerald-700">시간</dt>
                  <dd className="font-bold">
                    {formatLatency(baseline.latency_ms)}
                  </dd>
                </div>
              </dl>
            </div>
            <PreviewSection title="기준 입력" value={baseline.input_preview} />
            <PreviewSection title="기준 출력" value={baseline.output_preview} />
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-xs font-bold text-slate-500">
                B 후보 비교 컨텍스트
              </div>
              <dl className="mt-2 space-y-2 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">B 모델</dt>
                  <dd className="font-semibold">{candidate.model_id || '-'}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">B 출력</dt>
                  <dd className="font-semibold">
                    {candidate.output_format.toUpperCase()}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">B 지식 베이스</dt>
                  <dd className="font-semibold">
                    {candidate.knowledgeBases.length}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">B Threshold</dt>
                  <dd className="font-semibold">
                    {candidate.scoreThreshold.toFixed(2)}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <div className="text-xs font-bold text-slate-500">상태</div>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                {baseline
                  ? 'A baseline이 고정되었습니다. B 옵션을 조정하면서 실행 결과를 비교할 수 있습니다.'
                  : '먼저 왼쪽에서 A baseline을 선택하세요.'}
              </p>
            </div>
          </div>
        </aside>
          </div>
        ) : (
          <div className="flex h-full min-h-0 w-full max-w-[90vw] flex-col gap-4 overflow-y-auto">
            <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-emerald-600" />
                  <h2 className="text-base font-bold">비교 리포트</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setActiveMode('setup')}
                    className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
                  >
                    실험 설정으로 돌아가기
                  </button>
                  <button
                    type="button"
                    disabled
                    className="rounded-md bg-slate-200 px-3 py-2 text-xs font-bold text-slate-500"
                    title="B 후보 실행 API 연결 후 활성화됩니다."
                  >
                    현재 노드에 적용
                  </button>
                </div>
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-4">
                <div className="rounded-lg bg-slate-50 p-3">
                  <div className="text-xs font-semibold text-slate-500">
                    A 비용
                  </div>
                  <div className="mt-1 text-lg font-bold">
                    {baseline ? `$${baseline.cost}` : '-'}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <div className="text-xs font-semibold text-slate-500">
                    A 토큰
                  </div>
                  <div className="mt-1 text-lg font-bold">
                    {baseline ? formatMetric(baseline.total_tokens) : '-'}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <div className="text-xs font-semibold text-slate-500">
                    B 모델
                  </div>
                  <div className="mt-1 truncate text-lg font-bold">
                    {candidate.model_id || '-'}
                  </div>
                </div>
                <div className="rounded-lg bg-amber-50 p-3">
                  <div className="text-xs font-semibold text-amber-700">
                    B 실행 상태
                  </div>
                  <div className="mt-1 text-sm font-bold text-amber-900">
                    실행 대기
                  </div>
                </div>
              </div>
            </div>

            <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[1fr_1fr_360px]">
              <section className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <Clock3 className="h-4 w-4 text-emerald-600" />
                  <h3 className="text-sm font-bold">A baseline 결과</h3>
                </div>
                {baseline ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div className="rounded-md bg-slate-50 p-2">
                        <div className="text-slate-500">모델</div>
                        <div className="truncate font-bold">{baseline.model}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 p-2">
                        <div className="text-slate-500">비용</div>
                        <div className="font-bold">${baseline.cost}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 p-2">
                        <div className="text-slate-500">시간</div>
                        <div className="font-bold">
                          {formatMetric(baseline.latency_ms, 'ms')}
                        </div>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-bold text-slate-700">
                        출력
                      </div>
                      <pre className="max-h-72 overflow-auto rounded-md bg-slate-50 p-3 text-xs text-slate-700">
                        {baseline.output_preview || '-'}
                      </pre>
                    </div>
                  </div>
                ) : (
                  <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                    먼저 실험 설정에서 A baseline을 선택하세요.
                  </p>
                )}
              </section>

              <section className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <FlaskConical className="h-4 w-4 text-emerald-600" />
                  <h3 className="text-sm font-bold">B candidate 결과</h3>
                </div>
                <div className="rounded-lg border border-dashed border-amber-200 bg-amber-50 p-4 text-sm leading-relaxed text-amber-800">
                  B 실행 후 결과 분석이 표시됩니다. 지금은 후보 설정만 준비된
                  상태입니다.
                </div>
              </section>

              <aside className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-emerald-600" />
                  <h3 className="text-sm font-bold">분석 요약</h3>
                </div>
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs font-bold text-slate-500">Diff</div>
                    <dl className="mt-2 space-y-2 text-xs">
                      <div className="flex justify-between gap-3">
                        <dt className="text-slate-500">A 모델</dt>
                        <dd className="font-semibold">
                          {baseline?.model || '-'}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-slate-500">B 모델</dt>
                        <dd className="font-semibold">
                          {candidate.model_id || '-'}
                        </dd>
                      </div>
                    </dl>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs font-bold text-slate-500">
                      RAG
                    </div>
                    <dl className="mt-2 space-y-2 text-xs">
                      <div className="flex justify-between gap-3">
                        <dt className="text-slate-500">A 지식 베이스</dt>
                        <dd className="font-semibold">
                          {baselineNodeOptions?.knowledgeBases?.length ?? '-'}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-slate-500">B 지식 베이스</dt>
                        <dd className="font-semibold">
                          {candidate.knowledgeBases.length}
                        </dd>
                      </div>
                    </dl>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs font-bold text-slate-500">
                      Downstream
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-500">
                      B 실행 결과가 생성되면 schema와 downstream 호환성 판단을
                      함께 표시합니다.
                    </p>
                  </div>
                </div>
              </aside>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
