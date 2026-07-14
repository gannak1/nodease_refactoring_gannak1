import React, { useState, useEffect, useMemo } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { workflowApi } from '../../api/workflowApi';
import { knowledgeApi } from '@/app/features/knowledge/api/knowledgeApi';
import {
  BUDGET_EXCEEDED_MESSAGE,
  isBudgetExceededError,
} from '@/app/features/budget/utils/budgetGuard';
import {
  X,
  Play,
  RefreshCw,
  Loader2,
  CheckCircle,
  AlertCircle,
  ArrowLeft,
  ChevronRight,
  Clock,
  Coins,
  GitCompareArrows,
} from 'lucide-react';
import { toast } from 'sonner';
import { StartNodeData, WorkflowVariable } from '../../types/Nodes';
import { getNodeOutputVariables } from '../../utils/nodeVariablePorts';
import type { WorkflowDraftRequest } from '../../types/Workflow';
import {
  formatGraphIssue,
  type GraphValidationIssue,
  validateWorkflowGraph,
} from '../../utils/validateWorkflowGraph';
import { buildWorkflowDraftPayload } from '../../utils/workflowDraftPayload';
import {
  formatCost,
  formatLatency,
  formatTokens,
  isTestExecutionActionDisabled,
  readNodeFinishExecutionSummary,
  readCost,
  readTokenUsage,
  summarizeWorkflowExecution,
} from '../../utils/testExecutionSummary';
import {
  getFinalResponsePreview,
  shouldShowFinalResponseCard,
} from '../../utils/testExecutionFinalResponse';
import { FinalResponseCard } from '../execution/FinalResponseCard';
import { deploymentApiErrorMessage } from '../../utils/deploymentPreflightMessage';
import { ModelRoutingDecisionDetails } from '../modelRouting/ModelRoutingDecisionDetails';
import { restoreTestExecutionFromWorkflowRun } from '../../utils/testExecutionRestore';
import { ExecutionComparisonPanel } from './ExecutionComparisonPanel';

export { ModelRoutingDecisionDetails } from '../modelRouting/ModelRoutingDecisionDetails';

export { FinalResponseCard } from '../execution/FinalResponseCard';

type TestSidebarProps = {
  appendMemoryFlag?: (
    inputs: Record<string, any> | FormData,
  ) => Record<string, any> | FormData;
};

const STREAM_IDLE_TIMEOUT_MS = 60_000;
const TEST_SIDEBAR_DEFAULT_WIDTH = 480;
const TEST_SIDEBAR_MIN_WIDTH = 380;
const TEST_SIDEBAR_MAX_WIDTH = 640;
const TEST_SIDEBAR_VIEWPORT_GUTTER = 24;
const TEST_SIDEBAR_MIN_CANVAS_WIDTH = 420;
const TEST_SIDEBAR_KEYBOARD_STEP = 20;
const TEST_RUN_QUERY_KEY = 'testRun';
const TEST_NODE_QUERY_KEY = 'testNode';

type PreflightStatus = 'idle' | 'validating' | 'saving';

export const TEST_INPUT_CLASS_NAME =
  'w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-100 dark:placeholder:text-gray-500';
const testTextAreaClassName = `${TEST_INPUT_CLASS_NAME} min-h-[100px]`;
const testJsonTextAreaClassName = `${TEST_INPUT_CLASS_NAME} min-h-[200px] font-mono text-sm`;

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

const cloneDraft = (value: WorkflowDraftRequest): WorkflowDraftRequest => {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as WorkflowDraftRequest;
};

const getHttpStatus = (error: unknown) => {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { status?: unknown } }).response?.status ===
      'number'
  ) {
    return (error as { response: { status: number } }).response.status;
  }
  return undefined;
};

const readTestExecutionLocation = () => {
  if (typeof window === 'undefined') {
    return { runId: null, nodeId: null };
  }

  const searchParams = new URLSearchParams(window.location.search);
  return {
    runId: searchParams.get(TEST_RUN_QUERY_KEY),
    nodeId: searchParams.get(TEST_NODE_QUERY_KEY),
  };
};

const replaceTestExecutionLocation = (
  runId: string | null,
  nodeId: string | null,
) => {
  if (typeof window === 'undefined') return;

  const url = new URL(window.location.href);
  if (runId) {
    url.searchParams.set(TEST_RUN_QUERY_KEY, runId);
  } else {
    url.searchParams.delete(TEST_RUN_QUERY_KEY);
  }
  if (nodeId) {
    url.searchParams.set(TEST_NODE_QUERY_KEY, nodeId);
  } else {
    url.searchParams.delete(TEST_NODE_QUERY_KEY);
  }
  window.history.replaceState(window.history.state, '', url);
};

