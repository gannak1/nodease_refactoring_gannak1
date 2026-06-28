import React, { useState, useEffect, useMemo } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { workflowApi } from '../../api/workflowApi';
import { knowledgeApi } from '@/app/features/knowledge/api/knowledgeApi';
import {
  X,
  Play,
  RefreshCw,
  Loader2,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { StartNodeData, WorkflowVariable } from '../../types/Nodes';
import { WorkflowCompareResponse } from '../../types/Api';

type TestSidebarProps = {
  appendMemoryFlag?: (
    inputs: Record<string, any> | FormData,
  ) => Record<string, any> | FormData;
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
  } = useWorkflowStore();
  const { setCenter } = useReactFlow();

  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [isUploading, setIsUploading] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any>(null);
  const [compareResult, setCompareResult] =
    useState<WorkflowCompareResponse | null>(null);
  const [isComparing, setIsComparing] = useState(false);
  const [compareNodeId, setCompareNodeId] = useState('');
  const [compareType, setCompareType] = useState<'model' | 'prompt'>('model');
  const [leftValue, setLeftValue] = useState('');
  const [rightValue, setRightValue] = useState('');
  const [nodeResults, setNodeResults] = useState<
    Array<{ nodeId: string; nodeType: string; output: any }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const nodeStartedAtRef = React.useRef<Record<string, number>>({});
  const canExecute = workflowAccess?.can_execute !== false;

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

  const llmNodes = useMemo(
    () => nodes.filter((node) => node.type === 'llmNode'),
    [nodes],
  );

  // 패널이 열릴 때 입력값 초기화 (실행 결과는 유지)
  useEffect(() => {
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
  }, [isTestPanelOpen]);

  useEffect(() => {
    if (!compareNodeId && llmNodes[0]) {
      setCompareNodeId(llmNodes[0].id);
    }
  }, [compareNodeId, llmNodes]);

  useEffect(() => {
    const selected = llmNodes.find((node) => node.id === compareNodeId);
    if (!selected) return;
    const data = selected.data as any;
    if (compareType === 'model') {
      setLeftValue(data.model_id || '');
      setRightValue(data.fallback_model_id || data.model_id || '');
    } else {
      setLeftValue(data.user_prompt || '');
      setRightValue(data.user_prompt || '');
    }
    setCompareResult(null);
  }, [compareNodeId, compareType]);

  if (!isTestPanelOpen) return null;

  const handleChange = (name: string, value: any) => {
    setInputs((prev) => ({ ...prev, [name]: value }));
  };

  const buildFinalInputs = async () => {
    const hasFiles = Object.values(files).some((file) => file !== null);
    let finalInputs: Record<string, any> = { ...inputs };

    if (startNode?.type === 'webhookTrigger') {
      try {
        const rawJson = inputs['__json_payload__'];
        finalInputs = JSON.parse(rawJson);
      } catch {
        throw new Error('JSON 파싱 실패');
      }
    }

    if (hasFiles) {
      setIsUploading(true);
      try {
        for (const [key, file] of Object.entries(files)) {
          if (!file) continue;
          const presignedData = await knowledgeApi.getPresignedUploadUrl(
            file.name,
            file.type || 'application/octet-stream',
          );
          await knowledgeApi.uploadToS3(
            presignedData.upload_url,
            file,
            file.type || 'application/octet-stream',
          );
          finalInputs[key] = presignedData.upload_url.split('?')[0];
        }
      } finally {
        setIsUploading(false);
      }
    }

    return appendMemoryFlag
      ? appendMemoryFlag(finalInputs)
      : finalInputs;
  };

  const buildObservability = (
    output: any,
    status: 'success' | 'failure' | 'running',
    latencyMs?: number,
  ) => {
    const usage = output?.usage || {};
    return {
      status,
      model: output?.model,
      total_tokens:
        usage.total_tokens ||
        (usage.prompt_tokens || 0) + (usage.completion_tokens || 0),
      total_cost: output?.cost || usage.total_cost || 0,
      latency_ms: latencyMs,
    };
  };

  const handleExecute = async () => {
    if (!activeWorkflowId) return;
    if (!canExecute) {
      setError('현재 권한으로는 실행할 수 없습니다.');
      return;
    }

    setIsExecuting(true);
    setExecutionResult(null);
    setNodeResults([]);
    setError(null);

    try {
      const inputsWithMemory = await buildFinalInputs();

      // 1. 초기화: 모든 노드 상태 초기화
      const initialNodes = nodes.map((node) => ({
        ...node,
        data: { ...node.data, status: 'idle', observability: undefined },
      })) as unknown as any[];
      setNodes(initialNodes);

      let finalResult: any = null;

      await workflowApi.executeWorkflowStream(
        activeWorkflowId,
        inputsWithMemory as Record<string, any>,
        async (event) => {
          // 시각적 피드백을 위한 지연
          await new Promise((resolve) => setTimeout(resolve, 500));

          const { type, data } = event;

          if (type === 'node_start') {
            nodeStartedAtRef.current[data.node_id] = performance.now();
            updateNodeData(data.node_id, {
              status: 'running',
              observability: buildObservability(null, 'running'),
            });

            // 실행 중인 노드로 화면 중심 이동 및 줌인
            const latestNodes = useWorkflowStore.getState().nodes;
            const currentNode = latestNodes.find((n) => n.id === data.node_id);
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
            const latencyMs = startedAt
              ? Math.round(performance.now() - startedAt)
              : undefined;
            updateNodeData(data.node_id, {
              status: 'success',
              observability: buildObservability(
                data.output,
                'success',
                latencyMs,
              ),
            });

            // 노드 실행 완료 토스트

            // 노드 결과 누적
            setNodeResults((prev) => [
              ...prev,
              {
                nodeId: data.node_id,
                nodeType: data.node_type,
                output: data.output,
              },
            ]);
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
            }
            toast.error(`모듈 실행 실패: ${data.message}`);
            throw new Error(data.message);
          }
        },
      );

      // 최종 결과 저장
      if (finalResult) {
        setExecutionResult(finalResult);
      }
    } catch (err: any) {
      console.error('Execution failed:', err);
      setError(err.message || '실행 중 오류가 발생했습니다.');
      toast.error('실행 실패');
    } finally {
      setIsExecuting(false);
    }
  };

  const handleReset = () => {
    setExecutionResult(null);
    setNodeResults([]);
    setError(null);
  };

  const handleCompare = async () => {
    if (!activeWorkflowId || !compareNodeId || !leftValue || !rightValue) return;
    if (!canExecute) {
      setError('현재 권한으로는 비교 실행을 할 수 없습니다.');
      return;
    }
    setIsComparing(true);
    setCompareResult(null);
    setError(null);
    try {
      const compareInputs = await buildFinalInputs();
      const result = await workflowApi.compareWorkflow(activeWorkflowId, {
        node_id: compareNodeId,
        compare_type: compareType,
        inputs: compareInputs as Record<string, unknown>,
        left: leftValue,
        right: rightValue,
      });
      setCompareResult(result);
    } catch (err: any) {
      setError(err.message || '비교 실행 중 오류가 발생했습니다.');
      toast.error('비교 실행 실패');
    } finally {
      setIsComparing(false);
    }
  };

  return (
    <div className="absolute top-18 right-2 bottom-2 w-[400px] bg-white border-l border-gray-200 shadow-xl z-50 flex flex-col rounded-xl animate-in slide-in-from-right duration-200 dark:bg-gray-900 dark:border-gray-800">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between dark:border-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
          <Play className="w-5 h-5 text-blue-600" />
          테스트 실행
        </h2>
        <button
          onClick={toggleTestPanel}
          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-colors dark:hover:bg-gray-800"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isExecuting && nodeResults.length > 0 ? (
          /* Execution Progress - Show node results as they come in */
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-blue-600 mb-4">
              <Loader2 className="w-5 h-5 animate-spin" />
              <h3 className="text-sm font-medium">실행 중...</h3>
            </div>
            {nodeResults.map((result, index) => (
              <div
                key={`${result.nodeId}-${index}`}
                className="border border-gray-200 rounded-lg overflow-hidden dark:border-gray-700 animate-in fade-in slide-in-from-bottom-2 duration-300"
              >
                <div className="px-4 py-2 bg-green-50 border-b border-green-200 flex items-center gap-2 dark:bg-green-900/20 dark:border-green-800">
                  <CheckCircle className="w-4 h-4 text-green-600" />
                  <span className="text-xs font-medium text-green-800 dark:text-green-400">
                    [{result.nodeType}] 완료
                  </span>
                </div>
                <div className="p-3 bg-white overflow-x-auto dark:bg-gray-900 max-h-40">
                  <pre className="text-xs text-gray-600 font-mono dark:text-gray-300">
                    {JSON.stringify(result.output, null, 2)}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        ) : !executionResult && !error ? (
          /* Input Form */
          <div className="space-y-6">
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
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[200px] font-mono text-sm dark:bg-gray-800 dark:border-gray-700"
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
                            {variable.name}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </span>
                        </label>
                      ) : variable.type === 'select' ? (
                        <>
                          <label className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-300">
                            {variable.name}
                            {variable.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </label>
                          <select
                            value={inputs[variable.name] || ''}
                            onChange={(e) =>
                              handleChange(variable.name, e.target.value)
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-800 dark:border-gray-700"
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
                            {variable.name}
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
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:border-gray-700"
                          />
                        </>
                      ) : (
                        <>
                          <label className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-300">
                            {variable.name}
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
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[100px] dark:bg-gray-800 dark:border-gray-700"
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
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:border-gray-700"
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

            {llmNodes.length > 0 && (
              <div className="border border-gray-200 rounded-lg overflow-hidden dark:border-gray-700">
                <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700">
                  <h3 className="text-sm font-medium text-gray-900 dark:text-gray-200">
                    Model / Prompt 비교
                  </h3>
                </div>
                <div className="p-4 space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={compareNodeId}
                      onChange={(event) => setCompareNodeId(event.target.value)}
                      className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white dark:bg-gray-800 dark:border-gray-700"
                    >
                      {llmNodes.map((node) => (
                        <option key={node.id} value={node.id}>
                          {(node.data as any).title || node.id}
                        </option>
                      ))}
                    </select>
                    <div className="grid grid-cols-2 rounded-lg border border-gray-300 overflow-hidden dark:border-gray-700">
                      {(['model', 'prompt'] as const).map((type) => (
                        <button
                          key={type}
                          onClick={() => setCompareType(type)}
                          className={`py-2 text-sm font-medium ${
                            compareType === type
                              ? 'bg-blue-600 text-white'
                              : 'bg-white text-gray-700 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-200'
                          }`}
                        >
                          {type}
                        </button>
                      ))}
                    </div>
                  </div>

                  {compareType === 'model' ? (
                    <div className="grid grid-cols-2 gap-2">
                      <input
                        value={leftValue}
                        onChange={(event) => setLeftValue(event.target.value)}
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm dark:bg-gray-800 dark:border-gray-700"
                        placeholder="Model A"
                      />
                      <input
                        value={rightValue}
                        onChange={(event) => setRightValue(event.target.value)}
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm dark:bg-gray-800 dark:border-gray-700"
                        placeholder="Model B"
                      />
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      <textarea
                        value={leftValue}
                        onChange={(event) => setLeftValue(event.target.value)}
                        className="min-h-[120px] px-3 py-2 border border-gray-300 rounded-lg text-sm dark:bg-gray-800 dark:border-gray-700"
                        placeholder="Prompt A"
                      />
                      <textarea
                        value={rightValue}
                        onChange={(event) => setRightValue(event.target.value)}
                        className="min-h-[120px] px-3 py-2 border border-gray-300 rounded-lg text-sm dark:bg-gray-800 dark:border-gray-700"
                        placeholder="Prompt B"
                      />
                    </div>
                  )}

                  <button
                    onClick={handleCompare}
                    disabled={
                      isComparing ||
                      isUploading ||
                      !canExecute ||
                      !leftValue ||
                      !rightValue
                    }
                    className="w-full px-4 py-2 text-white bg-gray-900 hover:bg-gray-800 disabled:bg-gray-300 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2 font-medium"
                  >
                    {isComparing ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        비교 실행 중...
                      </>
                    ) : (
                      '비교 실행'
                    )}
                  </button>

                  {compareResult && (
                    <div className="grid grid-cols-2 gap-2">
                      {compareResult.variants.map((variant) => (
                        <div
                          key={variant.label}
                          className="border border-gray-200 rounded-lg p-3 dark:border-gray-700"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                              {variant.label}
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                variant.status === 'success'
                                  ? 'bg-green-50 text-green-700'
                                  : 'bg-red-50 text-red-700'
                              }`}
                            >
                              {variant.status}
                            </span>
                          </div>
                          <dl className="mt-2 space-y-1 text-xs text-gray-600 dark:text-gray-300">
                            <div className="flex justify-between gap-2">
                              <dt>tokens</dt>
                              <dd>{variant.total_tokens || 0}</dd>
                            </div>
                            <div className="flex justify-between gap-2">
                              <dt>cost</dt>
                              <dd>${Number(variant.total_cost || 0).toFixed(6)}</dd>
                            </div>
                            <div className="flex justify-between gap-2">
                              <dt>latency</dt>
                              <dd>{variant.latency_ms || 0}ms</dd>
                            </div>
                          </dl>
                          {variant.error ? (
                            <p className="mt-2 line-clamp-3 text-xs text-red-600">
                              {variant.error}
                            </p>
                          ) : (
                            <pre className="mt-2 max-h-32 overflow-auto rounded bg-gray-50 p-2 text-[11px] text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                              {JSON.stringify(variant.node_output, null, 2)}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
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

            {executionResult && (
              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-3 dark:text-gray-200">
                  노드별 실행 결과
                </h3>
                <div className="space-y-3">
                  {Object.entries(executionResult).map(
                    ([nodeId, output]: [string, any]) => (
                      <div
                        key={nodeId}
                        className="border border-gray-200 rounded-lg overflow-hidden dark:border-gray-700"
                      >
                        <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 text-xs font-medium text-gray-500 dark:bg-gray-800 dark:border-gray-700">
                          {nodeId}
                        </div>
                        <div className="p-3 bg-white overflow-x-auto dark:bg-gray-900">
                          <pre className="text-xs text-gray-600 font-mono dark:text-gray-300">
                            {JSON.stringify(output, null, 2)}
                          </pre>
                        </div>
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 dark:bg-gray-900 dark:border-gray-800">
        {!executionResult && !error ? (
          <button
            onClick={handleExecute}
            disabled={isExecuting || isUploading || !canExecute}
            className="w-full px-4 py-2 text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2 font-medium"
          >
            {isExecuting || isUploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {isUploading ? '파일 업로드 중...' : '실행 중...'}
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                {canExecute ? '실행하기' : '실행 권한 없음'}
              </>
            )}
          </button>
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
