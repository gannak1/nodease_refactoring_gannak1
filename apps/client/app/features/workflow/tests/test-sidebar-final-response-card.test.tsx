import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  FinalResponseCard,
  TestSidebar,
  TEST_INPUT_CLASS_NAME,
} from '../components/editor/TestSidebar';
import type { FinalResponsePreview } from '../utils/testExecutionFinalResponse';

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    setCenter: vi.fn(),
    getViewport: vi.fn(() => ({ zoom: 1 })),
  }),
}));

vi.mock('../store/useWorkflowStore', () => {
  const state = {
    isTestPanelOpen: true,
    toggleTestPanel: vi.fn(),
    nodes: [
      {
        id: 'start',
        type: 'startNode',
        data: {
          variables: [
            {
              id: 'question-variable',
              name: 'question',
              label: '질문',
              type: 'paragraph',
              required: false,
              placeholder: '질문을 입력하세요',
            },
          ],
        },
      },
    ],
    activeWorkflowId: 'workflow-1',
    setNodes: vi.fn(),
    updateNodeData: vi.fn(),
    workflowAccess: { can_execute: true },
    edges: [],
    features: {},
    envVariables: [],
    runtimeVariables: [],
    testExecutionStatus: 'idle',
    testExecutionStartedAt: null,
    testExecutionFinishedAt: null,
    testExecutionResult: null,
    testNodeResults: [],
    testExecutionError: null,
    currentExecutingNodeId: null,
    isTestUploading: false,
    beginTestExecution: vi.fn(),
    setTestUploading: vi.fn(),
    setCurrentExecutingNode: vi.fn(),
    addTestNodeResult: vi.fn(),
    finishTestExecution: vi.fn(),
    failTestExecution: vi.fn(),
    resetTestExecution: vi.fn(),
  };
  const useWorkflowStore = Object.assign(vi.fn(() => state), {
    getState: vi.fn(() => state),
  });
  return { useWorkflowStore };
});

afterEach(() => {
  cleanup();
});

describe('TestSidebar final response card', () => {
  it('테스트 입력 필드는 다크 모드에서도 입력값과 placeholder 색상을 명시한다', () => {
    expect(TEST_INPUT_CLASS_NAME).toContain('text-gray-900');
    expect(TEST_INPUT_CLASS_NAME).toContain('placeholder:text-gray-400');
    expect(TEST_INPUT_CLASS_NAME).toContain('dark:text-gray-100');
    expect(TEST_INPUT_CLASS_NAME).toContain('dark:placeholder:text-gray-500');
  });

  it('테스트 실행 패널 textarea에 다크 모드 입력 class를 실제 적용한다', () => {
    render(<TestSidebar />);

    const textarea = screen.getByPlaceholderText('질문을 입력하세요');

    expect(textarea).toHaveClass('text-gray-900');
    expect(textarea).toHaveClass('dark:text-gray-100');
    expect(textarea).toHaveClass('placeholder:text-gray-400');
    expect(textarea).toHaveClass('dark:placeholder:text-gray-500');
    expect(
      screen.getByRole('button', { name: /테스트 실행하기/ }),
    ).toBeVisible();
  });

  it('최종 사용자가 받는 text 응답을 별도 카드로 표시한다', () => {
    render(
      <FinalResponseCard
        preview={{
          kind: 'text',
          text: '개발팀 커밋 컨벤션은 feat: 설명 형식입니다.',
          isEmpty: false,
          sourceLabel: '정책 답변 LLM',
        }}
      />,
    );

    expect(screen.getByRole('heading', { name: '최종 응답' })).toBeVisible();
    expect(screen.getByText('정책 답변 LLM')).toBeVisible();
    expect(
      screen.getByText('개발팀 커밋 컨벤션은 feat: 설명 형식입니다.'),
    ).toBeVisible();
  });

  it('JSON 응답은 raw dump 대신 필드 preview로 표시한다', () => {
    const preview: FinalResponsePreview = {
      kind: 'json',
      items: [
        { label: 'summary', value: '온보딩 절차 안내' },
        { label: 'next_steps', value: '2개 항목' },
      ],
      text: 'summary: 온보딩 절차 안내\nnext_steps: 2개 항목',
      isEmpty: false,
      sourceLabel: '워크플로우 최종 출력',
    };

    render(<FinalResponseCard preview={preview} />);

    expect(screen.getByText('summary')).toBeVisible();
    expect(screen.getByText('온보딩 절차 안내')).toBeVisible();
    expect(screen.getByText('next_steps')).toBeVisible();
    expect(screen.getByText('2개 항목')).toBeVisible();
    expect(screen.queryByText(/"summary"/)).not.toBeInTheDocument();
  });

  it('빈 최종 응답은 empty state를 표시한다', () => {
    render(
      <FinalResponseCard
        preview={{
          kind: 'text',
          text: '',
          isEmpty: true,
          sourceLabel: '실행 결과',
        }}
      />,
    );

    expect(
      screen.getByText('최종 사용자에게 표시할 응답이 비어 있습니다.'),
    ).toBeVisible();
  });
});
