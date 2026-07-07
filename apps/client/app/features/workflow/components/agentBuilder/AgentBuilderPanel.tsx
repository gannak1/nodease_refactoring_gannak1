'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertCircle, Bot, Eye, Loader2, Send, X } from 'lucide-react';
import { toast } from 'sonner';
import { useReactFlow, type Edge, type Viewport } from '@xyflow/react';
import { agentBuilderApi, AgentBuilderMessageResponse } from '../../api/agentBuilderApi';
import { workflowApi } from '../../api/workflowApi';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import type { Node } from '../../types/Workflow';

type Props = {
  workflowId: string;
  appId?: string | null;
  nodes: Node[];
  edges: Edge[];
  hasUnsavedChanges: boolean;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
};

const UI_ONLY_NODE_DATA_KEYS = new Set([
  'selected',
  'dragging',
  'status',
  'displayStatus',
  'isHovered',
]);

const semanticNodeData = (data: Node['data']) =>
  Object.fromEntries(
    Object.entries(data ?? {}).filter(([key]) => !UI_ONLY_NODE_DATA_KEYS.has(key)),
  );

const stableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(stableValue);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, stableValue(entry)]),
    );
  }
  return value;
};

const graphHashPayload = (nodes: Node[], edges: Edge[]) => {
  const realNodes = nodes.filter((node) => node.type !== 'note');
  const realNodeIds = new Set(realNodes.map((node) => node.id));
  const realEdges = edges.filter(
    (edge) => realNodeIds.has(edge.source) && realNodeIds.has(edge.target),
  );

  return JSON.stringify(
    stableValue({
      nodes: realNodes
        .map((node) => ({
          id: node.id,
          type: node.type,
          data: semanticNodeData(node.data),
        }))
        .sort((a, b) => a.id.localeCompare(b.id)),
      edges: realEdges
        .map((edge) => ({
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle ?? null,
          targetHandle: edge.targetHandle ?? null,
        }))
        .sort((a, b) =>
          [
            a.source.localeCompare(b.source),
            a.target.localeCompare(b.target),
            String(a.sourceHandle ?? '').localeCompare(String(b.sourceHandle ?? '')),
            String(a.targetHandle ?? '').localeCompare(String(b.targetHandle ?? '')),
          ].find((value) => value !== 0) ?? 0,
        ),
    }),
  );
};

const graphHash = async (nodes: Node[], edges: Edge[]) => {
  if (typeof crypto === 'undefined' || !crypto.subtle) {
    return null;
  }
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(graphHashPayload(nodes, edges)),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
};

const canonicalEditorGraph = (nodes: Node[], edges: Edge[]) => {
  const realNodes = nodes.filter((node) => node.type !== 'note');
  const realNodeIds = new Set(realNodes.map((node) => node.id));
  const realEdges = edges.filter(
    (edge) => realNodeIds.has(edge.source) && realNodeIds.has(edge.target),
  );
  return { nodes: realNodes, edges: realEdges };
};

