import type { DeploymentRunInfoResponse } from '../types/Deployment';
import {
  buildFinalResponsePreview,
  getFinalResponsePreview,
  type FinalResponsePreview,
} from './testExecutionFinalResponse';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export const getDeploymentRunFinalPreview = (
  deployment: DeploymentRunInfoResponse | null,
  runResponse: unknown,
): FinalResponsePreview => {
  const workflowResult =
    isRecord(runResponse) && 'results' in runResponse
      ? runResponse.results
      : runResponse;

  if (isRecord(workflowResult)) {
    for (const output of deployment?.output_schema?.outputs || []) {
      if (workflowResult[output.variable] !== undefined) {
        return buildFinalResponsePreview(
          workflowResult[output.variable],
          output.label || '워크플로우 최종 출력',
        );
      }
    }
  }

  return getFinalResponsePreview({
    workflowResult,
    nodeResults: [],
    nodes: [],
  });
};
