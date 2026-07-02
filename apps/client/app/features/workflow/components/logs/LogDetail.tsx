import { format } from 'date-fns';
import { JsonDataDisplay } from './shared/JsonDataDisplay';
import { ko } from 'date-fns/locale';
import {
  LLMTrace,
  WorkflowRun,
  WorkflowNodeRun,
} from '@/app/features/workflow/types/Api';
import {
  CheckCircle2,
  XCircle,
  Clock,
  BrainCircuit,
  PlayCircle,
  AlertCircle,
  Upload,
  Download,
  Copy,
  Check,
} from 'lucide-react';
import { useState, useRef, useEffect, useMemo } from 'react';
import { LogExecutionPath } from './detail-components/LogExecutionPath';
import { LogTokenAnalysis } from './detail-components/LogTokenAnalysis';
import { getNodeDisplayInfo } from './shared/nodeDisplayInfo';
import { getNodeDuration } from './shared/nodeUtils';
import { CollapsibleSection } from './shared/CollapsibleSection';
import { NodeOptionsDisplay } from './shared/NodeOptionsDisplay';
import { workflowApi } from '../../api/workflowApi';

interface LogDetailProps {
  run: WorkflowRun;
  onCompareClick?: () => void;
  compactMode?: boolean;
}

const FINAL_OUTPUT_NODE_TYPES = [
  'answerNode',
  'slackPostNode',
  'templateNode',
  'llmNode',
];

const INPUT_FIRST_FINAL_NODE_TYPES = ['slackPostNode'];

const PREFERRED_TEXT_KEYS = [
  'answer_text',
  'answer',
  'text',
  'message',
  'content',
  'response',
  'result',
  'output',
  'sanitized_text',
];

const getNodeSortTime = (node: WorkflowNodeRun) =>
  new Date(node.finished_at || node.started_at).getTime();

const extractTextValue = (
  value: any,
  depth = 0,
  allowDirectString = true,
): string | null => {
  if (value === null || value === undefined || depth > 5) return null;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return allowDirectString && trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value !== 'object') return null;

  for (const key of PREFERRED_TEXT_KEYS) {
    const child = value[key];
    const text = extractTextValue(child, depth + 1, true);
    if (text) return text;
  }

  const values = Array.isArray(value) ? value : Object.values(value);
  for (const child of values) {
    if (child === null || typeof child !== 'object') continue;
    const text = extractTextValue(child, depth + 1, false);
    if (text) return text;
  }

  return null;
};

const findPreferredResultNode = (nodeRuns: WorkflowNodeRun[] = []) => {
  const sortedNodes = [...nodeRuns].sort(
    (a, b) => getNodeSortTime(a) - getNodeSortTime(b),
  );
  const successfulNodes = sortedNodes.filter(
    (node) => node.status === 'success',
  );

  return (
    [...successfulNodes]
      .reverse()
      .find((node) => FINAL_OUTPUT_NODE_TYPES.includes(node.node_type)) ||
    successfulNodes.at(-1) ||
    sortedNodes.at(-1) ||
    null
  );
};

const findFinalOutputSummary = (run: WorkflowRun) => {
  const preferredNode = findPreferredResultNode(run.node_runs || []);
  const nodeOutputText = preferredNode
    ? INPUT_FIRST_FINAL_NODE_TYPES.includes(preferredNode.node_type)
      ? extractTextValue(preferredNode.inputs) ||
        extractTextValue(preferredNode.outputs)
      : extractTextValue(preferredNode.outputs) ||
        extractTextValue(preferredNode.inputs)
    : null;
  const runOutputText = extractTextValue(run.outputs);
  const text = nodeOutputText || runOutputText;

  if (!text) return null;

  return {
    text,
    node: preferredNode,
  };
};

