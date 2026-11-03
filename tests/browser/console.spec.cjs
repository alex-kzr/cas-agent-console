const { test, expect } = require('@playwright/test');

test('console opens and displays the working-session panel', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveTitle('CAS · Execution console');
  await expect(page.locator('#working-session-panel')).toBeVisible();
  await expect(page.getByRole('button', { name: 'New working session' })).toBeVisible();
  await expect(page.locator('#working-session-panel h2')).toHaveText('One or two tasks. Your local workspace.');
  await expect(page.locator('header .local')).toContainText('Local console');
  expect(errors).toEqual([]);
});

test('one new non-secret task runs and is saved', async ({ page }) => {
  test.skip(process.env.CAS_BROWSER_LIVE !== '1', 'Set CAS_BROWSER_LIVE=1 for a real provider run.');
  const title = `Browser verification checklist ${Date.now()}`;
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New working session' }).click();
  const draft = page.locator('#working-session-list article').first();
  await draft.getByRole('textbox', { name: 'Task title' }).fill(title);
  await draft.getByRole('textbox', { name: 'Task instructions' }).fill(
    'Write a concise five-item checklist for verifying a small software deployment. Keep it under 100 words.'
  );
  await draft.getByRole('button', { name: 'Add task' }).click();
  const card = page.locator('#working-session-list article').filter({ hasText: title });
  await expect(card).toHaveCount(1);
  await card.getByRole('button', { name: 'Freeze plan and show local command' }).click();
  await card.getByRole('button', { name: 'Run task' }).click();
  await expect(card).toContainText('COMPLETED · cleanup CONFIRMED', { timeout: 110_000 });
  await expect(card.locator('pre').last()).not.toBeEmpty();
  await page.reload();
  await expect(page.locator('#working-session-list article').filter({ hasText: title })).toContainText('COMPLETED · cleanup CONFIRMED');
});

test('oversized task is blocked and a rejected draft survives refresh', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New working session' }).click();
  const draft = page.locator('#working-session-list article').first();
  await draft.getByRole('textbox', { name: 'Task title' }).fill('Draft survival check');
  const prompt = draft.getByRole('textbox', { name: 'Task instructions' });
  await prompt.fill('Ж'.repeat(1100));
  await expect(draft).toContainText('2200 / 2048 bytes');
  await expect(draft.getByRole('button', { name: 'Add task' })).toBeDisabled();
  const rejected = 'Please store password=SYNTHETIC_ONLY for later.';
  await prompt.fill(rejected);
  await draft.getByRole('button', { name: 'Add task' }).click();
  await expect(page.locator('#working-session-status')).toContainText('must not look like credentials');
  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.waitForTimeout(3200); // two periodic refreshes rebuild every card
  const card = page.locator('#working-session-list article').first();
  await expect(card.getByRole('textbox', { name: 'Task instructions' })).toHaveValue(rejected);
  await expect(card.getByRole('textbox', { name: 'Task title' })).toHaveValue('Draft survival check');
  await card.getByRole('button', { name: 'End session' }).click();
  await expect(page.locator('#working-session-list article').first()).toContainText('CLOSED');
});
