import { apiClient } from '@/lib/apiClient';
import type { Edge, Node } from '@xyflow/react';

export type AgentBuilderStatus =
  | 'draft_ready'
  | 'clarification_required'
  | 'validation_failed'
  | 'unsupported'
  | 'configuration_required'
  | 'failed'
  | 'canceled';

export type AgentBuilderGraph = {
  nodes: Node[];
  edges: Edge[];
  viewport?: { x: number; y: number; zoom: number };
};

export type AgentBuilderValidationResult = {
  valid: boolean;
  issues: Array<{ code: string; message: string; path?: string | null }>;
};

export type AgentBuilderDraftPreview = {
  draft_id: string;
  preview_graph: AgentBuilderGraph;
  base_graph_hash?: string | null;
  base_workflow_updated_at?: string | null;
  draft_mode: 'new_workflow' | 'modify_workflow' | 'replace_workflow';
  node_detail_previews: Array<Record<string, unknown>>;
  validation_result: AgentBuilderValidationResult;
  safety_notices: string[];
};

export type AgentBuilderSessionResponse = {
  session_id: string;
  workflow_id?: string | null;
  app_id?: string | null;
  status: string;
  messages: Array<Record<string, unknown>>;
  pending_request?: Record<string, unknown> | null;
  draft_preview?: Record<string, unknown> | null;
};

export type AgentBuilderMessageResponse = {
  request_id: string;
  status: AgentBuilderStatus;
  structured_request?: Record<string, unknown> | null;
  clarification_questions: string[];
  draft_preview?: AgentBuilderDraftPreview | null;
  validation_result?: AgentBuilderValidationResult | null;
  preview_prompt?: string | null;
  warnings: string[];
};

export type AgentBuilderApplyResponse = {
  apply_id: string;
  outcome: 'saved' | 'blocked' | 'canceled' | 'failed';
  saved_workflow_id?: string | null;
  latest_graph_hash?: string | null;
  latest_workflow_updated_at?: string | null;
  block_reason?: string | null;
  failure_reason?: string | null;
  stale_state: string;
  permission_recheck_outcome: string;
  validation_state: string;
  audit_recorded: boolean;
  notices: string[];
};

export const agentBuilderApi = {
  async createSession(input: {
    workflowId?: string | null;
    appId?: string | null;
  }): Promise<AgentBuilderSessionResponse> {
    const response = await apiClient.post('/agent-builder/sessions', {
      workflow_id: input.workflowId ?? undefined,
      app_id: input.appId ?? undefined,
    });
    return response.data;
  },

  async getSession(sessionId: string): Promise<AgentBuilderSessionResponse> {
    const response = await apiClient.get(`/agent-builder/sessions/${sessionId}`);
    return response.data;
  },

  async sendMessage(
    sessionId: string,
    input: {
      message: string;
      workflowId?: string | null;
      appId?: string | null;
      selectedNodeId?: string | null;
      selectedEdgeId?: string | null;
    },
  ): Promise<AgentBuilderMessageResponse> {
    const response = await apiClient.post(
      `/agent-builder/sessions/${sessionId}/messages`,
      {
        message: input.message,
        workflow_id: input.workflowId ?? undefined,
        app_id: input.appId ?? undefined,
        selected_node_id: input.selectedNodeId ?? undefined,
        selected_edge_id: input.selectedEdgeId ?? undefined,
      },
    );
    return response.data;
  },

  async cancelRequest(requestId: string): Promise<AgentBuilderMessageResponse> {
    const response = await apiClient.post(
      `/agent-builder/requests/${requestId}/cancel`,
    );
    return response.data;
  },

  async recordPreviewOpened(draftId: string): Promise<void> {
    await apiClient.post(`/agent-builder/drafts/${draftId}/preview-opened`);
  },

  async applyDraft(
    draftId: string,
    input: {
      clientPreviewGraphHash?: string | null;
      clientLatestGraphHash?: string | null;
    },
  ): Promise<AgentBuilderApplyResponse> {
    const response = await apiClient.post(
      `/agent-builder/drafts/${draftId}/apply`,
      {
        action: 'apply_and_save',
        client_preview_graph_hash: input.clientPreviewGraphHash,
        client_latest_graph_hash: input.clientLatestGraphHash,
      },
    );
    return response.data;
  },

  async cancelDraft(draftId: string): Promise<AgentBuilderApplyResponse> {
    const response = await apiClient.post(
      `/agent-builder/drafts/${draftId}/apply`,
      { action: 'cancel' },
    );
    return response.data;
  },
};
