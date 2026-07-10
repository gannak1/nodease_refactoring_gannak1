import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  AgentBuilderPreviewNode,
  AgentBuilderPreviewNodeDetail,
  resolveAgentBuilderDisplayedGraph,
} from './NodeCanvas';

vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>(
    '@xyflow/react',
  );
  return {
    ...actual,
    Handle: () => <span data-testid="preview-handle" />,
  };
});

describe('NodeCanvas Agent Builder preview boundary', () => {
  it('renders an Answer preview card without internal output mappings', () => {
    render(
      <AgentBuilderPreviewNode
        {...({
          id: 'answer',
          type: 'answerNode',
          data: {
            title: 'Answer',
            outputs: ['internal-output-variable'],
            value_selector: ['llm', 'text'],
          },
        } as never)}
      />,
    );

    expect(screen.getByText('Answer')).toBeTruthy();
    expect(screen.getByText('읽기 전용 도안')).toBeTruthy();
    expect(screen.queryByText('internal-output-variable')).toBeNull();
    expect(screen.queryByText('value_selector')).toBeNull();
  });

  it('renders Node Detail as read-only data with only a close action', () => {
    const onClose = vi.fn();
    render(
      <AgentBuilderPreviewNodeDetail
        detail={{
          node_id: 'answer',
          node_type: 'answerNode',
          output_mapping: { source: 'llm.text' },
          validation_state: 'valid',
        }}
        onClose={onClose}
      />,
    );

    expect(screen.getByText('Node Detail')).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('selects preview nodes and edges without mutating the actual graph', () => {
    const actualNodes = [{ id: 'actual-node' }];
    const actualEdges = [{ id: 'actual-edge' }];
    const previewNodes = [{ id: 'preview-node' }];
    const previewEdges = [{ id: 'preview-edge' }];

    const displayed = resolveAgentBuilderDisplayedGraph(
      actualNodes,
      actualEdges,
      {
        previewGraph: { nodes: previewNodes, edges: previewEdges },
      },
    );

    expect(displayed).toEqual({ nodes: previewNodes, edges: previewEdges });
    expect(actualNodes).toEqual([{ id: 'actual-node' }]);
    expect(actualEdges).toEqual([{ id: 'actual-edge' }]);
  });
});