const FinalOutputSummary = ({
  text,
  node,
  onNodeSelect,
}: {
  text: string;
  node: WorkflowNodeRun | null;
  onNodeSelect: (nodeId: string) => void;
}) => {
  const [copied, setCopied] = useState(false);
  const displayInfo = node ? getNodeDisplayInfo(node.node_type) : null;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <section className="mb-6 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-blue-950">최종 응답</h3>
          <p className="mt-1 text-xs text-blue-700">
            시연 결과를 바로 확인할 수 있도록 마지막 응답 값을 먼저 보여줍니다.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {node && displayInfo && (
            <button
              type="button"
              onClick={() => onNodeSelect(node.node_id)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${displayInfo.color} border border-blue-100 hover:border-blue-300`}
            >
              {displayInfo.icon}
              {displayInfo.label} 상세
            </button>
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? '복사됨' : '복사'}
          </button>
        </div>
      </div>
      <div className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg border border-blue-100 bg-white p-4 text-sm leading-6 text-gray-900 shadow-sm">
        {text}
      </div>
    </section>
  );
};

// 노드 설정 섹션 (NodeOptionsDisplay를 CollapsibleSection으로 감싸지 않고, 내부에서 직접 처리)
const NodeOptionsSection = ({
  nodeType,
  options,
}: {
  nodeType: string;
  options: Record<string, any>;
}) => {
  return (
    <CollapsibleSection
      title="실행 시점 노드 설정"
      icon={<span>⚙️</span>}
      bgColor="amber"
      defaultOpen={true}
    >
      <div className="pt-2">
        <NodeOptionsDisplay nodeType={nodeType} options={options} />
      </div>
    </CollapsibleSection>
  );
};

// 입력 데이터 섹션
const InputDataSection = ({ data }: { data: any }) => {
  return (
    <CollapsibleSection
      title="입력 데이터"
      icon={<Upload className="w-4 h-4" />}
      bgColor="gray"
      defaultOpen={true}
    >
      <div className="bg-white rounded border border-gray-200 p-4 max-h-96 overflow-y-auto">
        <JsonDataDisplay data={data} initiallyExpanded={true} />
      </div>
    </CollapsibleSection>
  );
};

// 출력 데이터 섹션
const OutputDataSection = ({ data }: { data: any }) => {
  return (
    <CollapsibleSection
      title="출력 데이터"
      icon={<Download className="w-4 h-4" />}
      bgColor="gray"
      defaultOpen={true}
    >
      <div className="bg-white rounded border border-gray-200 p-4 max-h-96 overflow-y-auto">
        <JsonDataDisplay data={data} initiallyExpanded={true} />
      </div>
    </CollapsibleSection>
  );
};

export const LogDetail = ({
  run,
  onCompareClick,
  compactMode = false,
}: LogDetailProps) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [llmTraces, setLlmTraces] = useState<LLMTrace[]>([]);
  const [llmTraceLoading, setLlmTraceLoading] = useState(false);
  const [llmTraceError, setLlmTraceError] = useState(false);
  const nodeRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const preferredResultNode = useMemo(
    () => findPreferredResultNode(run.node_runs || []),
    [run.node_runs],
  );
  const finalOutputSummary = useMemo(() => findFinalOutputSummary(run), [run]);

  const selectedNode =
    run.node_runs?.find((n) => n.node_id === selectedNodeId) ||
    preferredResultNode ||
    run.node_runs?.[0];

  // 선택된 노드가 변경될 때 해당 버튼으로 스크롤
  useEffect(() => {
    const currentNodeId = selectedNode?.node_id;
    if (currentNodeId) {
      const element = nodeRefs.current.get(currentNodeId);
      element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [selectedNode?.node_id]);

  useEffect(() => {
    let cancelled = false;

    const loadLlmTraces = async () => {
      try {
        setLlmTraces([]);
        setLlmTraceLoading(true);
        setLlmTraceError(false);
        const response = await workflowApi.getWorkflowRunLlmTraces(
          run.workflow_id,
          run.id,
          { limit: 500 },
        );
        if (cancelled) return;
        setLlmTraces(response.items);
      } catch {
        if (cancelled) return;
        setLlmTraces([]);
        setLlmTraceError(true);
      } finally {
        if (!cancelled) setLlmTraceLoading(false);
      }
    };

    loadLlmTraces();

    return () => {
      cancelled = true;
    };
  }, [run.id, run.workflow_id]);

  const hasTraceRows = llmTraces.length > 0;
  const { totalTokens, totalCost } = hasTraceRows
    ? llmTraces.reduce(
        (acc, trace) => {
          acc.totalTokens += trace.total_tokens || 0;
          acc.totalCost += Number(trace.total_cost || 0);
          return acc;
        },
        { totalTokens: 0, totalCost: 0 },
      )
    : (run.node_runs || []).reduce(
        (acc, node) => {
          const usage = (node.outputs as any)?.usage;
          if (usage) {
            acc.totalTokens += usage.total_tokens || 0;
            if (typeof (node.outputs as any)?.cost === 'number') {
              acc.totalCost += (node.outputs as any).cost;
            }
          }
          return acc;
        },
        { totalTokens: 0, totalCost: 0 },
      );

  return (
    <div className="flex flex-col h-full overflow-y-auto p-1">
      {/* 1. 헤더: 실행 요약 및 컨트롤 */}
      <div className="border-b border-gray-100 pb-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-gray-900">실행 상세</h2>
            {run.status === 'success' ? (
              <span className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> SUCCESS
              </span>
            ) : run.status === 'failed' ? (
              <span className="px-3 py-1 bg-red-100 text-red-700 rounded-full text-xs font-bold flex items-center gap-1">
                <XCircle className="w-3 h-3" /> FAILED
              </span>
            ) : (
              <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold flex items-center gap-1">
                <PlayCircle className="w-3 h-3" /> RUNNING
              </span>
            )}
          </div>

          {onCompareClick && (
            <button
              onClick={onCompareClick}
              className="px-4 py-2 bg-white border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 flex items-center gap-2 text-sm shadow-sm transition-colors"
            >
              <span>⚡ A/B Compare</span>
            </button>
          )}
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-4 text-sm bg-gray-50 p-4 rounded-xl border border-gray-100">
          <div>
            <span className="block text-gray-500 text-xs mb-1">시작 시간</span>
            <span className="font-medium flex items-center gap-1 text-gray-800">
              <Clock className="w-3 h-3" />
              {format(new Date(run.started_at), 'yyyy-MM-dd HH:mm:ss', {
                locale: ko,
              })}
            </span>
          </div>
          <div>
            <span className="block text-gray-500 text-xs mb-1">소요 시간</span>
            <span className="font-medium text-gray-800">
              {run.duration ? `${run.duration.toFixed(2)}초` : '-'}
            </span>
          </div>
          <div>
            <span className="block text-gray-500 text-xs mb-1">총 토큰</span>
            <span className="font-medium text-gray-800">
              {totalTokens.toLocaleString()}
            </span>
          </div>
          <div>
            <span className="block text-gray-500 text-xs mb-1">총 비용</span>
            <span className="font-medium text-gray-800 flex items-center gap-1">
              <span className="text-amber-600">
                {totalCost > 0 ? `$${totalCost.toFixed(4)}` : '-'}
              </span>
            </span>
          </div>
        </div>
      </div>

      {finalOutputSummary && (
        <FinalOutputSummary
          text={finalOutputSummary.text}
          node={finalOutputSummary.node}
          onNodeSelect={setSelectedNodeId}
        />
      )}

      {/* 2. Token Analysis Sections */}
      <LogTokenAnalysis
        run={run}
        llmTraces={llmTraces}
        loading={llmTraceLoading}
        error={llmTraceError}
        onNodeSelect={setSelectedNodeId}
      />

      {/* 3. Visual Execution Path */}
      <div className="mb-6">
        <h3 className="font-bold text-gray-800 mb-3 text-sm flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-blue-500" />
          실행 흐름
        </h3>
        <LogExecutionPath
          nodeRuns={run.node_runs || []}
          onNodeSelect={setSelectedNodeId}
          selectedNodeId={selectedNode?.node_id ?? null}
        />
      </div>

      {/* 3. 상세 내용 */}
      {compactMode ? (
        // Compact Mode: 반응형 좌우 분할 (lg 이상에서 좌측 목록 표시)
        <div className="flex gap-4 items-start">
          {/* 좌측 패널: lg 이상에서만 표시 */}
          <div className="hidden lg:block w-1/3 border-r border-gray-100 pr-4 sticky top-0 self-start max-h-[calc(100vh-300px)] overflow-y-auto">
            <h3 className="font-bold text-gray-700 mb-3 text-sm sticky top-0 bg-white py-1 z-10">
              노드 목록
            </h3>
            <div className="space-y-2">
              {run.node_runs?.map((node, idx) => {
                const displayInfo = getNodeDisplayInfo(node.node_type);
                const duration = getNodeDuration(node);
                return (
                  <button
                    key={`${node.node_id}-${idx}`}
                    onClick={() => setSelectedNodeId(node.node_id)}
                    className={`w-full text-left p-2 rounded-lg border transition-all text-xs ${
                      selectedNode?.node_id === node.node_id
                        ? 'bg-blue-50 border-blue-200 ring-1 ring-blue-100'
                        : 'bg-white border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <span
                        className={`font-semibold flex items-center gap-1.5 ${displayInfo.color}`}
                      >
                        {displayInfo.icon}
                        {displayInfo.label}
                      </span>
                      <span
                        className={`text-[9px] px-1 py-0.5 rounded ${
                          node.status === 'success'
                            ? 'bg-green-100 text-green-700'
                            : node.status === 'running'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {node.status === 'success'
                          ? '✓'
                          : node.status === 'running'
                            ? '...'
                            : '✗'}
                      </span>
                    </div>
                    {duration && (
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        {duration}초
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 우측: 상세 정보 */}
          <div className="flex-1 min-w-0">
            {selectedNode ? (
              <div className="space-y-4">
                {selectedNode.process_data?.node_options && (
                  <NodeOptionsSection
                    nodeType={selectedNode.node_type}
                    options={selectedNode.process_data.node_options}
                  />
                )}
                <InputDataSection data={selectedNode.inputs} />
                <OutputDataSection data={selectedNode.outputs} />
                {selectedNode.error_message && (
                  <div className="bg-red-50 rounded-lg p-3 border border-red-200">
                    <h4 className="font-bold text-red-700 flex items-center gap-2 mb-1 text-sm">
                      <AlertCircle className="w-4 h-4" /> 에러
                    </h4>
                    <p className="text-xs text-red-600">
                      {selectedNode.error_message}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-gray-400 py-8">
                <p className="text-sm">실행 흐름에서 노드를 선택하세요</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        // Normal Mode: 좌우 분할 레이아웃
        <div className="flex gap-6 items-start">
          <div className="w-1/3 border-r border-gray-100 pr-6 sticky top-0 self-start max-h-[calc(100vh-200px)] overflow-y-auto">
            <h3 className="font-bold text-gray-800 mb-4 sticky top-0 bg-white py-2 z-10">
              노드 실행 경로
            </h3>
            <div className="space-y-3">
              {run.node_runs?.map((node, idx) => {
                const displayInfo = getNodeDisplayInfo(node.node_type);
                const duration = getNodeDuration(node);

                return (
                  <button
                    key={`${node.node_id}-${idx}`}
                    ref={(el) => {
                      if (el) {
                        nodeRefs.current.set(node.node_id, el);
                      } else {
                        nodeRefs.current.delete(node.node_id);
                      }
                    }}
                    onClick={() => setSelectedNodeId(node.node_id)}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${
                      selectedNode?.node_id === node.node_id
                        ? 'bg-blue-50 border-blue-200 shadow-sm ring-1 ring-blue-100'
                        : 'bg-white border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span
                        className={`font-semibold text-sm flex items-center gap-2 px-2 py-1 rounded ${displayInfo.color}`}
                      >
                        {displayInfo.icon}
                        {displayInfo.label}
                      </span>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${
                          node.status === 'success'
                            ? 'bg-green-100 text-green-700'
                            : node.status === 'running'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {node.status === 'success'
                          ? '성공'
                          : node.status === 'running'
                            ? '진행중'
                            : '실패'}
                      </span>
                    </div>
                    {duration && (
                      <div className="text-xs text-gray-500 flex items-center gap-1 mt-1">
                        <Clock className="w-3 h-3" />
                        소요: {duration}초
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex-1 pl-2">
            <h3 className="font-bold text-gray-800 mb-4 sticky top-0 bg-white py-2 z-10">
              노드 상세 정보
            </h3>
            {selectedNode ? (
              <div className="space-y-6">
                {selectedNode.process_data?.node_options && (
                  <NodeOptionsSection
                    nodeType={selectedNode.node_type}
                    options={selectedNode.process_data.node_options}
                  />
                )}
                <InputDataSection data={selectedNode.inputs} />
                <OutputDataSection data={selectedNode.outputs} />
                {selectedNode.error_message && (
                  <div className="bg-red-50 rounded-lg p-4 border border-red-200">
                    <h4 className="font-bold text-red-700 flex items-center gap-2 mb-1">
                      <AlertCircle className="w-4 h-4" /> 에러 발생
                    </h4>
                    <p className="text-sm text-red-600">
                      {selectedNode.error_message}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-gray-400">
                <BrainCircuit className="w-12 h-12 mb-3 opacity-20" />
                <p>왼쪽에서 노드를 선택하여 상세 정보를 확인하세요.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
