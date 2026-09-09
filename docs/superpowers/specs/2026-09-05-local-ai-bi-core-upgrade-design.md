# 析据单机 AI BI 核心升级设计

> 状态：已确认，进入实施计划
> 日期：2026-09-05

## 1. 目标

在保持 Windows 单机免登录、一键启动和现有兼容 API 可用的前提下，完成四个闭环：

1. 所有模型调用都能按阶段统计 Token，并在统一中心查看；
2. 对不可恢复的日期损坏做诚实降级，用可靠时间粒度扩充 Global Superstore 报告；
3. AI 可以对整份报告提出增删改和排版方案，但不能绕过预览、质量检查和用户确认；
4. 一个 Project 可以创建多个本地 Dashboard，并完成编辑、展示、筛选、版本和 AI 布局建议。

本轮不实现登录、密码、JWT、用户 CRUD、第三方 Skill 安装、Redis/Celery 或新的外部 BI 依赖。

## 2. 已确认的产品决策

- 产品继续使用单机免登录，自动进入本机所有者身份。
- 一个 Project 可以拥有多个 Dashboard。
- 澄清技能首次一次性提出全部重要问题；后续只提出新出现且会改变结果的问题。
- 对话框附近提供 `自动 | 每次检查 | 关闭` 三档澄清菜单，按当前对话保存，新对话默认“自动”。
- 用户可以跳过问题并采用推荐默认值，但这些值必须作为“未经确认的业务假设”写入报告。
- AI 对整份报告的修改采用“生成方案 → 展示差异与质量 → 用户确认 → 保存版本”，不能直接覆盖报告。
- Token 中心只展示 Token，不计算或展示货币费用。
- Global Superstore 的原始文件不可修改；所有修复产生新的 DatasetVersion。

## 3. 方案选择

采用现有 FastAPI + SQLAlchemy + SQLite + DuckDB/Pandas + Vue + ECharts 的模块化单体方案。复用现有 `Project`、`DatasetVersion`、`Run`、`Artifact`、`Evidence`、`ReportDocument`、报告版本和异步运行机制。

不建设通用插件市场。首版 Skill 是仓库内版本化的受控定义，只提供结构化输入输出协议和 Prompt 片段；所有工具执行仍经过现有策略层。

## 4. 模块边界

### 4.1 Token 中心

扩展 `LlmUsageLog`，增加：

- `stage`：`intake | planning | synthesis | chart | report | dashboard`；
- `run_id`：关联分析运行；
- `report_id`：关联报告；
- `dashboard_id`：关联 Dashboard；
- `purpose`：不超过 120 字的调用目的。

保留现有 Token 原始字段和旧费用字段以兼容数据库，但新界面不显示金额。OpenAI 或 DeepSeek 未返回 Usage 时记录调用状态和 `usage_unavailable=true`，不能伪造 Token。

统一查询接口返回：

- 今日、近 7 日和累计 Token；
- 输入、缓存命中、缓存未命中、输出 Token；
- 按阶段、模型、Run、Report、Dashboard 汇总；
- 最近调用的耗时、状态和关联对象。

前端提供“Token 中心”页面，并在对话、报告 AI 和 Dashboard AI 方案中显示本次及累计 Token。确定性计算明确显示 `0 模型 Token`。

### 4.2 分析澄清 Skill

新增仓库内置 `analysis-intake` Skill，定义：

- 触发条件：生成报告、创建 Dashboard、复杂分析或新业务目标；
- 输入：用户请求、数据画像、项目已保存的分析简报；
- 输出：结构化问题列表、推荐默认值、问题原因和影响范围；
- 约束：首轮最多 8 个问题，一次性展示；不得重复已回答或已采用默认值的问题；不得索取与任务无关的敏感信息。

对话输入区左侧提供 `澄清` 菜单：

- `自动（默认）`：生成报告、创建 Dashboard、复杂分析或新业务目标时检查缺口，没有关键缺口则直接继续；
- `每次检查`：每次请求均执行缺口检查，但仍不得重复已回答的问题；
- `关闭`：不调用澄清 Skill，直接使用已保存简报和推荐默认值继续。

该设置保存在 Conversation，不影响其他对话。菜单旁显示 `自动`、`N 项待回答`、`已完成` 或 `已关闭`。问题在同一张卡片中一次性呈现，支持逐项回答和“全部使用推荐默认值”。设置中心只负责新对话的全局默认值。

`Project` 增加兼容字段 `analysis_brief JSON`，保存：

- 受众、分析目的、时间范围、对比基准、指标口径、单位/币种、目标值和输出类型；
- `answers`、`confirmed_keys`、`defaulted_keys`、`asked_keys`；
- Skill 版本、更新时间和产生这些信息的请求摘要。

自动和每次检查模式下，后续请求先比较当前目标与 `AnalysisBrief`。只有新目标引入新的关键缺口时才再次提问。关闭模式不调用 Skill。选择“使用推荐默认值继续”后，默认项进入 `defaulted_keys`；报告摘要、限制说明和质量结果均可看到这些假设。

