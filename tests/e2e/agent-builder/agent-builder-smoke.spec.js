const { test, expect } = require('@playwright/test');
const {
  config,
  loginAndOpenWorkflow,
  openAgentBuilder,
  requireEnvironment,
} = require('./helpers');

test('model selection, preview, apply/save, and multi-KB selection', async ({
  page,
}) => {
  requireEnvironment('email', 'password', 'organizationId', 'workflowId');
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await loginAndOpenWorkflow(page, config.workflowId);

  const panel = await openAgentBuilder(page);
  const textarea = panel.locator('textarea');
  const modelOptionsResponse = await page.request.get(
    `${config.baseUrl}/api/v1/agent-builder/model-options`,
    { headers: { 'X-Organization-Id': config.organizationId } },
  );
  expect(modelOptionsResponse.status()).toBe(200);
  const modelGroups = await modelOptionsResponse.json();
  expect(modelGroups.map((group) => group.provider_name)).toEqual([
    'openai',
    'anthropic',
    'google',
    'llamaparse',
  ]);
  const selectedOption = modelGroups.flatMap((group) => group.options)[0];
  expect(selectedOption).toBeTruthy();

  const modelMenuButton = panel.locator('header svg.lucide-chevron-down').locator('..');
  await modelMenuButton.click();
  await panel
    .getByRole('button', {
      name: `${selectedOption.model.name}, ${selectedOption.credential.credential_name}`,
      exact: true,
    })
    .click();

  const prompt =
    'Create a simple workflow: Start input to LLM answer without Knowledge Base to Answer node.';
  const messageRequestPromise = page.waitForRequest(
    (request) =>
      request.url().includes('/api/v1/agent-builder/sessions/') &&
      request.url().endsWith('/messages') &&
      request.method() === 'POST',
    { timeout: 60000 },
  );
  await textarea.fill(prompt);
  await textarea.press('Enter');
  const messageRequest = await messageRequestPromise;
  expect(messageRequest.postDataJSON().intent_model_selection).toEqual({
    credential_id: selectedOption.credential.id,
    model_id: selectedOption.model.id,
  });
  await expect(panel.getByText('draft_ready')).toBeVisible({ timeout: 60000 });
  await panel.getByRole('button', { name: '도안 생성 미리보기' }).last().click();

  const previewBanner = page.getByText(/Agent Builder 도안 보기/).first();
  await expect(previewBanner).toBeVisible({ timeout: 30000 });
  await expect(page.locator('.react-flow__node')).toHaveCount(3);
  const applyResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/agent-builder/drafts/') &&
      response.url().endsWith('/apply') &&
      response.request().method() === 'POST',
    { timeout: 60000 },
  );
  await panel.getByRole('button', { name: '적용 및 저장' }).click();
  const applyPayload = await (await applyResponsePromise).json();
  expect(applyPayload.outcome).toBe('saved');
  expect(applyPayload.audit_recorded).toBe(true);
  expect(applyPayload.layout_optimization_applied).toBe(true);

  const savedWorkflowId = applyPayload.saved_workflow_id || config.workflowId;
  const draftResponse = await page.request.get(
    `${config.baseUrl}/api/v1/workflows/${savedWorkflowId}/draft`,
    { headers: { 'X-Organization-Id': config.organizationId } },
  );
  expect(draftResponse.status()).toBe(200);
  const savedGraph = await draftResponse.json();
  expect(savedGraph.nodes).toHaveLength(3);
  expect(savedGraph.edges).toHaveLength(2);
  expect(
    savedGraph.nodes.map((node) => node.position?.x).sort((left, right) => left - right),
  ).toEqual([0, 580, 1160]);
  await expect(previewBanner).toBeHidden({ timeout: 30000 });
  await expect(panel.getByText(prompt, { exact: true })).toBeVisible();

  const knowledgePrompt =
    '사내 휴가와 복지 질문에 답하도록 Knowledge Base를 사용하는 워크플로우를 만들어줘.';
  await textarea.fill(knowledgePrompt);
  await panel.locator('svg.lucide-send').locator('..').click();
  await expect(panel.getByText('clarification_required').last()).toBeVisible({
    timeout: 60000,
  });
  const candidateList = panel.getByTestId('agent-builder-kb-candidate-list').last();
  const candidateButtons = candidateList.locator('button');
  const candidateCount = await candidateButtons.count();
  expect(candidateCount).toBeGreaterThanOrEqual(2);
  expect(candidateCount).toBeLessThanOrEqual(20);
  await candidateButtons.nth(0).click();
  await candidateButtons.nth(1).click();

  const selectionRequestPromise = page.waitForRequest(
    (request) =>
      request.url().includes('/api/v1/agent-builder/sessions/') &&
      request.url().endsWith('/messages') &&
      request.method() === 'POST',
    { timeout: 60000 },
  );
  await panel.locator('svg.lucide-send').locator('..').click();
  expect((await selectionRequestPromise).postDataJSON().selected_knowledge_candidates).toHaveLength(2);
  await expect(panel.getByText('draft_ready').last()).toBeVisible({ timeout: 60000 });
  expect(pageErrors).toEqual([]);
});
