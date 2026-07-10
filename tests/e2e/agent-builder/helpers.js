const { expect, test } = require('@playwright/test');

const config = {
  baseUrl: process.env.NODEASE_BASE_URL || 'http://localhost',
  email: process.env.NODEASE_E2E_EMAIL,
  password: process.env.NODEASE_E2E_PASSWORD,
  organizationId: process.env.NODEASE_E2E_ORGANIZATION_ID,
  workflowId: process.env.NODEASE_E2E_WORKFLOW_ID,
  structuredEditWorkflowId: process.env.NODEASE_E2E_STRUCTURED_EDIT_WORKFLOW_ID,
};

function requireEnvironment(...keys) {
  const missing = keys.filter((key) => !config[key]);
  test.skip(
    missing.length > 0,
    `Missing Agent Builder E2E environment: ${missing.join(', ')}`,
  );
}

function agentBuilderPanel(page) {
  return page
    .locator('section')
    .filter({ hasText: 'Agent Builder' })
    .filter({ has: page.locator('textarea') })
    .first();
}

async function openAgentBuilder(page) {
  const panel = agentBuilderPanel(page);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.locator('button[aria-label*="Agent Builder"]').last().click();
    await page.waitForTimeout(750);
    if (await panel.isVisible()) return panel;
  }
  throw new Error('Agent Builder panel did not stay open');
}

async function loginAndOpenWorkflow(page, workflowId) {
  await page.goto(`${config.baseUrl}/auth/login`);
  await page.locator('input[name="email"]').fill(config.email);
  await page.locator('input[name="password"]').fill(config.password);
  await Promise.all([
    page.waitForURL(/\/dashboard/, { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.evaluate((organizationId) => {
    window.localStorage.setItem('moduly_active_organization_id', organizationId);
  }, config.organizationId);
  await page.goto(`${config.baseUrl}/modules/${workflowId}`);
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('.react-flow').first()).toBeVisible({ timeout: 30000 });
}

async function createPreview(panel, page, prompt) {
  const textarea = panel.locator('textarea');
  await expect(textarea).toBeEnabled({ timeout: 30000 });
  await textarea.fill(prompt);
  const sendButton = panel.locator('svg.lucide-send').locator('..');
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
  await expect(panel.getByText('draft_ready').last()).toBeVisible({ timeout: 60000 });
  await panel.getByRole('button', { name: '도안 생성 미리보기' }).last().click();
  await expect(page.getByText(/Agent Builder 도안 보기/).first()).toBeVisible({
    timeout: 30000,
  });
}

module.exports = {
  agentBuilderPanel,
  config,
  createPreview,
  loginAndOpenWorkflow,
  openAgentBuilder,
  requireEnvironment,
};