export function TestSidebar({ appendMemoryFlag }: TestSidebarProps) {
  const {
    isTestPanelOpen,
    toggleTestPanel,
    nodes,
    activeWorkflowId,
    setNodes,
    updateNodeData,
    workflowAccess,
    edges,
    features,
    envVariables,
    runtimeVariables,
    testExecutionStatus,
    testExecutionRunId,
    testSelectedNodeId,
    testExecutionStartedAt,
    testExecutionFinishedAt,
    testExecutionResult,
    testNodeResults,
    testExecutionError,
    currentExecutingNodeId,
    isTestUploading,
    beginTestExecution,
    setTestUploading,
    setCurrentExecutingNode,
    setTestExecutionRunId,
    selectTestExecutionNode,
    addTestNodeResult,
    finishTestExecution,
    failTestExecution,
    restoreTestExecution,
    resetTestExecution,
  } = useWorkflowStore();
  const { setCenter, getViewport } = useReactFlow();

  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [preflightStatus, setPreflightStatus] =
    useState<PreflightStatus>('idle');
  const [validationErrors, setValidationErrors] = useState<
    GraphValidationIssue[]
  >([]);
  const [isComparisonMode, setIsComparisonMode] = useState(false);
  const [comparisonBaselineRunId, setComparisonBaselineRunId] = useState<
    string | null
  >(null);
  const [localSelectedTestNodeId, setLocalSelectedTestNodeId] = useState<
    string | null
  >(null);
  const [testSidebarWidth, setTestSidebarWidth] = useState(
    TEST_SIDEBAR_DEFAULT_WIDTH,
  );
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === 'undefined' ? 0 : window.innerWidth,
  );
  const clearResizeListenersRef = React.useRef<(() => void) | null>(null);
  const nodeStartedAtRef = React.useRef<Record<string, number>>({});
  const restoredRunRef = React.useRef<string | null>(null);
  const isExecuting = testExecutionStatus === 'running';
  const selectedTestNodeId = testSelectedNodeId ?? localSelectedTestNodeId;
  const selectExecutionNode = (nodeId: string | null) => {
    setLocalSelectedTestNodeId(nodeId);
    selectTestExecutionNode?.(nodeId);
  };
  const isPreparing =
    preflightStatus === 'validating' || preflightStatus === 'saving';
  const executionResult = testExecutionResult;
  const hasExecutionResult =
    executionResult !== null && executionResult !== undefined;
  const nodeResults = testNodeResults;
  const error = testExecutionError;
  const canExecute = workflowAccess?.can_execute !== false;
  const isExecuteActionDisabled = isTestExecutionActionDisabled({
    isExecuting,
    isUploading: isTestUploading,
    isPreparing,
    canExecute,
  });

  const maxTestSidebarWidth = Math.min(
    TEST_SIDEBAR_MAX_WIDTH,
    Math.max(0, viewportWidth - TEST_SIDEBAR_VIEWPORT_GUTTER),
  );
  const minTestSidebarWidth = Math.min(
    TEST_SIDEBAR_MIN_WIDTH,
    maxTestSidebarWidth,
  );
  const renderedTestSidebarWidth = clamp(
    testSidebarWidth,
    minTestSidebarWidth,
    maxTestSidebarWidth,
  );
  const canResizeTestSidebar =
    viewportWidth >= TEST_SIDEBAR_MIN_WIDTH + TEST_SIDEBAR_MIN_CANVAS_WIDTH;

  useEffect(() => {
    const syncViewportWidth = () => setViewportWidth(window.innerWidth);

    window.addEventListener('resize', syncViewportWidth);
    return () => window.removeEventListener('resize', syncViewportWidth);
  }, []);

  useEffect(
    () => () => {
      clearResizeListenersRef.current?.();
    },
    [],
  );

  useEffect(() => {
    const { runId, nodeId } = readTestExecutionLocation();
    if (!runId || !activeWorkflowId || nodes.length === 0) return;

    if (testExecutionRunId === runId) {
      if (
        nodeId &&
        testNodeResults.some((result) => result.nodeId === nodeId) &&
        nodeId !== testSelectedNodeId
      ) {
        setLocalSelectedTestNodeId(nodeId);
        selectTestExecutionNode?.(nodeId);
      }
      return;
    }

    const restoreKey = `${activeWorkflowId}:${runId}`;
    if (restoredRunRef.current === restoreKey) return;
    restoredRunRef.current = restoreKey;

    let cancelled = false;
    workflowApi
      .getWorkflowRun(activeWorkflowId, runId)
      .then((run) => {
        if (cancelled) return;
        const restored = restoreTestExecutionFromWorkflowRun(run, nodes);
        restoreTestExecution(restored);
        if (
          nodeId &&
          restored.nodeResults.some((result) => result.nodeId === nodeId)
        ) {
          setLocalSelectedTestNodeId(nodeId);
          selectTestExecutionNode?.(nodeId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          toast.error('이전 테스트 실행 기록을 불러오지 못했습니다.');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeWorkflowId,
    nodes,
    restoreTestExecution,
    selectTestExecutionNode,
    testExecutionRunId,
    testNodeResults,
    testSelectedNodeId,
  ]);

  const outputLabelByNodeId = useMemo(() => {
    const labelMap = new Map<string, Map<string, string>>();

    for (const node of nodes) {
      const outputLabels = new Map<string, string>();
      for (const output of getNodeOutputVariables(node)) {
        outputLabels.set(output.key, output.label || output.key);
        if (output.outputId) {
          outputLabels.set(output.outputId, output.label || output.key);
        }
      }
      labelMap.set(node.id, outputLabels);
    }

    return labelMap;
  }, [nodes]);

  const getNodeDisplayName = (nodeId: string) => {
    const node = nodes.find((item) => item.id === nodeId);
    const title = String(node?.data?.title || '').trim();
    return title || nodeId;
  };

  const getOutputDisplayKey = (nodeId: string, key: string) => {
    const label = outputLabelByNodeId.get(nodeId)?.get(key)?.trim();
    if (!label || label === key) return key;
    return `${label} (${key})`;
  };

  const stringifyOutputForDisplay = (nodeId: string, output: unknown) => {
    if (!output || typeof output !== 'object' || Array.isArray(output)) {
      return JSON.stringify(output, null, 2);
    }

    const displayOutput = Object.fromEntries(
      Object.entries(output as Record<string, unknown>).map(([key, value]) => [
        getOutputDisplayKey(nodeId, key),
        value,
      ]),
    );

    return JSON.stringify(displayOutput, null, 2);
  };

  // Start Node 찾기 및 변수 초기화
  const startNode = nodes.find(
    (n) =>
      n.type === 'startNode' ||
      n.type === 'webhookTrigger' ||
      n.type === 'scheduleTrigger',
  );

  let variables: WorkflowVariable[] = [];
  if (startNode?.type === 'startNode') {
    variables = (startNode.data as StartNodeData)?.variables || [];
  } else if (startNode?.type === 'webhookTrigger') {
    // Webhook의 경우 내부적으로만 사용, UI에서는 특별 처리
    variables = [
      {
        id: '__json_payload__',
        name: '__json_payload__',
        label: '웹훅 페이로드',
        type: 'paragraph',
        required: true,
        placeholder: '{"user": "john", "action": "signup"}',
      },
    ];
  }

  // 패널이 열릴 때 입력값 초기화 (실행 결과는 유지)
  useEffect(() => {
    if (!isTestPanelOpen) return;

    const timeout = window.setTimeout(() => {
      if (isTestPanelOpen) {
        const initial: Record<string, any> = {};
        variables.forEach((v) => {
          if (v.type === 'number') {
            initial[v.name] = 0;
          } else if (v.type === 'checkbox') {
            initial[v.name] = false;
          } else if (v.type === 'select') {
            initial[v.name] = v.options?.[0]?.value || '';
          } else if (v.type === 'file') {
            initial[v.name] = null;
          } else {
            initial[v.name] = '';
          }
        });

        // 웹훅의 경우 캡처된 데이터가 있으면 자동 채우기
        if (startNode?.type === 'webhookTrigger') {
          const data = startNode.data as any;
          if (data.captured_payload) {
            initial['__json_payload__'] = JSON.stringify(
              data.captured_payload,
              null,
              2,
            );
          }
        }

        setInputs(initial);
        setFiles({});
      }
    }, 0);

    return () => window.clearTimeout(timeout);
  }, [isTestPanelOpen]);

  if (!isTestPanelOpen) return null;

  const setClampedTestSidebarWidth = (width: number) => {
    setTestSidebarWidth(clamp(width, minTestSidebarWidth, maxTestSidebarWidth));
  };

  const handleTestSidebarResizeStart = (
    event: React.PointerEvent<HTMLDivElement>,
  ) => {
    if (!canResizeTestSidebar) return;

    event.preventDefault();
    clearResizeListenersRef.current?.();

    const startClientX = event.clientX;
    const startWidth = renderedTestSidebarWidth;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handlePointerMove = (moveEvent: PointerEvent) => {
      setClampedTestSidebarWidth(startWidth + startClientX - moveEvent.clientX);
    };
    const clearResizeListeners = () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', clearResizeListeners);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      clearResizeListenersRef.current = null;
    };

    clearResizeListenersRef.current = clearResizeListeners;
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', clearResizeListeners, { once: true });
  };

  const handleTestSidebarResizeKeyDown = (
    event: React.KeyboardEvent<HTMLDivElement>,
  ) => {
    if (!canResizeTestSidebar) return;

    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setClampedTestSidebarWidth(
        renderedTestSidebarWidth - TEST_SIDEBAR_KEYBOARD_STEP,
      );
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setClampedTestSidebarWidth(
        renderedTestSidebarWidth + TEST_SIDEBAR_KEYBOARD_STEP,
      );
    } else if (event.key === 'Home') {
      event.preventDefault();
      setClampedTestSidebarWidth(minTestSidebarWidth);
    } else if (event.key === 'End') {
      event.preventDefault();
      setClampedTestSidebarWidth(maxTestSidebarWidth);
    }
  };

  const handleChange = (name: string, value: any) => {
    setInputs((prev) => ({ ...prev, [name]: value }));
  };

  const buildObservability = (
    output: any,
    status: 'success' | 'failure' | 'running',
    latencyMs?: number,
    totalTokens?: number,
    totalCost?: number,
  ) => {
    return {
      status,
      model: output?.model,
      total_tokens: totalTokens ?? readTokenUsage(output),
      total_cost: totalCost ?? readCost(output),
      latency_ms: latencyMs,
    };
  };

  const resultOutputByNodeId = new Map<string, unknown>();
  if (
    executionResult &&
    typeof executionResult === 'object' &&
    !Array.isArray(executionResult)
  ) {
    for (const [nodeId, output] of Object.entries(
      executionResult as Record<string, unknown>,
    )) {
      resultOutputByNodeId.set(nodeId, output);
    }
  }
  // 스트림의 node_finish 결과에는 routing/usage 메타데이터가 더 풍부하므로
  // workflow 최종 결과의 축약 output보다 우선합니다.
  for (const result of nodeResults) {
    resultOutputByNodeId.set(result.nodeId, result.output);
  }

  const nodeResultById = new Map(
    nodeResults.map((result) => [result.nodeId, result]),
  );
  const executionNodeIds = new Set([
    ...nodes.map((node) => node.id),
    ...nodeResults.map((result) => result.nodeId),
  ]);
  const nodeExecutionSummaries = Array.from(executionNodeIds)
    .map((nodeId) => {
      const node = nodes.find((item) => item.id === nodeId);
      const storedResult = nodeResultById.get(nodeId);
      if (!node && !storedResult) return null;
      const data = node?.data as {
        title?: string;
        name?: string;
        status?: string;
        observability?: {
          status?: 'success' | 'failure' | 'running';
          total_tokens?: number;
          total_cost?: number;
          latency_ms?: number;
        };
      };
      const output = resultOutputByNodeId.get(nodeId);
      const status =
        currentExecutingNodeId === nodeId
          ? 'running'
          : storedResult?.status ||
            data.observability?.status ||
            data.status ||
            'idle';

      return {
        nodeId,
        nodeType: storedResult?.nodeType || node?.type || 'node',
        title:
          storedResult?.title ||
          data.title ||
          data.name ||
          getNodeDisplayName(nodeId),
        status,
        output,
        latencyMs: storedResult?.latencyMs ?? data.observability?.latency_ms,
        totalTokens:
          storedResult?.totalTokens ??
          data.observability?.total_tokens ??
          readTokenUsage(output),
        totalCost:
          storedResult?.totalCost ??
          data.observability?.total_cost ??
          readCost(output),
      };
    })
    .filter(
      (summary): summary is NonNullable<typeof summary> => summary !== null,
    )
    .filter((summary) =>
      ['running', 'success', 'failure'].includes(summary.status),
    );

  const workflowExecutionSummary = summarizeWorkflowExecution(
    nodeExecutionSummaries.map((summary) => ({
      nodeId: summary.nodeId,
      status: summary.status as 'running' | 'success' | 'failure',
      latencyMs: summary.latencyMs,
      totalTokens: summary.totalTokens,
      cost: summary.totalCost,
    })),
    testExecutionStartedAt,
    testExecutionFinishedAt,
    executionResult as
      | {
          duration?: unknown;
          total_tokens?: unknown;
          total_cost?: unknown;
        }
      | null
      | undefined,
  );
  const finalResponsePreview = getFinalResponsePreview({
    workflowResult: executionResult,
    nodeResults,
    nodes,
  });
  const showFinalResponseCard = shouldShowFinalResponseCard({
    hasExecutionResult,
    error,
  });
  const selectedNodeExecutionSummary = selectedTestNodeId
    ? nodeExecutionSummaries.find(
        (summary) => summary.nodeId === selectedTestNodeId,
      )
    : null;

  const renderNodeExecutionSummary = (
    summary: (typeof nodeExecutionSummaries)[number],
  ) => {
    const isRunning = summary.status === 'running';
    const isFailure = summary.status === 'failure';
    const statusLabel = isRunning ? '실행 중' : isFailure ? '실패' : '성공';
    const statusClassName = isRunning
      ? 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300'
      : isFailure
        ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300'
        : 'border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-300';
    const StatusIcon = isRunning
      ? Loader2
      : isFailure
        ? AlertCircle
        : CheckCircle;

    return (
      <div
        key={summary.nodeId}
        className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700"
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
              {summary.title}
            </div>
            <div className="mt-1 text-xs text-gray-500">{summary.nodeType}</div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold ${statusClassName}`}
            >
              <StatusIcon
                className={`h-3.5 w-3.5 ${isRunning ? 'animate-spin' : ''}`}
              />
              {statusLabel}
            </span>
            {!isRunning ? (
              <button
                type="button"
                aria-label={`${summary.title} 상세 보기`}
                title="상세 보기"
                onClick={() => {
                  selectExecutionNode(summary.nodeId);
                  replaceTestExecutionLocation(
                    testExecutionRunId,
                    summary.nodeId,
                  );
                }}
                className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-500 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:border-blue-800 dark:hover:bg-blue-950/30"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </div>
        <dl className="grid grid-cols-3 gap-2 bg-white px-4 py-3 text-xs dark:bg-gray-900">
          <div>
            <dt className="flex items-center gap-1 text-gray-500">
              <Clock className="h-3.5 w-3.5" />
              시간
            </dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {formatLatency(summary.latencyMs)}
            </dd>
          </div>
          <div>
            <dt className="flex items-center gap-1 text-gray-500">
              <Coins className="h-3.5 w-3.5" />
              비용
            </dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {formatCost(summary.totalCost)}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">토큰</dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {formatTokens(summary.totalTokens)}
            </dd>
          </div>
        </dl>
      </div>
    );
  };

  const renderNodeExecutionDetail = (
    summary: (typeof nodeExecutionSummaries)[number],
  ) => {
    const hasRoutingTrace =
      summary.nodeType === 'llmNode' &&
      typeof summary.output === 'object' &&
      summary.output !== null &&
      !Array.isArray(summary.output) &&
      typeof (summary.output as { metadata?: { model_routing?: unknown } })
        .metadata?.model_routing === 'object';

    return (
      <div className="space-y-5">
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="테스트 결과로 돌아가기"
            title="테스트 결과로 돌아가기"
            onClick={() => {
              selectExecutionNode(null);
              replaceTestExecutionLocation(testExecutionRunId, null);
            }}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {summary.title} 실행 상세
          </h3>
        </div>

        <dl className="grid grid-cols-3 gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 text-xs dark:border-gray-700 dark:bg-gray-800/60">
          <div>
            <dt className="text-gray-500">상태</dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {summary.status === 'failure' ? '실패' : '성공'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">실행 시간</dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {formatLatency(summary.latencyMs)}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">비용</dt>
            <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
              {formatCost(summary.totalCost)}
            </dd>
          </div>
        </dl>

        <section>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            출력 데이터
          </h4>
          <pre className="mt-2 max-h-[420px] overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-4 text-xs leading-5 text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
            {stringifyOutputForDisplay(summary.nodeId, summary.output)}
          </pre>
        </section>

        {hasRoutingTrace ? (
          <div className="space-y-3">
            <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs leading-relaxed text-blue-800 dark:border-blue-900 dark:bg-blue-950/20 dark:text-blue-200">
              이 테스트 실행은 자동 라우팅 정책의 학습 및 갱신 횟수에 포함되지
              않습니다.
            </p>
            <ModelRoutingDecisionDetails output={summary.output} />
          </div>
        ) : null}
      </div>
    );
  };

  const renderExecutionTotalSummary = () => (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-900/20">
      <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100">
        최종 실행 요약
      </h3>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div>
          <dt className="text-blue-700 dark:text-blue-300">서버 실행</dt>
          <dd className="mt-1 font-semibold text-blue-950 dark:text-blue-50">
            {formatLatency(workflowExecutionSummary.serverDurationMs)}
          </dd>
        </div>
        <div>
          <dt className="text-blue-700 dark:text-blue-300">화면 완료</dt>
          <dd className="mt-1 font-semibold text-blue-950 dark:text-blue-50">
            {formatLatency(workflowExecutionSummary.screenCompletionDurationMs)}
          </dd>
        </div>
        <div>
          <dt className="text-blue-700 dark:text-blue-300">전체 비용</dt>
          <dd className="mt-1 font-semibold text-blue-950 dark:text-blue-50">
            {formatCost(workflowExecutionSummary.totalCost)}
          </dd>
        </div>
        <div>
          <dt className="text-blue-700 dark:text-blue-300">전체 토큰</dt>
          <dd className="mt-1 font-semibold text-blue-950 dark:text-blue-50">
            {formatTokens(workflowExecutionSummary.totalTokens)}
          </dd>
        </div>
      </dl>
    </div>
  );

  const handleExecute = async () => {
    if (!activeWorkflowId) return;
    if (!canExecute) {
      failTestExecution('현재 권한으로는 실행할 수 없습니다.');
      return;
    }

    selectExecutionNode(null);
    replaceTestExecutionLocation(null, null);
    setValidationErrors([]);
    setPreflightStatus('validating');

    try {
      const hasFiles = Object.values(files).some((file) => file !== null);
      let finalInputs: Record<string, any> = { ...inputs };

      // Webhook인 경우 JSON 파싱
      if (startNode?.type === 'webhookTrigger') {
        try {
          const rawJson = inputs['__json_payload__'];
          finalInputs = JSON.parse(rawJson);
        } catch {
          toast.error('유효하지 않은 JSON 형식입니다.');
          failTestExecution('JSON 파싱 실패');
          setPreflightStatus('idle');
          return;
        }
      }

      const graphSnapshot = cloneDraft({
        nodes,
        edges,
        viewport: getViewport(),
        features,
        envVariables,
        runtimeVariables,
      });
      const validation = validateWorkflowGraph(graphSnapshot);

      if (!validation.ok) {
        setValidationErrors(validation.errors);
        failTestExecution(
          '워크플로우 연결에 문제가 있어 테스트를 실행하지 않았습니다.',
        );
        toast.error('실행 전 그래프 검증 실패');
        setPreflightStatus('idle');
        return;
      }

      setPreflightStatus('saving');

      try {
        await workflowApi.syncDraftWorkflow(
          activeWorkflowId,
          buildWorkflowDraftPayload(graphSnapshot, graphSnapshot.viewport),
        );
      } catch (saveError) {
        const status = getHttpStatus(saveError);
        const message =
          status === 401
            ? '로그인이 만료되어 현재 워크플로우를 저장하지 못했습니다.'
            : '현재 워크플로우 저장에 실패해서 테스트를 실행하지 않았습니다.';
        failTestExecution(message);
        toast.error('저장 실패');
        setPreflightStatus('idle');
        return;
      }

      setPreflightStatus('idle');
      beginTestExecution();

      // 파일 업로드 처리
      if (hasFiles) {
        setTestUploading(true);
        try {
          for (const [key, file] of Object.entries(files)) {
            if (file) {
              const presignedData = await knowledgeApi.getPresignedUploadUrl(
                file.name,
                file.type || 'application/octet-stream',
              );

              await knowledgeApi.uploadToS3(
                presignedData.upload_url,
                file,
                file.type || 'application/octet-stream',
              );

              const s3Url = presignedData.upload_url.split('?')[0];
              finalInputs[key] = s3Url;
            }
          }
        } catch (uploadError: any) {
          toast.error(`파일 업로드 실패: ${uploadError.message}`);
          failTestExecution('파일 업로드 실패');
          return;
        }
        setTestUploading(false);
      }

      // 1. 초기화: 모든 노드 상태 초기화
      const initialNodes = nodes.map((node) => ({
        ...node,
        data: { ...node.data, status: 'idle', observability: undefined },
      })) as unknown as any[];
      setNodes(initialNodes);

      let finalResult: any = null;

      // 2. 스트리밍 실행 (기억모드 플래그 적용)
      const inputsWithMemory = appendMemoryFlag
        ? appendMemoryFlag(finalInputs)
        : finalInputs;
      const abortController = new AbortController();
      let streamIdleTimeout: ReturnType<typeof setTimeout> | null = null;
      let streamTimedOut = false;
      const resetStreamIdleTimeout = () => {
        if (streamIdleTimeout) clearTimeout(streamIdleTimeout);
        streamIdleTimeout = setTimeout(() => {
          streamTimedOut = true;
          abortController.abort();
        }, STREAM_IDLE_TIMEOUT_MS);
      };

      try {
        resetStreamIdleTimeout();
        await workflowApi.executeWorkflowStream(
          activeWorkflowId,
          inputsWithMemory as Record<string, any>,
          async (event) => {
            resetStreamIdleTimeout();
            // 시각적 피드백을 위한 지연
            await new Promise((resolve) => setTimeout(resolve, 500));

            const { type, data } = event;

            if (type === 'workflow_start') {
              if (typeof data?.run_id === 'string') {
                setTestExecutionRunId(data.run_id);
                replaceTestExecutionLocation(data.run_id, null);
              }
            } else if (type === 'node_start') {
              nodeStartedAtRef.current[data.node_id] = performance.now();
              setCurrentExecutingNode(data.node_id);
              updateNodeData(data.node_id, {
                status: 'running',
                observability: buildObservability(null, 'running'),
              });

              // 실행 중인 노드로 화면 중심 이동 및 줌인
              const latestNodes = useWorkflowStore.getState().nodes;
              const currentNode = latestNodes.find(
                (n) => n.id === data.node_id,
              );
              if (currentNode) {
                setCenter(
                  currentNode.position.x +
                    (currentNode.measured?.width || 200) / 2,
                  currentNode.position.y +
                    (currentNode.measured?.height || 100) / 2,
                  { zoom: 1.2, duration: 800 },
                );
              }
            } else if (type === 'node_finish') {
              const startedAt = nodeStartedAtRef.current[data.node_id];
              const fallbackLatencyMs = startedAt
                ? Math.round(performance.now() - startedAt)
                : undefined;
              const metrics = readNodeFinishExecutionSummary(
                data,
                fallbackLatencyMs,
              );
              updateNodeData(data.node_id, {
                status: 'success',
                observability: buildObservability(
                  data.output,
                  'success',
                  metrics.latencyMs,
                  metrics.totalTokens,
                  metrics.totalCost,
                ),
              });

              // 노드 실행 완료 토스트

              // 노드 결과 누적
              addTestNodeResult({
                nodeId: data.node_id,
                nodeType: data.node_type,
                output: data.output,
                title: getNodeDisplayName(data.node_id),
                status: 'success',
                latencyMs: metrics.latencyMs,
                totalTokens: metrics.totalTokens,
                totalCost: metrics.totalCost,
              });
            } else if (type === 'workflow_finish') {
              finalResult = data;
            } else if (type === 'error') {
              if (data.node_id) {
                const startedAt = nodeStartedAtRef.current[data.node_id];
                const latencyMs = startedAt
                  ? Math.round(performance.now() - startedAt)
                  : undefined;
                updateNodeData(data.node_id, {
                  status: 'failure',
                  observability: buildObservability(null, 'failure', latencyMs),
                });
                addTestNodeResult({
                  nodeId: data.node_id,
                  nodeType: data.node_type || 'node',
                  output: {},
                  title: getNodeDisplayName(data.node_id),
                  status: 'failure',
                  latencyMs,
                });
              }
              toast.error(`모듈 실행 실패: ${data.message}`);
              throw new Error(data.message);
            }
          },
          {
            signal: abortController.signal,
            graphSnapshot,
            // 테스트 결과는 운영 정책 학습에 포함하지 않지만, 현재 draft와
            // 같은 활성 배포 정책은 실제 실행처럼 평가해 확인한다.
            useActiveDeploymentRoutingPolicy: true,
          },
        );
      } catch (streamError) {
        if (streamTimedOut) {
          throw new Error(
            '실행 이벤트가 60초 이상 도착하지 않았습니다. 실행 엔진 또는 Redis 스트림 상태를 확인해주세요.',
          );
        }
        throw streamError;
      } finally {
        if (streamIdleTimeout) clearTimeout(streamIdleTimeout);
      }

      // 최종 결과 저장
      if (finalResult) {
        finishTestExecution(finalResult);
      } else {
        finishTestExecution({});
      }
    } catch (err: any) {
      console.error('Execution failed:', err);
      const budgetExceeded = isBudgetExceededError(err);
      const message = budgetExceeded
        ? BUDGET_EXCEEDED_MESSAGE
        : deploymentApiErrorMessage(
            err,
            err.message || '실행 중 오류가 발생했습니다.',
          );
      failTestExecution(message);
      toast.error(message);
    } finally {
      setTestUploading(false);
      setPreflightStatus('idle');
    }
  };

  const handleReset = () => {
    selectExecutionNode(null);
    replaceTestExecutionLocation(null, null);
    setValidationErrors([]);
    setPreflightStatus('idle');
    resetTestExecution();
  };

  const getVariableDisplayName = (variable: WorkflowVariable) =>
    variable.label?.trim() || variable.name;

  return (
    <div
      data-testid="test-execution-sidebar"
      className="absolute top-18 right-2 bottom-2 z-50 flex min-w-0 flex-col rounded-xl border-l border-gray-200 bg-white shadow-xl animate-in slide-in-from-right duration-200 dark:border-gray-800 dark:bg-gray-900"
      style={{ width: `${renderedTestSidebarWidth}px` }}
    >
      {canResizeTestSidebar && (
        <div
          role="separator"
          aria-label="테스트 실행 패널 너비 조절"
          aria-orientation="vertical"
          aria-valuemin={minTestSidebarWidth}
          aria-valuemax={maxTestSidebarWidth}
          aria-valuenow={renderedTestSidebarWidth}
          tabIndex={0}
          onPointerDown={handleTestSidebarResizeStart}
          onKeyDown={handleTestSidebarResizeKeyDown}
          className="group absolute inset-y-0 -left-1 z-10 w-3 touch-none cursor-col-resize outline-none"
        >
          <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent transition-colors group-hover:bg-blue-300 group-focus-visible:bg-blue-500" />
        </div>
      )}
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-4 dark:border-gray-800">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
            <Play className="h-5 w-5 text-blue-600" />
            테스트 실행
          </h2>
          <button
            onClick={toggleTestPanel}
            className="rounded-full p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-3 grid grid-cols-2 rounded-lg border border-gray-200 bg-gray-50 p-1 dark:border-gray-700 dark:bg-gray-800">
          <button
            type="button"
            aria-pressed={!isComparisonMode}
            onClick={() => {
              setIsComparisonMode(false);
              setComparisonBaselineRunId(null);
            }}
            className={`rounded-md px-3 py-2 text-xs font-semibold transition-colors ${
              !isComparisonMode
                ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-900 dark:text-gray-100'
                : 'text-gray-500 hover:text-gray-800 dark:text-gray-300'
            }`}
          >
            단일 결과
          </button>
          <button
            type="button"
            aria-pressed={isComparisonMode}
            onClick={() => {
              setIsComparisonMode(true);
              setClampedTestSidebarWidth(maxTestSidebarWidth);
            }}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold transition-colors ${
              isComparisonMode
                ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-300'
                : 'text-gray-500 hover:text-gray-800 dark:text-gray-300'
            }`}
          >
            <GitCompareArrows className="h-3.5 w-3.5" /> 실행 비교
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isComparisonMode && activeWorkflowId ? (
          <ExecutionComparisonPanel
            workflowId={activeWorkflowId}
            nodes={nodes}
            baselineRunId={comparisonBaselineRunId}
            currentRunId={testExecutionRunId}
            currentExecutionError={testExecutionError}
            onBaselineRunIdChange={setComparisonBaselineRunId}
          />
        ) : null}
        {isExecuting ? (
          /* Execution Progress - Show node results as they come in */
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-blue-600 mb-4">
              <Loader2 className="w-5 h-5 animate-spin" />
              <h3 className="text-sm font-medium">테스트 실행 중...</h3>
            </div>
            {nodeExecutionSummaries.length > 0 ? (
              nodeExecutionSummaries.map(renderNodeExecutionSummary)
            ) : (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
                <div className="flex items-center gap-2 font-medium">
                  <Loader2 className="h-4 w-4 animate-spin" />첫 노드 실행
                  결과를 기다리는 중입니다.
                </div>
              </div>
            )}
          </div>
        ) : !hasExecutionResult && !error ? (
          /* Input Form */
          <div className="space-y-6">
            {isPreparing && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
                <div className="flex items-center gap-2 font-medium">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {preflightStatus === 'validating'
                    ? '워크플로우 연결을 검증하는 중입니다.'
                    : '현재 워크플로우를 저장하는 중입니다.'}
                </div>
              </div>
            )}
            <div>
              <h3 className="text-sm font-medium text-gray-900 mb-4 dark:text-gray-200">
                입력 변수 설정
              </h3>

              {variables.length === 0 ? (
                <div className="text-center py-8 text-gray-500 bg-gray-50 rounded-lg dark:bg-gray-800">
                  입력 변수가 없는 모듈입니다.
                  <br />
                  바로 실행할 수 있습니다.
                </div>
              ) : startNode?.type === 'webhookTrigger' ? (
                /* 웹훅 전용 UI */
                <div className="space-y-3">
                  {!(startNode.data as any).captured_payload && (
                    <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg dark:bg-blue-900/20 dark:border-blue-800">
                      <p className="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">
                        캡처된 데이터가 없습니다. 웹훅 트리거의{' '}
                        <strong>[캡처 시작]</strong> 기능을 사용하면 실제
                        데이터가 테스트 입력에 자동으로 채워집니다.
                      </p>
                    </div>
                  )}

                  {(startNode.data as any).captured_payload && (
                    <div className="p-3 bg-green-50 border border-green-200 rounded-lg dark:bg-green-900/20 dark:border-green-800">
                      <p className="text-xs text-green-700 dark:text-green-300 leading-relaxed">
                        ✅ 최신 데이터가 자동으로 로드되었습니다. 캡처된
                        Payload를 확인하고 바로 테스트를 진행해 보세요.
                      </p>
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    {(startNode.data as any).captured_payload && (
                      <span className="text-xs text-green-600 dark:text-green-400">
                        {/* ✓ 캡처된 데이터 사용 중 (메시지로 대체됨) */}
                      </span>
                    )}
                  </div>

                  <div>
                    <textarea
                      value={inputs['__json_payload__'] || ''}
                      onChange={(e) =>
                        handleChange('__json_payload__', e.target.value)
                      }
                      className={testJsonTextAreaClassName}
                      placeholder='webhook payload: {"user": "john", "action": "signup"}'
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {variables.map((variable) => (
                    <div key={variable.id}>
                      {variable.type === 'checkbox' ? (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={inputs[variable.name] || false}
                            onChange={(e) =>
                              handleChange(variable.name, e.target.checked)
                            }
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            {getVariableDisplayName(variable)}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </span>
                        </label>
                      ) : variable.type === 'select' ? (
                        <>
                          <label className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-300">
                            {getVariableDisplayName(variable)}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </label>
                          <select
                            value={inputs[variable.name] || ''}
                            onChange={(e) =>
                              handleChange(variable.name, e.target.value)
                            }
                            className={TEST_INPUT_CLASS_NAME}
                          >
                            {variable.options?.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </>
                      ) : variable.type === 'file' ? (
                        <>
                          <label className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-300">
                            {getVariableDisplayName(variable)}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </label>
                          <input
                            type="file"
                            onChange={(e) => {
                              const file = e.target.files?.[0] || null;
                              setFiles((prev) => ({
                                ...prev,
                                [variable.name]: file,
                              }));
                            }}
                            className={TEST_INPUT_CLASS_NAME}
                          />
                        </>
                      ) : (
                        <>
                          <label className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-300">
                            {getVariableDisplayName(variable)}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </label>
                          {variable.type === 'paragraph' ? (
                            <textarea
                              value={inputs[variable.name] || ''}
                              onChange={(e) =>
                                handleChange(variable.name, e.target.value)
                              }
                              className={testTextAreaClassName}
                              placeholder={variable.placeholder}
                            />
                          ) : (
                            <input
                              type={
                                variable.type === 'number' ? 'number' : 'text'
                              }
                              value={inputs[variable.name] || ''}
                              onChange={(e) =>
                                handleChange(
                                  variable.name,
                                  variable.type === 'number'
                                    ? Number(e.target.value)
                                    : e.target.value,
                                )
                              }
                              className={TEST_INPUT_CLASS_NAME}
                              placeholder={variable.placeholder}
                            />
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : isComparisonMode ? null : (
          /* Execution Result */
          <div className="space-y-6">
            {error ? (
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-medium text-red-800">
                    실행 실패
                  </h3>
                  <p className="text-sm text-red-600 mt-1">{error}</p>
                  {validationErrors.length > 0 && (
                    <ul className="mt-3 space-y-1 text-sm text-red-700">
                      {validationErrors.slice(0, 5).map((issue, index) => (
                        <li key={`${issue.code}-${issue.edgeId || index}`}>
                          - {formatGraphIssue(issue)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-medium text-green-800">
                    실행 성공
                  </h3>
                  <p className="text-sm text-green-600 mt-1">
                    모듈이 성공적으로 실행되었습니다.
                  </p>
                </div>
              </div>
            )}

            {hasExecutionResult &&
              (selectedNodeExecutionSummary ? (
                renderNodeExecutionDetail(selectedNodeExecutionSummary)
              ) : (
                <div className="space-y-4">
                  {showFinalResponseCard && (
                    <FinalResponseCard preview={finalResponsePreview} />
                  )}
                  {renderExecutionTotalSummary()}
                  <h3 className="text-sm font-medium text-gray-900 mb-3 dark:text-gray-200">
                    노드별 실행 결과
                  </h3>
                  <div className="space-y-3">
                    {nodeExecutionSummaries.length > 0 ? (
                      nodeExecutionSummaries.map(renderNodeExecutionSummary)
                    ) : (
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800">
                        노드별 실행 결과가 없습니다.
                      </div>
                    )}
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 dark:bg-gray-900 dark:border-gray-800">
        {!hasExecutionResult && !error ? (
          <div>
            <button
              onClick={handleExecute}
              disabled={isExecuteActionDisabled}
              className="px-3 py-2 text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2 text-sm font-medium"
            >
              {isExecuting || isTestUploading || isPreparing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {isTestUploading
                    ? '파일 업로드 중...'
                    : preflightStatus === 'validating'
                      ? '검증 중...'
                      : preflightStatus === 'saving'
                        ? '저장 중...'
                        : '테스트 실행 중...'}
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  {canExecute ? '테스트 실행하기' : '테스트 실행 권한 없음'}
                </>
              )}
            </button>
          </div>
        ) : (
          <button
            onClick={handleReset}
            className="w-full px-4 py-2 text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 rounded-lg transition-colors flex items-center justify-center gap-2 font-medium dark:bg-gray-800 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            <RefreshCw className="w-4 h-4" />
            다시 테스트하기
          </button>
        )}
      </div>
    </div>
  );
}