无模型时使用相同 Schema 的本地固定问题集，保证核心流程仍可运行。

### 4.3 日期诊断与恢复

已确认三个 Global Superstore 文件哈希一致，`Order Date` 与 `Ship Date` 在源 CSV 中均为 `00:00.0`。精确日期不可恢复。

日期恢复遵循：

1. 先检查原字段、替代字段和数据覆盖率；
2. 可可靠恢复的字段生成新列，不覆盖旧列；
3. 每个派生时间字段保存 `source_columns`、`precision` 和转换说明；
4. 应用操作生成新的 DatasetVersion 和 CleaningRecipe；
5. 无法恢复时只披露限制，不猜测日期。

Global Superstore 默认生成 `Order Year`，来源为 `Year`，精度为 `year`。`Year + weeknum` 只能作为用户明确启用的“近似周周期”，不用于默认趋势和预测；`Ship Date` 不恢复。

数据工作台增加日期诊断卡、恢复预览和“生成新版本”操作。通用清洗步骤新增 `derive_period`，仅接受服务端白名单策略。

### 4.4 Global Superstore 报告扩充

固定黄金报告目标为 4 个 KPI 和最多 9 个分析视图：

1. 销售额、利润、利润率、数量 KPI；
2. 年度销售趋势；
3. 年度利润率趋势；
4. Market 销售贡献；
5. Region 盈利能力；
6. Category/Sub-Category 结构；
7. Segment 表现；
8. Ship Mode 与运输成本；
9. 折扣与利润风险；
10. Top/Bottom 产品；
11. 亏损或异常明细表。

生成器根据字段可用性选择图表，不为满足数量生成无意义视图。报告正文保留 6～9 个最有决策价值的分析视图；其余可进入 Dashboard。销售额与利润量级差异较大时使用分面或利润率，不默认使用双轴。

每个视图必须包含标题、结论、口径、单位、来源字段和 Evidence。时间图必须声明时间精度；Top/Bottom 必须说明排序与截断。

### 4.5 整份报告 AI PatchSet

新增类型化 `ReportPatchSet`，只允许以下操作：

- `update_report`：标题、摘要、主题和页面设置；
- `add_block | update_block | delete_block | move_block`；
- `add_chart | update_chart | delete_chart | move_chart`；
- `add_page_break`。

不接受通用 JSON Patch、任意 ECharts 配置或 HTML。新增/修改图表只提交字段绑定、聚合、筛选、排序、图表类型和受控样式，数据由服务端基于完整 DatasetVersion 重新计算。

新增 `ReportPatchProposal` 持久化：

- 关联 Project、Report、基础 ReportVersion 和 DatasetVersion；
- 保存用户指令、PatchSet、修改前后摘要、质量前后对比、Token Usage 和状态；
- 状态为 `pending | applied | rejected | stale`；
- 报告在提案后发生变化时标记 `stale`，禁止静默套用。

AI 上下文只包含 `AnalysisBrief`、ReportDocument 结构、字段画像、Evidence 摘要和质量问题，不发送完整逐行数据。

前端报告编辑器增加整份报告 AI 入口和差异抽屉，逐项展示新增、删除、移动、内容修改、图表变更及质量分变化。用户可以取消单项操作后重新预览；确认应用时先创建 ReportVersion，再一次性保存通过校验的文档。

### 4.6 本地 Dashboard

新增两张表：

- `dashboards`：Project、DatasetVersion、标题、说明、状态和 `document JSON`；
- `dashboard_revisions`：Dashboard 快照、来源操作和创建时间。

`DashboardDocument` 包含：

- 12 列网格和画布设置；
- `widgets[]`：KPI、ChartSpec 快照、表格、文本和筛选器；
- `filters[]`：日期、类别、数值区间和 Top N；
- `interactions[]`：点击筛选和联动高亮；
- 数据来源、刷新状态和质量结果。

图表以快照形式进入 Dashboard，并保存来源 Report/Chart ID。报告后续修改不会自动破坏已发布 Dashboard；用户可以执行“从来源刷新”并预览差异。

首版支持：

- 看板库的新建、读取、重命名、复制、软删除和恢复；
- 组件新增、复制、删除、移动、缩放和属性编辑；
- 编辑/浏览/全屏模式；
- 服务端使用完整数据按筛选条件重新计算组件；
- DashboardRevision 历史恢复；
- 从报告生成 Dashboard；
- AI 生成布局 PatchSet，继续使用预览、质量检查和确认保存。

Superset 保持独立的可选发布适配器，不作为本地 Dashboard 的运行依赖。

## 5. API 设计

### 5.1 Token

- `GET /api/v1/usage/tokens?workspace_id=&range=7d&group_by=stage`
- `GET /api/v1/usage/tokens/runs/{run_id}`
- `GET /api/v1/usage/tokens/reports/{report_id}`

### 5.2 AnalysisBrief 与日期恢复

