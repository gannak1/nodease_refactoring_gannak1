import type { Edge, Viewport } from '../types/Workflow';
import type { Node } from '../types/Nodes';

export type WorkflowBuilderStatus =
  | 'ready'
  | 'needs_input'
  | 'invalid'
  | 'error';

export type WorkflowBuilderMode = 'openai' | 'heuristic';

export type WorkflowBuilderGraph = {
  nodes: Node[];
  edges: Edge[];
  viewport: Viewport;
};

export type WorkflowBuilderSelectedNode = {
  id: string;
  type: string;
  title: string;
  reason: string;
};

export type WorkflowBuilderPlan = {
  trigger?: 'manual' | 'jira' | 'schedule' | 'existing';
  actions?: Array<
    | 'github'
    | 'mail'
    | 'http'
    | 'knowledge'
    | 'guardrail'
    | 'llm'
    | 'template'
    | 'slack'
    | 'answer'
  >;
  missing_fields?: string[];
  questions?: string[];
  message?: string;
};

export type WorkflowBuilderRequest = {
  prompt: string;
  workflowId?: string;
  graph?: Partial<WorkflowBuilderGraph>;
  selectedNodeId?: string | null;
};

export type WorkflowBuilderResponse = {
  status: WorkflowBuilderStatus;
  mode: WorkflowBuilderMode;
  message: string;
  graph_preview: WorkflowBuilderGraph | null;
  selected_nodes: WorkflowBuilderSelectedNode[];
  missing_fields: string[];
  questions: string[];
  validation_errors: string[];
  validation_warnings: string[];
  warnings: string[];
};
