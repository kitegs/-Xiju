# 单机多表收敛验收记录

日期：2026-09-07。结论：受限多表主流程可试用，尚未达到商业正式版或真实模型全链路验收标准。

## 数据与计算验收

使用用户提供的 `C:\Users\Administrator\Downloads\bike+sharing+dataset`，通过上传 API 创建副本，不修改原文件。

| 校验项 | 结果 |
| --- | --- |
| day.csv / hour.csv 行数 | 731 / 17,379 |
| 两表日期数 | 各 731 |
| 两表独立 cnt 总和 | 均为 3,292,679 |
| cnt = casual + registered | 两表全部成立 |
| hour.dteday → day.dteday | N:1，匹配率 100%，输出 17,379 行 |
| 原始文件 SHA-256 | 执行前后不变 |
| 汇总展开后的 day__cnt | 聚合被拦截，避免重复累计 |

day SHA-256：`a6bcf826782d3c0fbfdcbeead17cd0884185a0dafe8ff10cd48a874ee7ba18be`

hour SHA-256：`e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f`

## 最新真实 DeepSeek 验收

记录：`data/acceptance/20260907-195829-bike-multitable/acceptance.json`。

- 报告 ID：`59b654de-450a-4a48-9085-b6cf6483a956`，6 个图表、10 条 Evidence。
- 规划实际使用 DeepSeek；总结为 `deepseek-fallback`，状态 `degraded`，`full_model_pipeline_passed=false`。
- 4 次模型调用共 10,266 Token，包括校验失败的总结响应。按本地配置单价估算约 0.011814 元，不是供应商账单核对值。
- 自动规则质量检查通过、分数 100，仅代表当前规则通过，不代表解释质量、模型稳定性或商业交付质量满分。
- 前一轮记录 `20260907-194409-bike-multitable` 同样发生总结降级，且当时校验失败响应未计入用量，8,809 Token 不是完整消耗；本轮已修复并加入回归测试。

验收脚本刻意保留降级结果，而不是把 HTTP 200 当作完整成功。后续必须修正总结协议与验证器的兼容性，并连续多次通过，才能关闭此发布门槛。

## 自动化与文档视觉验收

- 后端全量：74 passed；仅 pytest 缓存目录权限警告，不影响断言。
- 浏览器主流程：7 passed，包含报告管理、分页搜索、关联预览/交换/确认、字段口径保存、进入 AI 分析。
- 前端生产构建通过；最大 ECharts 分包约 404 KB，已无原单包体积警告。
- 导出样例 `data/acceptance/20260907-194409-bike-multitable/bike-sharing-report.docx`，使用本机 Word 只读转换 PDF 后逐页检查，修正长血缘字段窄表排版问题，最终 9 页，无遮挡或内容溢出。
- 最终 DOCX SHA-256：`0c695db0b94b9fbcd7aadf50a65bd5d6b9711371a6822bd2502576f14897d84b`。渲染图位于同目录 `render-final/`。这个样例经过视觉验收，但不能冒充模型全链路通过的最终商业报告。

## 复测方式

先正常启动本地 API，在 `BI_V2.0` 执行：

```powershell
D:\PY\python.exe -X utf8 scripts/accept-bike-multitable.py
```

会新建测试上传副本、关系和报告，并产生真实模型费用；不修改原 CSV。请在模型设置可用、预算允许时执行。每次结果位于独立时间戳目录。确定性行数/金额应相同，模型措辞及 Token 不保证相同。

后端在 `backend` 执行 `D:\PY\python.exe -m pytest -q tests`；前端在 `frontend` 执行 `npm.cmd run build`、`npm.cmd run test:e2e`，使用已有依赖，不自动下载。

## 必须保留的边界与后续门槛

1. 多表当前是 1:1 / N:1 物化副本，拒绝 N:N 和反向 1:N。UI 单键，API 最多四键；不是任意跨事实表查询引擎。
2. 防重复聚合采用保守 SQL 检查，不是完整 SQL AST 或任意 Python/MCP 统计安全保证。按原右表粒度分析可避免展开后的权重偏差。
3. 关联确认还缺服务端预览哈希、幂等键及持久任务接入；大表资源预算尚未验收。
4. 报告解释应补观测时长/样本数归一化，去除不适用于共享单车的盈利模板。累计量差异不能直接推导原因；预测或推断统计不得因“不做预测”的否定语句被触发。
5. 部分证据代码是固定算子片段，不应宣称所有代码均可独立复制运行。后续统一可执行复现入口。
6. 进程恢复已有回归，但真实杀进程、Python/MCP 中途取消和长时间运行仍需专项验收。

下一步只收敛“总结协议稳定性 → 解释质量 → 多表提交可靠性”，冻结企业账号及新集成扩展。