- `POST /api/v1/projects/{project_id}/brief/questions`
- `GET /api/v1/projects/{project_id}/brief`
- `PUT /api/v1/projects/{project_id}/brief`
- `POST /api/v1/datasets/{dataset_id}/date-recovery/preview`
- `POST /api/v1/datasets/{dataset_id}/date-recovery/apply`

### 5.3 报告 AI

- `POST /api/v1/reports/{report_id}/ai-proposals`
- `GET /api/v1/reports/{report_id}/ai-proposals/{proposal_id}`
- `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/preview`
- `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/apply`
- `POST /api/v1/reports/{report_id}/ai-proposals/{proposal_id}/reject`

### 5.4 Dashboard

- `GET/POST /api/v1/projects/{project_id}/dashboards`
- `GET/PATCH/DELETE /api/v1/dashboards/{dashboard_id}`
- `POST /api/v1/dashboards/{dashboard_id}/duplicate`
- `POST /api/v1/dashboards/{dashboard_id}/restore`
- `GET /api/v1/dashboards/{dashboard_id}/revisions`
- `POST /api/v1/dashboards/{dashboard_id}/data-preview`
- `POST /api/v1/dashboards/from-report/{report_id}`
- `POST /api/v1/dashboards/{dashboard_id}/ai-proposals`
- `POST /api/v1/dashboards/{dashboard_id}/ai-proposals/{proposal_id}/apply`

删除操作为软删除并提供恢复；兼容 API 保持原路径和响应结构。

## 6. 前端信息架构

左侧主导航调整为：

- 分析
- 数据
- 图表
- 报告
- 看板
- 模板
- 专业发布
- 设置

“团队”入口在单机阶段隐藏，不删除已有兼容代码。

设置中新增 Token 中心；数据工作台新增日期诊断；报告编辑器新增“AI 修改整份报告”；看板使用独立 `DashboardWorkspace`，不继续扩充 `App.vue`。新 API 调用集中到小型客户端模块，避免五个功能再次耦合在根组件。

对话输入区在现有权限菜单旁增加三档澄清菜单和状态；问题使用单张 `AnalysisIntakeCard` 展示，不用连续消息逐题打断用户。

## 7. 错误与安全处理

- Token Usage 缺失时展示“服务商未返回”，不按字符数冒充官方 Token。
- Skill 输出必须通过 Pydantic Schema；问题去重以稳定 `question_key` 完成。
- 默认假设必须可见、可编辑、可追溯。
- 日期恢复先预览影响，确认后创建新版本；任何情况下不覆盖原文件。
- Report/Dashboard PatchSet 使用基础版本校验，过期提案不能应用。
- 删除报告对象时同时检查 Evidence 和图表引用；产生错误级质量问题的提案不能保存。
- Dashboard 筛选值和字段名均由服务端 Schema 校验，不拼接任意 SQL。
- AI 失败时保留本地确定性报告、手工编辑和 Dashboard 功能。

## 8. 测试与验收

### 8.1 单元与 API

- Token 对 DeepSeek/OpenAI Usage 字段解析正确，阶段汇总之和等于调用明细。
- 旧 `LlmUsageLog` 在新增字段后仍可读取。
- AnalysisBrief 不重复提问，默认值正确标记。
- 澄清菜单按对话持久化；自动模式只在命中条件时检查，每次检查模式不重复旧问题，关闭模式不产生澄清模型调用。
- 日期恢复测试证明原文件哈希不变、新版本包含 `Order Year`、精确日期未被伪造。
- ReportPatchSet 覆盖所有允许操作、非法字段、悬空 Evidence、过期版本和回滚。
- Dashboard CRUD、复制、软删除、恢复、筛选计算和版本恢复通过。

### 8.2 Global Superstore 黄金流程

- 51,290 行和现有销售额、利润断言保持不变；
- 年度汇总与独立 SQL 结果一致；
- 报告包含 4 个 KPI 和至少 6 个非 KPI 分析视图；
- 所有事实数字绑定 Evidence；
- DOCX 重新生成并逐页视觉检查；
- 从报告创建至少两个 Dashboard，并验证筛选联动和刷新。

### 8.3 Playwright

- 查看 Token 中心及阶段明细；
- 完成一次澄清、使用默认值并看到假设提示；
- 在自动、每次检查和关闭三种模式间切换，刷新后保持当前对话设置；
- 预览并应用日期恢复；
- 通过对话生成整份报告修改方案，取消一项后保存；
- 创建、复制、编辑、全屏查看、删除和恢复 Dashboard。

## 9. 实施顺序

1. Token 阶段标记、汇总 API 和 Token 中心；
2. AnalysisBrief 与 `analysis-intake` Skill；
3. 日期诊断、`Order Year` 新版本和 Global Superstore 报告扩充；
4. ReportPatchSet、提案持久化、差异预览和应用；
5. Dashboard 数据模型、CRUD、编辑/浏览和版本；
6. 从报告生成 Dashboard、AI 布局提案和筛选联动；
7. 完整回归、报告重生成、逐页视觉验收和文档更新。

每一步必须保持现有单机分析、报告编辑、DOCX 导出和可选 Superset 发布可用。
