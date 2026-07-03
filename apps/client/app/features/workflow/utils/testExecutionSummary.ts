export type TestNodeExecutionSummary = {
  nodeId: string;
  status: 'running' | 'success' | 'failure';
  latencyMs?: number;
  totalTokens?: number;
  cost?: number;
};

export const readTokenUsage = (output: unknown) => {
  if (!output || typeof output !== 'object') return undefined;
  const usage = (output as { usage?: Record<string, unknown> }).usage || {};
  const totalTokens = usage.total_tokens;
  if (typeof totalTokens === 'number') return totalTokens;

  const promptTokens =
    typeof usage.prompt_tokens === 'number' ? usage.prompt_tokens : 0;
  const completionTokens =
    typeof usage.completion_tokens === 'number' ? usage.completion_tokens : 0;
  const summedTokens = promptTokens + completionTokens;
  return summedTokens > 0 ? summedTokens : undefined;
};

export const readCost = (output: unknown) => {
  if (!output || typeof output !== 'object') return undefined;
  const directCost = (output as { cost?: unknown }).cost;
  if (typeof directCost === 'number') return directCost;
  const usage = (output as { usage?: Record<string, unknown> }).usage || {};
  return typeof usage.total_cost === 'number' ? usage.total_cost : undefined;
};

export const formatLatency = (latencyMs?: number | null) => {
  if (latencyMs === undefined || latencyMs === null) return '-';
  if (latencyMs < 1000) return `${latencyMs}ms`;
  return `${(latencyMs / 1000).toFixed(1)}s`;
};

export const formatTokens = (totalTokens?: number | null) => {
  if (totalTokens === undefined || totalTokens === null) return '-';
  return totalTokens.toLocaleString();
};

export const formatCost = (cost?: number | null) => {
  if (cost === undefined || cost === null) return '-';
  return `$${cost.toFixed(6)}`;
};

export const summarizeWorkflowExecution = (
  summaries: TestNodeExecutionSummary[],
  startedAt: number | null,
  finishedAt: number | null,
) => {
  const totalTokens = summaries.reduce(
    (sum, item) => sum + (item.totalTokens || 0),
    0,
  );
  const totalCost = summaries.reduce((sum, item) => sum + (item.cost || 0), 0);
  const totalLatencyMs =
    typeof startedAt === 'number' && typeof finishedAt === 'number'
      ? Math.max(0, finishedAt - startedAt)
      : undefined;

  return {
    totalTokens: totalTokens > 0 ? totalTokens : undefined,
    totalCost: totalCost > 0 ? totalCost : undefined,
    totalLatencyMs,
  };
};
