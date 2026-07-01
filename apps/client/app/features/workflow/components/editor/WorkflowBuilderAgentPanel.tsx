'use client';

import { FormEvent, useMemo, useState } from 'react';
import { useReactFlow } from '@xyflow/react';
import {
  AlertCircle,
  Bot,
  Check,
  Loader2,
  MessageSquarePlus,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  activeOrganizationHeaders,
  getStoredActiveOrganizationId,
} from '@/lib/activeOrganization';
import type { WorkflowBuilderResponse } from '../../agent/types';
import type { Node as WorkflowNode } from '../../types/Nodes';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};

const getErrorMessage = async (response: Response) => {
  const data = await response.json().catch(() => null);
  return data?.detail || data?.message || 'Workflow builder request failed.';
};

const getNodeSummary = (
  result: WorkflowBuilderResponse | null,
  selectedNodeTitle?: string,
) => {
  if (!result?.selected_nodes.length) {
    return selectedNodeTitle ? `Editing from ${selectedNodeTitle}` : 'No draft yet';
  }
  return `${result.selected_nodes.length} nodes selected`;
};

const getWorkflowNodeTitle = (node: WorkflowNode | null) => {
  if (!node) return '';
  const title = String(node.data?.title || '').trim();
  if (title) return title;
  return String(node.type);
};

