import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { getNodeDefinition } from '../../config/nodeRegistry';
import { NodeSettingsComparisonPanel } from '../../components/costOptimizer/NodeSettingsComparisonPanel';
import { LLMReferenceSidePanel } from '../../components/nodes/llm/components/LLMReferenceSidePanel';
import { fetchEligibleKnowledgeBases } from '@/app/features/workflow/utils/llmKnowledgeBaseSelection';
import type { CandidateDraft } from '../../components/costOptimizer/costOptimizerPlaygroundModel';
import type { LLMNodeData } from '../../types/Nodes';

const updateNodeDataMock = vi.hoisted(() => vi.fn());

vi.mock('@/app/features/workflow/store/useWorkflowStore', () => ({
  useWorkflowStore: () => ({
    updateNodeData: updateNodeDataMock,
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

const baseDraft: CandidateDraft = {
  model_id: 'gpt-4.1',
  fallback_model_id: '',
  auto_model_routing: false,
  model_routing_policy: undefined,
  task_type: 'generate',
  system_prompt: 'system',
  user_prompt: 'user',
  assistant_prompt: '',
  referenced_variables: [],
  max_tokens: 1024,
  temperature: 0.3,
  top_p: 1,
  presence_penalty: 0,
  frequency_penalty: 0,
  stop: [],
  output_format: 'text',
  json_schema_fields: [],
  knowledgeBases: [],
  topK: 3,
  scoreThreshold: 0.5,
  dedupeRetrievedContext: false,
  retrievedContextMaxChars: null,
  retrievedContextCompression: 'off',
  answerGroundingCheck: 'off',
};

describe('FR-003 RAG cost optimization options', () => {
  afterEach(() => {
    cleanup();
    updateNodeDataMock.mockClear();
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValue({
      bases: [],
      detailsById: {},
    });
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

    await waitFor(() =>
      expect(screen.getByText('비용 최적화')).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole('checkbox', { name: /중복 근거 제거/ }));
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

  it('일반 LLM 노드 지식 베이스 탭에서 선택한 RAG 연결을 노드 데이터에 반영한다', async () => {
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValueOnce({
      bases: [
        {
          id: 'kb-1',
          name: '제품 정책',
          description: '제품 정책 문서',
          document_count: 1,
          created_at: '2026-07-01T00:00:00Z',
          embedding_model: 'text-embedding-3-small',
        },
      ],
      detailsById: {},
    });

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={baseData}
        onClose={vi.fn()}
        embedded
      />,
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: /제품 정책/ }));

    expect(updateNodeDataMock).toHaveBeenCalledWith('llm-1', {
      knowledgeBases: [{ id: 'kb-1', name: '제품 정책' }],
    });
  });

  it('완료된 문서가 있는 KB가 없으면 RAG 선택 후보를 비워 안내한다', async () => {
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValueOnce({
      bases: [],
      detailsById: {},
      preserveSelectionIds: [],
    });

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={baseData}
        onClose={vi.fn()}
        embedded
      />,
    );

    expect(
      await screen.findByText('완료된 문서가 있는 지식 베이스가 없습니다.'),
    ).toBeInTheDocument();
  });

  it('읽기 전용 LLM 노드에서는 RAG 연결 선택을 변경하지 않는다', async () => {
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValueOnce({
      bases: [
        {
          id: 'kb-1',
          name: '제품 정책',
          description: '제품 정책 문서',
          document_count: 1,
          created_at: '2026-07-01T00:00:00Z',
          embedding_model: 'text-embedding-3-small',
        },
      ],
      detailsById: {},
    });

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={baseData}
        onClose={vi.fn()}
        embedded
        readOnly
      />,
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: /제품 정책/ }));

    expect(updateNodeDataMock).not.toHaveBeenCalled();
  });

  it('지식 베이스 목록 조회 실패 시 기존 RAG 연결을 지우지 않는다', async () => {
    vi.mocked(fetchEligibleKnowledgeBases).mockRejectedValueOnce(
      new Error('network failed'),
    );

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={{
          ...baseData,
          knowledgeBases: [{ id: 'kb-existing', name: '기존 정책' }],
        }}
        onClose={vi.fn()}
        embedded
      />,
    );

    expect(
      await screen.findByText('지식을 불러오지 못했습니다.'),
    ).toBeInTheDocument();
    expect(screen.getByText('선택됨:')).toBeInTheDocument();
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(updateNodeDataMock).not.toHaveBeenCalled();
  });

  it('특수문자가 포함된 지식 베이스 이름을 선택 payload에 보존한다', async () => {
    const kbName = 'R&D 정책 / 승인: <Beta>';
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValueOnce({
      bases: [
        {
          id: 'kb-special',
          name: kbName,
          description: '특수문자 이름 테스트',
          document_count: 2,
          created_at: '2026-07-01T00:00:00Z',
          embedding_model: 'text-embedding-3-small',
        },
      ],
      detailsById: {},
    });

    render(
      <LLMReferenceSidePanel
        nodeId="llm-1"
        data={baseData}
        onClose={vi.fn()}
        embedded
      />,
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: /R&D 정책/ }));

    expect(updateNodeDataMock).toHaveBeenCalledWith('llm-1', {
      knowledgeBases: [{ id: 'kb-special', name: kbName }],
    });
  });

  it('A/B 후보 지식 베이스 탭에서 지식 베이스를 선택한다', async () => {
    const onNodeDataChange = vi.fn();
    vi.mocked(fetchEligibleKnowledgeBases).mockResolvedValueOnce({
      bases: [
        {
          id: 'kb-1',
          name: 'HR 정책',
          description: '사내 HR 정책 문서',
          document_count: 1,
          created_at: '2026-07-01T00:00:00Z',
          embedding_model: 'text-embedding-3-small',
        },
      ],
      detailsById: {
        'kb-1': {
          id: 'kb-1',
          name: 'HR 정책',
          description: '사내 HR 정책 문서',
          document_count: 1,
          created_at: '2026-07-01T00:00:00Z',
          embedding_model: 'text-embedding-3-small',
          documents: [
            {
              id: 'doc-1',
              filename: 'hr-policy.md',
              status: 'completed',
              created_at: '2026-07-01T00:00:00Z',
              updated_at: '2026-07-01T00:00:00Z',
              chunk_count: 3,
              token_count: 240,
            },
          ],
        },
      },
    });

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="knowledge"
        onTabChange={vi.fn()}
        draft={baseDraft}
        onChange={vi.fn()}
        onNodeDataChange={onNodeDataChange}
      />,
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: /HR 정책/ }));

    expect(onNodeDataChange).toHaveBeenCalledWith({
      knowledgeBases: [{ id: 'kb-1', name: 'HR 정책' }],
    });
  });
});
