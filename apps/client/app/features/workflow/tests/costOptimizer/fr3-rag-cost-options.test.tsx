import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { getNodeDefinition } from '../../config/nodeRegistry';
import { LLMReferenceSidePanel } from '../../components/nodes/llm/components/LLMReferenceSidePanel';
import type { LLMNodeData } from '../../types/Nodes';

vi.mock('@/app/features/workflow/store/useWorkflowStore', () => ({
  useWorkflowStore: () => ({
    updateNodeData: vi.fn(),
  }),
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: {
    getKnowledgeBase: vi.fn(),
  },
}));

vi.mock('@/app/features/workflow/utils/llmKnowledgeBaseSelection', () => ({
  fetchEligibleKnowledgeBases: vi.fn().mockResolvedValue({
    bases: [],
    detailsById: {},
  }),
  sanitizeSelectedKnowledgeBases: (selected: unknown) => selected,
  isSameKnowledgeSelection: () => true,
}));

const baseData: LLMNodeData = {
  title: 'LLM',
  provider: 'openai',
  model_id: 'gpt-4.1',
  system_prompt: 'system',
  user_prompt: 'user',
  assistant_prompt: '',
  referenced_variables: [],
  parameters: {},
  knowledgeBases: [],
  topK: 3,
  scoreThreshold: 0.5,
};

describe('FR-003 RAG cost optimization options', () => {
  afterEach(() => {
    cleanup();
  });

  it('새 LLM 노드는 RAG 비용 최적화 옵션 기본값을 가진다', () => {
    const llmNodeDefinition = getNodeDefinition('llm');
    const defaultData = llmNodeDefinition?.defaultData?.() as LLMNodeData;

    expect(defaultData).toEqual(
      expect.objectContaining({
        dedupeRetrievedContext: false,
        retrievedContextMaxChars: undefined,
        retrievedContextCompression: 'off',
        answerGroundingCheck: 'off',
      }),
    );
  });

  it('지식 베이스 탭에서 RAG 비용 최적화 옵션을 편집한다', async () => {
    const onDataChange = vi.fn();

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={baseData}
        onClose={vi.fn()}
        embedded
        onDataChange={onDataChange}
      />,
    );

    await waitFor(() => expect(screen.getByText('비용 최적화')).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole('checkbox', { name: /중복 근거 제거/ }),
    );
    expect(onDataChange).toHaveBeenCalledWith({
      dedupeRetrievedContext: true,
    });

    fireEvent.change(screen.getByLabelText('참조 문서 길이 제한'), {
      target: { value: '6000' },
    });
    expect(onDataChange).toHaveBeenCalledWith({
      retrievedContextMaxChars: 6000,
    });

    fireEvent.change(screen.getByLabelText('검색 문서 압축'), {
      target: { value: 'light' },
    });
    expect(onDataChange).toHaveBeenCalledWith({
      retrievedContextCompression: 'light',
    });

    fireEvent.change(screen.getByLabelText('답변 근거 확인'), {
      target: { value: 'basic' },
    });
    expect(onDataChange).toHaveBeenCalledWith({
      answerGroundingCheck: 'basic',
    });
  });
});
