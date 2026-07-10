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

export type AgentBuilderMissingParameter = {
  key: string;
  label: string;
};

export type AgentBuilderNodeConfigurationIssue = {
  node_id: string;
  node_type: string;
  node_label: string;
  capability: string;
  missing_parameters: AgentBuilderMissingParameter[];
};

export type AgentBuilderEditTargetReference = {
  reference_type: 'natural_language_node' | 'selected_node' | 'selected_edge';
  query?: string | null;
  capabilities: string[];
  node_types: string[];
};

export type AgentBuilderEditOperation = {
  operation_id: string;
  operation: 'insert';
  placement: 'before' | 'after' | 'between';
  step_refs: string[];
  target: AgentBuilderEditTargetReference;
};

export type AgentBuilderStructuredRequest = {
  request_type:
    | 'new_workflow'
    | 'modify_workflow'
    | 'clarification'
    | 'unsupported'
    | 'validation_failure';
  draft_mode: 'new_workflow' | 'modify_workflow' | 'replace_workflow';
  intent_summary: string;
  planned_steps: Array<Record<string, unknown>>;
  knowledge_requirements: Array<Record<string, unknown>>;
  required_capabilities: string[];
  pending_resolution: Array<Record<string, unknown>>;
  edit_operations: AgentBuilderEditOperation[];
  missing_information: string[];
  unsupported_requests: string[];
  risk_flags: string[];
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
  configuration_issues?: AgentBuilderNodeConfigurationIssue[];
};

export type AgentBuilderSessionResponse = {
  session_id: string;
  workflow_id?: string | null;
  app_id?: string | null;
  status: string;
  messages: AgentBuilderSessionMessage[];
  pending_request?: Record<string, unknown> | null;
  draft_preview?: AgentBuilderDraftPreview | null;
};

export type AgentBuilderSessionMessage =
  | AgentBuilderMessageResponse
  | {
      kind: 'user';
      request_id: string;
      content: string;
      redacted?: boolean;
    }
  | {
      kind: 'assistant';
      request_id: string;
      response: AgentBuilderMessageResponse;
    };

export type AgentBuilderMessageResponse = {
  request_id: string;
  status: AgentBuilderStatus;
  structured_request?: AgentBuilderStructuredRequest | null;
  clarification_questions: string[];
  clarification_options: Array<Record<string, unknown>>;
  draft_preview?: AgentBuilderDraftPreview | null;
  validation_result?: AgentBuilderValidationResult | null;
  preview_prompt?: string | null;
  warnings: string[];
};

export type AgentBuilderKnowledgeCandidateSelection = {
  candidate_id: string;
  resolution_id?: string | null;
  requirement_id?: string | null;
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
  layout_optimization_applied: boolean;
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
      selectedKnowledgeCandidate?: AgentBuilderKnowledgeCandidateSelection | null;
      selectedKnowledgeCandidates?: AgentBuilderKnowledgeCandidateSelection[] | null;
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
        selected_knowledge_candidate: input.selectedKnowledgeCandidate ?? undefined,
        selected_knowledge_candidates: input.selectedKnowledgeCandidates ?? undefined,
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
