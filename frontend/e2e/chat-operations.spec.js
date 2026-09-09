import {test,expect} from '@playwright/test'

test('batch report recycle and restore only selected reports',async({page,request})=>{
  const workspace=(await (await request.post('/api/v1/workspaces/bootstrap')).json()).id
  for(const title of ['批量甲','批量乙']) await request.post('/api/v1/reports',{data:{workspace_id:workspace,title}})
  await page.goto('/')
  await page.getByRole('button',{name:'▦ 报告',exact:true}).click()
  const searchLoaded = page.waitForResponse(r => r.url().includes('/api/v1/report-catalog?') && new URL(r.url()).searchParams.get('q') === '批量')
  await page.getByLabel('搜索报告').fill('批量')
  await searchLoaded
  await expect(page.getByLabel('选择报告 批量甲')).toBeVisible()
  await page.getByRole('button',{name:'全选本页',exact:true}).click()
  await expect(page.getByLabel('选择报告 批量甲')).toBeChecked()
  await expect(page.getByLabel('选择报告 批量乙')).toBeChecked()
  page.once('dialog',d=>d.accept())
  await page.getByRole('button',{name:'删除所选（2）',exact:true}).click()
  await expect(page.getByLabel('选择报告 批量甲')).toHaveCount(0)
  await page.getByRole('button',{name:'回收站',exact:true}).click()
  await expect(page.getByLabel('选择报告 批量甲')).toBeVisible()
  await page.getByLabel('选择报告 批量甲').check()
  page.once('dialog',d=>d.accept())
  await page.getByRole('button',{name:'恢复所选（1）',exact:true}).click()
  await expect(page.getByLabel('选择报告 批量甲')).toHaveCount(0)
  await expect(page.getByLabel('选择报告 批量乙')).toBeVisible()
})

test('conversation bulk recycle retains messages and can restore',async({page,request})=>{
  const workspace=(await (await request.post('/api/v1/workspaces/bootstrap')).json()).id
  await request.post('/api/v1/conversations',{data:{workspace_id:workspace,title:'批量会话验收'}})
  await page.goto('/')
  await page.getByLabel('选择会话 批量会话验收').check()
  page.once('dialog',d=>d.accept())
  await page.getByRole('button',{name:'删除所选（1）',exact:true}).click()
  await expect(page.getByLabel('选择会话 批量会话验收')).toHaveCount(0)
  await page.getByRole('button',{name:'对话回收站',exact:true}).click()
  await page.getByLabel('选择会话 批量会话验收').check()
  page.once('dialog',d=>d.accept())
  await page.getByRole('button',{name:'恢复所选（1）',exact:true}).click()
  await expect(page.getByLabel('选择会话 批量会话验收')).toHaveCount(0)
})

test('stop planning prevents automatic tool execution',async({page})=>{
  await page.goto('/')
  await expect(page.getByText('当前上下文')).toBeVisible()
  let execute=0
  await page.route('**/api/v1/chat/execute-async',route=>{execute++;return route.abort()})
  await page.route('**/api/v1/chat/plan-async',()=>{})
  await page.locator('textarea[placeholder^="向数据提问"]').fill('生成报告')
  await page.locator('.send-btn').click()
  await page.getByRole('button',{name:'■ 停止当前对话任务'}).click()
  await expect(page.getByText('已停止等待规划', {exact:false})).toBeVisible()
  expect(execute).toBe(0)
})
