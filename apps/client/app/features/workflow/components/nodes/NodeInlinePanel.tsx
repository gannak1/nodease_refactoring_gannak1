import { DragEvent } from 'react';

import { AppNode } from '../../types/Nodes';
import {
  NODE_OUTPUT_DRAG_MIME,
  applyDroppedOutputToNodeData,
  parseDraggedOutput,
} from '../../utils/nodeVariablePorts';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { StartNodePanel } from './start/components/StartNodePanel';
import { AnswerNodePanel } from './answer/components/AnswerNodePanel';
import { HttpRequestNodePanel } from './http/components/HttpRequestNodePanel';
import { SlackPostNodePanel } from './slack/components/SlackPostNodePanel';
import { CodeNodePanel } from './code/components/CodeNodePanel';
import { ConditionNodePanel } from './condition/components/ConditionNodePanel';
import { LLMNodePanel } from './llm/components/LLMNodePanel';
import { TemplateNodePanel } from './template/components/TemplateNodePanel';
import { WorkflowNodePanel } from './workflow/components/WorkflowNodePanel';
import { FileExtractionNodePanel } from './file_extraction/components/FileExtractionNodePanel';
import { VariableExtractionNodePanel } from './variable_extraction/components/VariableExtractionNodePanel';
import { WebhookTriggerNodePanel } from './webhook/components/WebhookTriggerNodePanel';
import { ScheduleTriggerNodePanel } from './schedule/components/ScheduleTriggerNodePanel';
import { GithubNodePanel } from './github/components/GithubNodePanel';
import { MailNodePanel } from './mail/components/MailNodePanel';
import { LoopNodePanel } from './loop/components/LoopNodePanel';
import { VisiblePropertiesControl } from './VisiblePropertiesControl';

const isPanelSupported = (node: AppNode) =>
  node.type !== 'note' && node.type !== undefined;

const getTextDropTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return null;

  const textField = target.closest('textarea, input');
  if (!(textField instanceof HTMLElement)) return null;
  if (textField.dataset.variableDropDisabled) {
    return null;
  }
  if (!textField.dataset.variableDropEnabled) {
    return null;
  }

  if (
    textField instanceof HTMLTextAreaElement ||
    textField instanceof HTMLInputElement
  ) {
    const disallowedInputTypes = new Set([
      'checkbox',
      'radio',
      'range',
      'file',
      'color',
      'date',
      'datetime-local',
      'month',
      'time',
      'week',
    ]);

    if (
      textField instanceof HTMLInputElement &&
      disallowedInputTypes.has(textField.type)
    ) {
      return null;
    }

    return textField;
  }

  return null;
};

const insertTokenIntoTextField = (
  textField: HTMLInputElement | HTMLTextAreaElement,
  token: string,
) => {
  const selectionStart = textField.selectionStart ?? textField.value.length;
  const selectionEnd = textField.selectionEnd ?? selectionStart;
  const nextValue = `${textField.value.slice(0, selectionStart)}${token}${textField.value.slice(selectionEnd)}`;
  const valueSetter = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(textField),
    'value',
  )?.set;

  valueSetter?.call(textField, nextValue);
  textField.dispatchEvent(new Event('input', { bubbles: true }));

  const nextCursor = selectionStart + token.length;
  window.setTimeout(() => {
    textField.focus();
    textField.setSelectionRange(nextCursor, nextCursor);
  }, 0);
};

const NodePanelBody = ({ node }: { node: AppNode }) => {
  if (node.type === 'startNode') {
    return <StartNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'answerNode') {
    return <AnswerNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'httpRequestNode') {
    return <HttpRequestNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'slackPostNode') {
    return <SlackPostNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'codeNode') {
    return <CodeNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'conditionNode') {
    return <ConditionNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'llmNode') {
    return <LLMNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'templateNode') {
    return <TemplateNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'workflowNode') {
    return <WorkflowNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'fileExtractionNode') {
    return <FileExtractionNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'variableExtractionNode') {
    return <VariableExtractionNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'webhookTrigger') {
    return <WebhookTriggerNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'scheduleTrigger') {
    return <ScheduleTriggerNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'githubNode') {
    return <GithubNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'mailNode') {
    return <MailNodePanel nodeId={node.id} data={node.data} />;
  }
  if (node.type === 'loopNode') {
    return <LoopNodePanel nodeId={node.id} data={node.data} />;
  }

  return (
    <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 p-4 text-xs text-gray-500">
      이 노드는 아직 내부 편집 패널을 제공하지 않습니다.
    </div>
  );
};

export const NodeInlinePanel = ({ node }: { node: AppNode }) => {
  const updateNodeData = useWorkflowStore((state) => state.updateNodeData);

  if (!isPanelSupported(node)) return null;

  const handleTextFieldDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(NODE_OUTPUT_DRAG_MIME)) return;
    if (!getTextDropTarget(event.target)) return;

    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleTextFieldDrop = (event: DragEvent<HTMLDivElement>) => {
    const textField = getTextDropTarget(event.target);
    if (!textField) return;

    const output = parseDraggedOutput(event.dataTransfer);
    if (!output || output.sourceNodeId === node.id) return;

    event.preventDefault();
    event.stopPropagation();

    insertTokenIntoTextField(textField, `{{${output.key}}}`);
    const patch = applyDroppedOutputToNodeData(node, output);
    if (patch) updateNodeData(node.id, patch);
  };

  return (
    <div
      className="nodrag nowheel mt-4 min-w-0 max-w-full overflow-hidden border-t border-gray-100 pt-4"
      onDragOverCapture={handleTextFieldDragOver}
      onDropCapture={handleTextFieldDrop}
    >
      <div className="min-w-0 max-w-full [&_*]:min-w-0 [&_input]:max-w-full [&_input]:text-gray-700 [&_input::placeholder]:text-gray-500 [&_select]:max-w-full [&_select]:text-gray-700 [&_textarea]:max-w-full [&_textarea]:text-gray-800 [&_textarea::placeholder]:text-gray-500">
        {node.type !== 'llmNode' && <VisiblePropertiesControl node={node} />}
        <NodePanelBody node={node} />
      </div>
    </div>
  );
};

export type { DraggedOutputVariable } from '../../utils/nodeVariablePorts';
