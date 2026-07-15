import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AgentBuilderParameterTask } from '../../api/agentBuilderApi';
import { ParameterInputRenderer } from './ParameterInputRenderer';
import {
  deriveParameterControlHydration,
  parameterControlDisplayValue,
} from './parameterControlHydration';

const branchTask: AgentBuilderParameterTask = {
  task_id: 'task-condition-default',
  group_id: 'group-1',
  step_id: 'step-condition',
  node_id: 'condition',
  node_type: 'conditionNode',
  parameter_key: 'condition_branch:default',
  label: '기본 분기 연결',
  input_type: 'select',
  required: true,
  defer_policy: 'forbidden',
  status: 'active',
  task_version: 1,
  stable_order: 0,
  resolution_source: null,
  reason: '조건 분기가 실행될 다음 노드를 확인합니다.',
  input_guidance: '기존 노드를 선택하거나 연결 안 함을 명시하세요.',
  node_label: '조건',
  node_purpose: '조건 결과에 따라 다음 단계를 선택합니다.',
  configuration_state: 'unresolved',
  validation: {
    options: ['answer-node', '__agent_builder_no_connection__'],
    option_labels: {
      'answer-node': '응답 노드',
      __agent_builder_no_connection__: '연결 안 함',
    },
  },
  suggestions: [],
  candidates: [],
};

describe('ParameterInputRenderer condition branch target', () => {
  it('shows safe option labels while submitting the canonical target id', () => {
    const onSubmit = vi.fn();
    render(<ParameterInputRenderer task={branchTask} onSubmit={onSubmit} />);

    expect(screen.getByRole('option', { name: '응답 노드' })).toHaveValue(
      'answer-node',
    );
    expect(screen.getByRole('option', { name: '연결 안 함' })).toHaveValue(
      '__agent_builder_no_connection__',
    );

    fireEvent.change(screen.getByLabelText('기본 분기 연결'), {
      target: { value: 'answer-node' },
    });
    fireEvent.click(screen.getByRole('button'));

    expect(onSubmit).toHaveBeenCalledWith('answer-node');
  });

  it('hydrates an existing target and explicit no-connection from node data', () => {
    const targetHydration = deriveParameterControlHydration(branchTask, {
      _agent_builder_condition_branch_targets: { default: 'answer-node' },
    });
    const emptyHydration = deriveParameterControlHydration(branchTask, {
      _agent_builder_condition_branch_targets: { default: null },
    });

    expect(targetHydration).toEqual({ state: 'available', value: 'answer-node' });
    expect(parameterControlDisplayValue(branchTask, targetHydration)).toBe(
      '응답 노드',
    );
    expect(emptyHydration).toEqual({
      state: 'available',
      value: '__agent_builder_no_connection__',
    });
    expect(parameterControlDisplayValue(branchTask, emptyHydration)).toBe(
      '연결 안 함',
    );
  });
});
