import { agentBuilderApi } from '../../api/agentBuilderApi';
import { workflowApi } from '../../api/workflowApi';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import type {
  Edge,
  Node,
  Viewport,
  WorkflowDraftSaveRequest,
} from '../../types/Workflow';
import {
  applyAgentBuilderOperations,
  type AgentBuilderGraphMutation,
} from './agentBuilderGraphMutation';

const withoutEditorOnlyNodeData = (nodes: Node[]): Node[] =>
  nodes.map((node) => {
    const sanitized = structuredClone(node) as Node;
    const data = { ...(sanitized.data as Record<string, unknown>) };
    delete data.displayNumber;
    return { ...sanitized, data } as Node;
  });

export const applyAndSaveAgentBuilderMutation = async (input: {
  sessionId: string;
  workflowId: string;
  viewport: Viewport;
  mutation: AgentBuilderGraphMutation & {
    base_graph_hash: string;
    expected_workflow_updated_at: string;
  };
}) => {
  const store = useWorkflowStore.getState();
  store.setAgentBuilderMutationSaving(true);
  let applied = false;
  let persisted = false;
  let ambiguousSave = false;
  try {
    const canonical = await workflowApi.getDraftWorkflow(input.workflowId);
    store.ingestCanonicalDraftMetadata(canonical, input.workflowId);
    if (!Array.isArray(canonical?.nodes) || !Array.isArray(canonical?.edges)) {
      throw new Error('Agent Builder canonical base graph is unavailable');
    }
    const canonicalNodes = canonical.nodes as Node[];
    const canonicalEdges = canonical.edges as Edge[];
    const revertGraph = {
      nodes: structuredClone(
        canonicalNodes.filter((node) => node.type !== 'note'),
      ),
      edges: structuredClone(canonicalEdges),
    };
    const mutationResult = applyAgentBuilderOperations(
      revertGraph.nodes,
      revertGraph.edges,
      input.mutation.operations,
    );
    store.applyAgentBuilderGraphMutation(input.mutation, input.sessionId, {
      nodes: revertGraph.nodes,
      edges: revertGraph.edges,
    });
    applied = true;
    const current = useWorkflowStore.getState();
    const saveRequest: WorkflowDraftSaveRequest = {
      // displayNumber is a screen-only label and must not affect CAS hashes.
      nodes: withoutEditorOnlyNodeData(
        mutationResult.nodes.filter((node) => node.type !== 'note'),
      ),
      edges: mutationResult.edges,
      viewport: input.viewport,
      features: {
        ...current.features,
        noteNodes: current.nodes.filter((node) => node.type === 'note'),
      },
      envVariables: current.envVariables,
      runtimeVariables: current.runtimeVariables,
      expected_graph_hash: canonical.graph_hash,
      expected_updated_at: canonical.updated_at,
      mutation_context: {
        operation_id: input.mutation.operation_id,
        action: 'apply',
        expected_base_graph_hash: input.mutation.base_graph_hash,
        expected_workflow_updated_at:
          input.mutation.expected_workflow_updated_at,
        catalog_version: 3,
      },
    };
    const save = () =>
      workflowApi.syncDraftWorkflow(input.workflowId, saveRequest);
    let saveResult: { graph_hash: string; updated_at: string } | null = null;
    try {
      saveResult = await save();
    } catch {
      try {
        saveResult = await save();
      } catch (retryError) {
        let confirmedUnsaved = false;
        let recoveredCanonical = false;
        try {
          const session = await agentBuilderApi.getSession(input.sessionId);
          const active = session.active_graph_mutation as
            | Record<string, unknown>
            | null
            | undefined;
          const sameOperation =
            active?.operation_id === input.mutation.operation_id;
          const resultGraphHash = active?.result_graph_hash;
          const savedWorkflowUpdatedAt = active?.saved_workflow_updated_at;
          const expectedResultMatches =
            !input.mutation.expected_result_graph_hash ||
            resultGraphHash === input.mutation.expected_result_graph_hash;
          if (
            sameOperation &&
            (active?.status === 'pending_ack' ||
              active?.status === 'acknowledged') &&
            typeof resultGraphHash === 'string' &&
            typeof savedWorkflowUpdatedAt === 'string' &&
            expectedResultMatches
          ) {
            saveResult = {
              graph_hash: resultGraphHash,
              updated_at: savedWorkflowUpdatedAt,
            };
            recoveredCanonical = true;
          } else if (sameOperation && active?.status === 'blocked') {
            confirmedUnsaved = true;
          }
        } catch {
          // The canonical workflow reload below is the remaining recovery path.
        }
        if (!recoveredCanonical && !confirmedUnsaved) {
          try {
            const canonical = await workflowApi.getDraftWorkflow(
              input.workflowId,
            );
            useWorkflowStore
              .getState()
              .ingestCanonicalDraftMetadata(canonical, input.workflowId);
            if (
              canonical?.graph_hash ===
                input.mutation.expected_result_graph_hash &&
              typeof canonical.updated_at === 'string'
            ) {
              saveResult = {
                graph_hash: canonical.graph_hash,
                updated_at: canonical.updated_at,
              };
              recoveredCanonical = true;
            } else if (
              canonical?.graph_hash === input.mutation.base_graph_hash &&
              canonical.updated_at === input.mutation.expected_workflow_updated_at
            ) {
              confirmedUnsaved = true;
            } else if (canonical) {
              useWorkflowStore
                .getState()
                .ingestCanonicalDraftMetadata(canonical, input.workflowId);
              ambiguousSave = true;
            }
          } catch {
            ambiguousSave = true;
          }
        }
        if (confirmedUnsaved) {
          useWorkflowStore.getState().rollbackLatestAgentBuilderGraphMutation();
          applied = false;
        }
        if (!recoveredCanonical) throw retryError;
      }
    }
    if (!saveResult) {
      throw new Error('Agent Builder canonical save result is unavailable');
    }
    useWorkflowStore
      .getState()
      .ingestCanonicalDraftMetadata(saveResult, input.workflowId);
    persisted = true;
    useWorkflowStore.getState().markLatestAgentBuilderMutationPersisted({
      operationId: input.mutation.operation_id,
      resultGraphHash: saveResult.graph_hash,
      workflowUpdatedAt: saveResult.updated_at,
      sessionId: input.sessionId,
      revertGraph,
    });
    useWorkflowStore.getState().setHasUnsavedChanges(false);
    const acknowledgementRequest = {
      operationId: input.mutation.operation_id,
      workflowId: input.workflowId,
      graphHash: saveResult.graph_hash,
      workflowUpdatedAt: saveResult.updated_at,
    };
    let acknowledgement;
    let recoveredSession: Awaited<
      ReturnType<typeof agentBuilderApi.getSession>
    > | null = null;
    try {
      acknowledgement = await agentBuilderApi.acknowledgeMutation(
        input.sessionId,
        acknowledgementRequest,
      );
    } catch {
      try {
        acknowledgement = await agentBuilderApi.acknowledgeMutation(
          input.sessionId,
          acknowledgementRequest,
        );
      } catch (retryError) {
        const [sessionResult, canonicalResult] = await Promise.allSettled([
          agentBuilderApi.getSession(input.sessionId),
          workflowApi.getDraftWorkflow(input.workflowId),
        ]);
        if (
          sessionResult.status !== 'fulfilled' ||
          canonicalResult.status !== 'fulfilled' ||
          !sessionResult.value ||
          !canonicalResult.value
        ) {
          throw retryError;
        }
        const active = sessionResult.value.active_graph_mutation as
          | Record<string, unknown>
          | null
          | undefined;
        const canonical = canonicalResult.value;
        useWorkflowStore
          .getState()
          .ingestCanonicalDraftMetadata(canonical, input.workflowId);
        const acknowledged =
          active?.operation_id === input.mutation.operation_id &&
          active?.status === 'acknowledged' &&
          active?.result_graph_hash === saveResult.graph_hash &&
          active?.saved_workflow_updated_at === saveResult.updated_at &&
          canonical.graph_hash === saveResult.graph_hash &&
          canonical.updated_at === saveResult.updated_at;
        if (!acknowledged) throw retryError;
        recoveredSession = sessionResult.value;
        const completionContext = active?.completion_context as
          | Record<string, unknown>
          | undefined;
        acknowledgement = {
          operation_id: input.mutation.operation_id,
          operation_status: 'acknowledged' as const,
          graph_hash: saveResult.graph_hash,
          updated_at: saveResult.updated_at,
          parameter_group: sessionResult.value.parameter_group ?? null,
          completed_task_id:
            typeof completionContext?.parameter_task_id === 'string'
              ? completionContext.parameter_task_id
              : null,
          completed_knowledge_resolution_id:
            typeof completionContext?.knowledge_resolution_id === 'string'
              ? completionContext.knowledge_resolution_id
              : null,
          next_task_id: null,
        };
      }
    }
    if (!recoveredSession) {
      try {
        recoveredSession = await agentBuilderApi.getSession(input.sessionId);
      } catch {
        recoveredSession = null;
      }
    }
    useWorkflowStore.getState().markLatestAgentBuilderMutationAcknowledged(
      input.mutation.operation_id,
      recoveredSession?.status === 'completed',
    );
    return { ...saveResult, acknowledgement, session: recoveredSession };
  } catch (error) {
    if (applied && !persisted && !ambiguousSave) {
      useWorkflowStore.getState().rollbackLatestAgentBuilderGraphMutation();
    }
    throw error;
  } finally {
    useWorkflowStore.getState().setAgentBuilderMutationSaving(false);
  }
};
