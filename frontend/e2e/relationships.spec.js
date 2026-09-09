import { expect, test } from '@playwright/test'

test('report catalog pages summaries and searches beyond the first page', async ({page, request}) => {
  const workspace = await (await request.post('/api/v1/workspaces/bootstrap')).json()
  for(let i=1; i<=25; i++) {
    const response = await request.post('/api/v1/reports', {data: {workspace_id: workspace.id, title: `分页验收 ${String(i).padStart(2, '0')}`}})
    expect(response.status()).toBe(201)
  }
  await page.goto('/')
  await expect(page.getByText('当前上下文')).toBeVisible()
  await page.getByRole('button', {name: '▦ 报告', exact: true}).click()
  await page.getByLabel('搜索报告').fill('分页验收')
  await page.getByLabel('报告排序', {exact: true}).selectOption('title_asc')
  await expect(page.locator('.report-library .report-card')).toHaveCount(24)
  await page.getByRole('button', {name: '下一页', exact: true}).click()
  await expect(page.locator('.report-library .report-card')).toHaveCount(1)
  await expect(page.locator('.report-library h3')).toHaveText('分页验收 25')
  await page.getByLabel('搜索报告').fill('分页验收 01')
  await expect(page.locator('.report-library h3')).toHaveText('分页验收 01')
})

test('multi-table preview, swap and confirmed copy work without changing source rows', async ({ page, request }) => {
  const workspace = await (await request.post('/api/v1/workspaces/bootstrap')).json()
  async function upload(name, csv) {
    const response = await request.post('/api/v1/datasets/upload', { multipart: {
      workspace_id: workspace.id, file: { name, mimeType: 'text/csv', buffer: Buffer.from(csv) },
    } })
    expect(response.status()).toBe(201)
    return response.json()
  }
  const day = await upload('day.csv', 'instant,dteday,cnt\n1,2011-01-01,30\n2,2011-01-02,40\n')
  const hour = await upload('hour.csv', 'instant,dteday,hr,cnt\n1,2011-01-01,0,10\n2,2011-01-01,1,20\n3,2011-01-02,0,40\n')
  await page.goto('/')
  await expect(page.getByText('当前上下文')).toBeVisible()
  await page.locator('.chat-topbar select').selectOption(hour.id)
  await page.getByTitle('数据', { exact: true }).click()
  await page.getByRole('button', { name: '多表关联', exact: true }).click()
  const builder = page.locator('.relationship-builder')
  const panels = builder.locator('.relationship-grid article')
  await panels.nth(1).getByLabel('数据集').selectOption(day.id)
  await expect(panels.nth(0).getByLabel('关联键')).toHaveValue('dteday')
  await builder.getByRole('button', { name: '交换左右表' }).click()
  await builder.getByRole('button', { name: '验证关系' }).click()
  await expect(builder.locator('.relationship-error')).toContainText('交换左右表')
  await builder.getByRole('button', { name: '交换左右表' }).click()
  await builder.getByRole('button', { name: '验证关系' }).click()
  await expect(builder.locator('.relationship-kpis')).toContainText('100.00%')
  const apply = builder.getByRole('button', { name: '确认并生成关联副本' })
  await expect(apply).toBeDisabled()
  await builder.locator('.relationship-ack input').check()
  const responsePromise = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/v1/dataset-relationships'))
  await apply.click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  const relation = await response.json()
  expect(relation.result_dataset.profile.row_count).toBe(3)
  await expect(builder.locator('.relationship-history')).toContainText(relation.name)
  await page.screenshot({ path: 'test-results/multitable-workflow.png', fullPage: true })
  await page.getByRole('button', { name: '字段口径', exact: true }).click()
  await page.getByLabel('hr 角色', { exact: true }).selectOption('dimension')
  await page.getByLabel('cnt 显示名称', { exact: true }).fill('骑行次数')
  await page.getByLabel('cnt 单位', { exact: true }).fill('次')
  const semanticsSaved = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith('/semantics'))
  await page.getByRole('button', { name: '保存字段口径', exact: true }).click()
  const updated = await (await semanticsSaved).json()
  expect(updated.current_version_id).not.toBe(relation.result_dataset.current_version_id)
  await page.getByRole('button', { name: '多表关联', exact: true }).click()
  await builder.getByRole('button', { name: '交给 AI 分析', exact: true }).first().click()
  await expect(page.locator('.chat-topbar select')).toHaveValue(relation.result_dataset_id)
  for (const dataset of [day, hour]) {
    const preview = await (await request.get(`/api/v1/datasets/${dataset.id}/preview?workspace_id=${workspace.id}`)).json()
    expect(preview.rows.length).toBe(dataset.profile.row_count)
  }
})
