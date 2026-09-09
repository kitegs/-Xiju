import { expect, test } from '@playwright/test'

test('first use configures a disabled model without disclosing its key on reload', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('当前上下文')).toBeVisible()
  await page.getByTitle('设置').click()
  const card = page.locator('.provider-card').filter({ has: page.getByRole('heading', { name: 'DeepSeek', exact: true }) })
  await expect(card).toBeVisible()
  await card.locator('header input[type="checkbox"]').uncheck()
  await card.getByLabel(/^模型/).fill('onboarding-offline-fixture')
  await card.getByLabel('API Key', { exact: true }).fill('onboarding-only-no-live-key')
  const saved = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/settings/providers/deepseek'))
  await card.getByRole('button', { name: '保存设置', exact: true }).click()
  const response = await saved
  expect(response.ok()).toBeTruthy()
  expect(await response.text()).not.toContain('onboarding-only-no-live-key')
  await page.reload()
  await page.getByTitle('设置').click()
  await expect(card.getByLabel(/^模型/)).toHaveValue('onboarding-offline-fixture')
  await expect(card.getByLabel('API Key', { exact: true })).toHaveValue('')
  await expect(card.locator('header input[type="checkbox"]')).not.toBeChecked()
})