export function AgentBuilderPanel({
  workflowId,
  appId,
  nodes,
  edges,
  hasUnsavedChanges,
  selectedNodeId,
  selectedEdgeId,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [applyNotice, setApplyNotice] = useState<string | null>(null);
  const [responses, setResponses] = useState<AgentBuilderMessageResponse[]>([]);
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null);
  const [prePreviewViewport, setPrePreviewViewport] = useState<Viewport | null>(null);
  const router = useRouter();
  const { getViewport, setViewport } = useReactFlow();
  const agentBuilderPreview = useWorkflowStore((state) => state.agentBuilderPreview);
  const setAgentBuilderPreview = useWorkflowStore(
    (state) => state.setAgentBuilderPreview,
  );
  const clearAgentBuilderPreview = useWorkflowStore(
    (state) => state.clearAgentBuilderPreview,
  );
  const setWorkflowData = useWorkflowStore((state) => state.setWorkflowData);
  const envVariables = useWorkflowStore((state) => state.envVariables);
  const runtimeVariables = useWorkflowStore((state) => state.runtimeVariables);

  const latestResponse = responses[responses.length - 1];
  const storageKey = `agent-builder:${workflowId}:${appId ?? 'none'}`;
  const scopeRef = useRef(storageKey);

  const appendResponse = (response: AgentBuilderMessageResponse) => {
    setResponses((items) =>
      items.some((item) => item.request_id === response.request_id)
        ? items
        : [...items, response],
    );
  };

  useEffect(() => {
    if (scopeRef.current === storageKey) return;
    scopeRef.current = storageKey;
    setSessionId(null);
    setInput('');
    setIsSubmitting(false);
    setIsApplying(false);
    setApplyNotice(null);
    setResponses([]);
    setPendingRequestId(null);
    setPrePreviewViewport(null);
    clearAgentBuilderPreview();
  }, [storageKey, clearAgentBuilderPreview]);

  useEffect(() => {
    if (!isOpen || sessionId || typeof window === 'undefined') return;
    const storedSessionId = window.localStorage.getItem(storageKey);
    if (!storedSessionId) return;
    let isCanceled = false;
    agentBuilderApi
      .getSession(storedSessionId)
      .then((session) => {
        if (isCanceled) return;
        setSessionId(session.session_id);
        setResponses(session.messages as AgentBuilderMessageResponse[]);
        const requestId = session.pending_request?.request_id;
        setPendingRequestId(typeof requestId === 'string' ? requestId : null);
      })
      .catch(() => {
        window.localStorage.removeItem(storageKey);
      });
    return () => {
      isCanceled = true;
    };
  }, [isOpen, sessionId, storageKey]);

  const ensureSession = async () => {
    if (sessionId) return sessionId;
    const session = await agentBuilderApi.createSession({ workflowId, appId });
    setSessionId(session.session_id);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(storageKey, session.session_id);
    }
    return session.session_id;
  };

  const submit = async () => {
    const message = input.trim();
    if (!message || isSubmitting) return;
    if (hasUnsavedChanges) {
      toast.warning('저장되지 않은 변경이 있어 Agent Builder를 시작할 수 없습니다.');
      return;
    }
    setIsSubmitting(true);
    try {
      const nextSessionId = await ensureSession();
      setPendingRequestId('submitting');
      const response = await agentBuilderApi.sendMessage(nextSessionId, {
        message,
        workflowId,
        appId,
        selectedNodeId,
        selectedEdgeId,
      });
      appendResponse(response);
      setPendingRequestId(null);
      setInput('');
    } catch {
      toast.error('Agent Builder 요청에 실패했습니다.');
      setPendingRequestId(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const resolvePendingRequestId = async () => {
    if (pendingRequestId && pendingRequestId !== 'submitting') {
      return pendingRequestId;
    }
    if (!sessionId) return null;
    const session = await agentBuilderApi.getSession(sessionId);
    setResponses(session.messages as AgentBuilderMessageResponse[]);
    const requestId = session.pending_request?.request_id;
    if (typeof requestId === 'string') {
      setPendingRequestId(requestId);
      return requestId;
    }
    return null;
  };

  const cancelPendingRequest = async () => {
    if (!pendingRequestId) return;
    try {
      const requestId = await resolvePendingRequestId();
      if (!requestId) {
        toast.warning('취소할 진행 중 요청을 아직 확인하지 못했습니다. 잠시 후 다시 시도해주세요.');
        return;
      }
      const response = await agentBuilderApi.cancelRequest(requestId);
      appendResponse(response);
      setPendingRequestId(null);
      toast.success('진행 중인 Agent Builder 요청을 취소했습니다.');
    } catch {
      toast.error('진행 중 요청 취소에 실패했습니다.');
    }
  };

  const openPreview = async () => {
    const preview = latestResponse?.draft_preview;
    if (!preview) return;
    if (hasUnsavedChanges) {
      toast.warning('저장되지 않은 변경이 있어 도안 보기를 열 수 없습니다.');
      return;
    }
    if (!preview.validation_result.valid) {
      toast.warning('검증을 통과한 초안만 도안 보기로 열 수 있습니다.');
      return;
    }
    try {
      await agentBuilderApi.recordPreviewOpened(preview.draft_id);
    } catch {
      toast.error('도안 보기 audit 기록에 실패해 미리보기를 열 수 없습니다. 다시 시도해주세요.');
      return;
    }
    setIsOpen(true);
    setApplyNotice(null);
    setPrePreviewViewport(getViewport());
    setAgentBuilderPreview({
      draftId: preview.draft_id,
      previewGraph: {
        nodes: preview.preview_graph.nodes as unknown as Node[],
        edges: preview.preview_graph.edges as unknown as Edge[],
        viewport: preview.preview_graph.viewport,
      },
      nodeDetailPreviews: preview.node_detail_previews,
      validationResult: preview.validation_result,
      baseGraphHash: preview.base_graph_hash,
      draftMode: preview.draft_mode,
    });
  };

  const applyAndSave = async () => {
    if (!agentBuilderPreview || isApplying) return;
    if (hasUnsavedChanges) {
      toast.warning('저장되지 않은 변경이 있어 적용 및 저장을 차단했습니다.');
      return;
    }
    setIsApplying(true);
    setApplyNotice(null);
    try {
      const latestGraph = canonicalEditorGraph(nodes, edges);
      const clientPreviewGraphHash = await graphHash(
        agentBuilderPreview.previewGraph.nodes,
        agentBuilderPreview.previewGraph.edges,
      );
      const clientLatestGraphHash = await graphHash(
        latestGraph.nodes,
        latestGraph.edges,
      );
      if (!clientPreviewGraphHash || !clientLatestGraphHash) {
        toast.error('브라우저에서 graph hash를 계산할 수 없어 저장을 중단했습니다.');
        return;
      }
      const response = await agentBuilderApi.applyDraft(agentBuilderPreview.draftId, {
        clientPreviewGraphHash,
        clientLatestGraphHash,
      });
      if (response.outcome === 'saved' && response.audit_recorded) {
        const savedWorkflowId = response.saved_workflow_id ?? workflowId;
        const [savedWorkflow, savedWorkflowMeta] = await Promise.all([
          workflowApi.getDraftWorkflow(savedWorkflowId),
          workflowApi.getWorkflow(savedWorkflowId),
        ]);
        const isSameWorkflow = savedWorkflowId === workflowId;
        setWorkflowData(
          {
            ...savedWorkflow,
            appId: savedWorkflowMeta.app_id,
            envVariables: isSameWorkflow ? envVariables : [],
            runtimeVariables: isSameWorkflow ? runtimeVariables : [],
          },
          savedWorkflowId,
        );
        toast.success('Agent Builder 초안을 저장했습니다.');
        setPrePreviewViewport(null);
        clearAgentBuilderPreview();
        if (savedWorkflowId !== workflowId) {
          router.push(`/modules/${savedWorkflowId}`);
        }
        return;
      }
      const notice =
        response.notices[0] ??
        response.block_reason ??
        response.failure_reason ??
        '초안을 저장하지 못했습니다.';
      setApplyNotice(notice);
      toast.warning(notice);
    } catch {
      toast.error('초안 적용 및 저장에 실패했습니다.');
      setApplyNotice('초안 적용 및 저장에 실패했습니다.');
    } finally {
      setIsApplying(false);
    }
  };

  const cancelPreview = async () => {
    const draftId = agentBuilderPreview?.draftId;
    setApplyNotice(null);
    clearAgentBuilderPreview();
    if (prePreviewViewport) {
      setViewport(prePreviewViewport);
      setPrePreviewViewport(null);
    }
    if (!draftId) return;
    try {
      await agentBuilderApi.cancelDraft(draftId);
    } catch {
      toast.warning('초안 취소 audit 기록에 실패했습니다.');
    }
  };

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3">
      {isOpen && (
        <section className="flex h-[520px] w-[380px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl">
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-slate-700" />
              <span className="text-sm font-semibold text-slate-900">
                Agent Builder
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                if (!agentBuilderPreview) {
                  setIsOpen(false);
                }
              }}
              disabled={Boolean(agentBuilderPreview)}
              className="rounded-md p-1 text-slate-500 hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
              aria-label="Agent Builder 닫기"
            >
              <X className="h-4 w-4" />
            </button>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
            {hasUnsavedChanges && (
              <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  저장되지 않은 변경이 있어 초안 생성, 도안 보기, 적용 및 저장이 차단됩니다.
                </span>
              </div>
            )}
            {responses.length === 0 && (
              <p className="text-slate-500">
                만들고 싶은 workflow를 한국어로 입력하세요.
              </p>
            )}
            {pendingRequestId && (
              <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
                <p>Agent Builder 요청이 진행 중입니다.</p>
                <button
                  type="button"
                  onClick={cancelPendingRequest}
                  className="mt-2 rounded-md border border-blue-300 px-2 py-1 font-semibold"
                >
                  요청 취소
                </button>
              </div>
            )}
            {responses.map((response) => (
              <div
                key={response.request_id}
                className="rounded-md border border-slate-200 bg-slate-50 p-3"
              >
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {response.status}
                </div>
                {response.draft_preview ? (
                  <p className="mt-2 text-slate-700">
                    workflow 초안이 생성되었습니다. 도안 보기에서 실제 editor graph와
                    분리된 preview를 확인할 수 있습니다.
                  </p>
                ) : null}
                {response.clarification_questions?.map((question) => (
                  <p key={question} className="mt-2 text-slate-700">
                    {question}
                  </p>
                ))}
                {response.validation_result?.issues?.map((issue) => (
                  <p key={`${issue.code}-${issue.path}`} className="mt-2 text-red-700">
                    {issue.message}
                  </p>
                ))}
                {response.warnings?.map((warning) => (
                  <p key={warning} className="mt-2 text-xs text-slate-500">
                    {warning}
                  </p>
                ))}
              </div>
            ))}
          </div>

          <div className="border-t border-slate-200 p-3">
            {latestResponse?.draft_preview?.validation_result.valid &&
              !agentBuilderPreview && (
              <button
                type="button"
                onClick={openPreview}
                disabled={hasUnsavedChanges}
                className="mb-2 flex w-full items-center justify-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                <Eye className="h-4 w-4" />
                도안 보기
              </button>
            )}
            {agentBuilderPreview && applyNotice && (
              <div className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {applyNotice}
              </div>
            )}
            {agentBuilderPreview && (
              <div className="mb-2 flex gap-2">
                <button
                  type="button"
                  onClick={applyAndSave}
                  disabled={hasUnsavedChanges || isApplying}
                  className="flex-1 rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {isApplying ? '저장 중' : '적용 및 저장'}
                </button>
                <button
                  type="button"
                  onClick={cancelPreview}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
                >
                  취소
                </button>
              </div>
            )}
            <div className="flex gap-2">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={Boolean(pendingRequestId) || isSubmitting}
                className="min-h-16 flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
                placeholder="예: 입력값을 분석해서 답변하는 workflow를 만들어줘"
              />
              <button
                type="button"
                onClick={submit}
                disabled={
                  !input.trim() ||
                  hasUnsavedChanges ||
                  isSubmitting ||
                  Boolean(pendingRequestId)
                }
                className="flex h-16 w-11 items-center justify-center rounded-md bg-slate-900 text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                aria-label="Agent Builder 요청 보내기"
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() =>
          setIsOpen((value) => (agentBuilderPreview ? true : !value))
        }
        className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-950 text-white shadow-lg transition-colors hover:bg-slate-800"
        aria-label="Agent Builder 열기"
      >
        <Bot className="h-5 w-5" />
      </button>
    </div>
  );
}
