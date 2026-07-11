const { test, expect } = require('@playwright/test');
const {
  config,
  createPreview,
  loginAndOpenWorkflow,
  openAgentBuilder,
  requireEnvironment,
} = require('./helpers');

test('blocked and failed apply outcomes preserve Preview Mode', async ({ page }) => {
  requireEnvironment('email', 'password', 'organizationId', 'workflowId');
  await loginAndOpenWorkflow(page, config.workflowId);
  const panel = await openAgentBuilder(page);
  await createPreview(
    panel,
    page,
    'Create a simple workflow with an input, LLM, and answer node.',
  );
  const previewBanner = page.getByText(/Agent Builder 도안 보기/).first();
  const previewNodeCount = await page.locator('.react-flow__node').count();
  let outcome = 'blocked';
  await page.route('**/api/v1/agent-builder/drafts/*/apply', async (route) => {
    const blocked = outcome === 'blocked';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        apply_id: 'e2e-safe-apply-id',
        outcome,
        saved_workflow_id: null,
        latest_graph_hash: null,
        latest_workflow_updated_at: null,
        block_reason: blocked ? '권한이 변경되어 저장할 수 없습니다.' : null,
        failure_reason: blocked ? null : '저장 중 안전하게 복구할 수 없는 오류가 발생했습니다.',
        stale_state: 'fresh',
        permission_recheck_outcome: blocked ? 'denied' : 'allowed',
        validation_state: 'valid',
        audit_recorded: true,
        layout_optimization_applied: false,
        notices: [
          blocked
            ? '권한이 변경되어 저장할 수 없습니다.'
            : '저장 중 안전하게 복구할 수 없는 오류가 발생했습니다.',
        ],
      }),
    });
  });

  const applyButton = panel.getByRole('button', { name: '적용 및 저장' });
  await applyButton.click();
  await expect(panel.getByText('권한이 변경되어 저장할 수 없습니다.')).toBeVisible();
  await expect(previewBanner).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(previewNodeCount);

  outcome = 'failed';
  await applyButton.click();
  await expect(
    panel.getByText('저장 중 안전하게 복구할 수 없는 오류가 발생했습니다.'),
  ).toBeVisible();
  await expect(previewBanner).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(previewNodeCount);
});
