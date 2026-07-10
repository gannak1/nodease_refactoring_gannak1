const { test, expect } = require('@playwright/test');
const {
  config,
  loginAndOpenWorkflow,
  openAgentBuilder,
  requireEnvironment,
} = require('./helpers');

test('existing GitHub target receives only the requested LLM node', async ({ page }) => {
  requireEnvironment(
    'email',
    'password',
    'organizationId',
    'structuredEditWorkflowId',
  );
  await loginAndOpenWorkflow(page, config.structuredEditWorkflowId);
  const panel = await openAgentBuilder(page);
  const textarea = panel.locator('textarea');
  const messageResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/agent-builder/sessions/') &&
      response.url().endsWith('/messages') &&
      response.request().method() === 'POST',
    { timeout: 60000 },
  );
  await textarea.fill('github 노드 뒤에 LLM 노드를 추가해줘');
  const sendButton = panel.locator('svg.lucide-send').locator('..');
  await expect(sendButton).toBeEnabled();
  await sendButton.click();

  const payload = await (await messageResponsePromise).json();
  expect(payload.status).toBe('draft_ready');
  expect(payload.structured_request.draft_mode).toBe('modify_workflow');
  expect(payload.structured_request.required_capabilities).toEqual(['llm']);
  const graph = payload.draft_preview.preview_graph;
  const generatedNodes = graph.nodes.filter((node) =>
    String(node.id).startsWith('agent-'),
  );
  expect(generatedNodes.map((node) => node.type)).toEqual(['llmNode']);
  const generatedLlmId = generatedNodes[0].id;
  const edgePairs = graph.edges.map((edge) => [edge.source, edge.target]);
  expect(edgePairs).not.toContainEqual(['smoke-github', 'smoke-answer']);
  expect(edgePairs).toContainEqual(['smoke-github', generatedLlmId]);
  expect(edgePairs).toContainEqual([generatedLlmId, 'smoke-answer']);
});
