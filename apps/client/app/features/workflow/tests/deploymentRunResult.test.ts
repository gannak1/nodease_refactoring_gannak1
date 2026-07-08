import { describe, expect, it } from 'vitest';

import type { DeploymentRunInfoResponse } from '../types/Deployment';
import { getDeploymentRunFinalPreview } from '../utils/deploymentRunResult';

const deployment = {
  deployment_id: 'deployment-1',
  app_id: 'app-1',
  workflow_id: 'workflow-1',
  name: '사내 문서 질문 응답 봇',
  version: 1,
  type: 'chatbot',
  output_schema: {
    outputs: [{ variable: 'final_answer', label: '최종 답변' }],
  },
} as DeploymentRunInfoResponse;

describe('deployment run final preview', () => {
  it('workflow output이 있으면 최종 출력으로 표시한다', () => {
    const preview = getDeploymentRunFinalPreview(deployment, {
      status: 'success',
      results: {
        output: '개발팀 신입 연봉 기준은 사내 보상 밴드 문서를 따릅니다.',
      },
    });

    expect(preview.kind).toBe('text');
    expect(preview.text).toContain('개발팀 신입 연봉 기준');
    expect(preview.sourceLabel).toBe('워크플로우 최종 출력');
  });

  it('safe output schema의 출력 변수를 우선 표시한다', () => {
    const preview = getDeploymentRunFinalPreview(deployment, {
      status: 'success',
      results: {
        raw_llm_output: { answer: 'LLM 원본 답변' },
        final_answer: '최종 사용자 답변',
      },
    });

    expect(preview.kind).toBe('text');
    expect(preview.text).toBe('최종 사용자 답변');
    expect(preview.sourceLabel).toBe('최종 답변');
  });

  it('output schema의 앞 출력이 null이면 다음 출력 후보를 표시한다', () => {
    const preview = getDeploymentRunFinalPreview(
      {
        ...deployment,
        output_schema: {
          outputs: [
            { variable: 'empty_answer', label: '빈 답변' },
            { variable: 'final_answer', label: '최종 답변' },
          ],
        },
      },
      {
        status: 'success',
        results: {
          empty_answer: null,
          final_answer: '실제 최종 사용자 답변',
        },
      },
    );

    expect(preview.kind).toBe('text');
    expect(preview.text).toBe('실제 최종 사용자 답변');
    expect(preview.sourceLabel).toBe('최종 답변');
  });
});