export function WorkflowBuilderAgentPanel() {
  const {
    nodes,
    edges,
    features,
    envVariables,
    runtimeVariables,
    activeWorkflowId,
    setWorkflowData,
    workflowAccess,
  } = useWorkflowStore();
  const { getViewport, fitView } = useReactFlow();
  const [isOpen, setIsOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: 'Tell me the workflow you want to create.',
    },
  ]);
  const [result, setResult] = useState<WorkflowBuilderResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isReadOnly = workflowAccess?.can_write === false;
  const selectedNode = useMemo<WorkflowNode | null>(
    () =>
      ((nodes || []) as WorkflowNode[]).find((node) => Boolean(node.selected)) ??
      null,
    [nodes],
  );
  const selectedNodeTitle = getWorkflowNodeTitle(selectedNode);
  const canApply =
    Boolean(result?.graph_preview) && result?.status !== 'invalid' && !isReadOnly;
  const resultMode = result?.mode === 'openai' ? 'OpenAI' : 'Heuristic';
  const helperText = useMemo(
    () => getNodeSummary(result, selectedNodeTitle),
    [result, selectedNodeTitle],
  );

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const nextPrompt = prompt.trim();
    if (!nextPrompt || isLoading) return;

    if (isReadOnly) {
      setError('You do not have write permission for this workflow.');
      return;
    }

    setIsLoading(true);
    setError(null);
    setPrompt('');
    setMessages((current) => [
      ...current,
      { role: 'user', content: nextPrompt },
    ]);

    try {
      const response = await fetch('/api/v1/workflow-builder-agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...activeOrganizationHeaders(getStoredActiveOrganizationId()),
        },
        credentials: 'include',
        body: JSON.stringify({
          prompt: nextPrompt,
          workflowId: activeWorkflowId,
          graph: {
            nodes,
            edges,
            viewport: getViewport(),
          },
          selectedNodeId: selectedNode?.id ?? null,
        }),
      });

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const data = (await response.json()) as WorkflowBuilderResponse;
      setResult(data);
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: data.message,
        },
      ]);
    } catch (submitError) {
      const message =
        submitError instanceof Error
          ? submitError.message
          : 'Workflow builder request failed.';
      setError(message);
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: message },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleApply = () => {
    if (!result?.graph_preview || isReadOnly) return;

    setWorkflowData({
      nodes: result.graph_preview.nodes,
      edges: result.graph_preview.edges,
      viewport: result.graph_preview.viewport,
      features,
      envVariables,
      runtimeVariables,
    });
    toast.success('Workflow draft applied.');
    setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 50);
  };

  return (
    <div
      className="pointer-events-none absolute bottom-24 right-4 z-40"
      data-canvas-shortcut-scope="blocked"
    >
      {isOpen ? (
        <div className="pointer-events-auto flex h-[560px] w-[380px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 text-white">
                <Bot className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-900">
                  Workflow Agent
                </div>
                <div className="truncate text-xs text-slate-500">
                  {helperText}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
              aria-label="Close workflow agent"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3">
            <div className="flex flex-col gap-2">
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={`max-w-[92%] rounded-lg px-3 py-2 text-sm leading-5 ${
                    message.role === 'user'
                      ? 'ml-auto bg-slate-950 text-white'
                      : 'mr-auto border border-slate-200 bg-slate-50 text-slate-700'
                  }`}
                >
                  {message.content}
                </div>
              ))}
              {isLoading && (
                <div className="mr-auto flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Planning workflow
                </div>
              )}
            </div>

            {error && (
              <div className="mt-3 flex gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {result && (
              <div className="mt-4 space-y-3 rounded-lg border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Preview
                  </div>
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    {resultMode}
                  </span>
                </div>

                {result.selected_nodes.length > 0 && (
                  <div className="space-y-1">
                    {result.selected_nodes.map((node) => (
                      <div
                        key={node.id}
                        className="flex items-start gap-2 rounded-md bg-slate-50 px-2 py-1.5"
                      >
                        <Check className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-600" />
                        <div className="min-w-0">
                          <div className="truncate text-xs font-medium text-slate-800">
                            {node.title}
                          </div>
                          <div className="text-[11px] leading-4 text-slate-500">
                            {node.reason}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {result.missing_fields.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-amber-700">
                      Missing settings
                    </div>
                    <ul className="space-y-1 text-xs text-slate-600">
                      {result.missing_fields.map((field) => (
                        <li key={field} className="rounded bg-amber-50 px-2 py-1">
                          {field}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.questions.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-blue-700">
                      Questions
                    </div>
                    <ul className="space-y-1 text-xs text-slate-600">
                      {result.questions.map((question) => (
                        <li key={question} className="rounded bg-blue-50 px-2 py-1">
                          {question}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.validation_errors.length > 0 && (
                  <div className="rounded-md border border-red-200 bg-red-50 px-2 py-2 text-xs text-red-700">
                    {result.validation_errors[0]}
                  </div>
                )}

                {result.warnings.length > 0 && (
                  <div className="rounded-md border border-slate-200 bg-slate-50 px-2 py-2 text-xs text-slate-500">
                    {result.warnings[0]}
                  </div>
                )}
              </div>
            )}
          </div>

          <form
            onSubmit={handleSubmit}
            className="border-t border-slate-200 p-3"
          >
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={
                selectedNode
                  ? 'Describe how to edit from the selected node'
                  : 'Select a node to edit, or ask to create a new workflow'
              }
              disabled={isLoading || isReadOnly}
              className="min-h-20 w-full resize-none rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-slate-500 disabled:bg-slate-100"
            />
            {selectedNode && (
              <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                Target: {selectedNodeTitle}
              </div>
            )}
            <div className="mt-2 flex items-center gap-2">
              <button
                type="submit"
                disabled={isLoading || !prompt.trim() || isReadOnly}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                Generate
              </button>
              <button
                type="button"
                onClick={handleApply}
                disabled={!canApply}
                className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Sparkles className="h-4 w-4" />
                Apply
              </button>
            </div>
            {isReadOnly && (
              <div className="mt-2 text-xs text-slate-500">
                Read-only access. Workflow drafts cannot be applied.
              </div>
            )}
          </form>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="pointer-events-auto inline-flex h-11 w-11 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-lg transition-colors hover:bg-slate-50"
          aria-label="Open workflow agent"
        >
          <MessageSquarePlus className="h-5 w-5" />
        </button>
      )}
    </div>
  );
}
