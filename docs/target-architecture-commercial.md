# Insight Studio 商业化目标架构

## 2026-09-07 增量：受限多表与摘要分页

`relationships.py` 负责键归一化、基数/匹配分析、拒绝 N:N/反向 1:N、空键不匹配的副本物化与清洗语义继承。`DatasetRelationship` 记录两侧 DatasetVersion、键、连接方式与结果 Dataset；结果复用现有图表/报告路径，不让模型直接执行任意 JOIN。

`Dataset.semantics` 是当前编辑状态；`DatasetVersion.profile.semantics` 是口径快照。语义改变生成内容哈希相同的新版本；重算修复读原版本。关系来源版本递归进入 Artifact/Evidence 来源集合；单表兼容接口保持不变。用户标签、描述和 brief 属不可信上下文，权限与粒度限制由服务端执行。

独立 `report_catalog.py` 提供 `GET /api/v1/report-catalog`（q、dataset_id、deleted、offset、limit、sort），SQL 只投影元数据、300 字摘要、图表数，limit 最大 100。Vue 报告库每页 24 条；旧 `/reports` 完整文档接口保留。JSON 数组长度查询目前针对单机 SQLite，其他数据库方言需单独适配测试。

本轮未把关联操作纳入持久后台任务，也未引入队列依赖。预览令牌/幂等应用、大表资源预算和主路由进一步拆分仍属后续门槛，不应标为已完成。

## 2026-09-06 增量：重算修复提案

新增独立 `report_repair.py`，提供 `POST /reports/{id}/repair/preview` 和 `POST /reports/{id}/repair/apply`。读取原 DatasetVersion.storage_key，重算前后核对 content_hash，固定计算在线程中执行。提案哈希绑定原报告、标题、数据版本与候选文档；应用时重新计算并校验哈希，条件更新防止并发覆盖。确认字段必须为 true。写入旧 ReportVersion、新 Artifact 与审计，保持现有报告 API 兼容。

此处是确定性修复，不是 AI 通用重写或自动审核。现阶段为单机同步 HTTP 提案，较大数据与取消应接入既有 Run 队列，不额外引入新任务框架。

## 2026-09-05 增量：结论完整性与数学检查

`report_claims.seal_claims` 只在确定性报告生成结束调用，写入原始文本/引用与 Evidence SHA-256 指纹；`check_claims` 输出带对象 ID 的 `ReportQualityReport.claim_checks`。PUT 保留服务器已有基线和 Evidence，拒绝客户端自签认证。`Evidence.calculation` 可携带 ratio/growth/rank 操作数；校验器复算并检查结果、单位和期间类型。同比/环比仅支持明确的 YYYY-MM 完整月度期间，未证明期间完整性时仍需业务复核。

这是保守完整性检查，不是完整 Claim 语义引擎；正确的自由改写也进入待核验。旧报告 GET 重新评估规则，不沿用过期的 passed。原文基线增加文档体积，后续应迁往独立不可变 Claim 记录；本轮不引入新数据库表或模型调用。

## 2026-09-05 增量：报告 CRUD

`Report.deleted_at` 通过 SQLite 兼容迁移新增；默认列表只返回未删除报告，`deleted=true` 查询回收站。新增 `POST /reports`（可传 `source_report_id` 复制）、`PATCH /reports/{id}` 重命名、`DELETE /reports/{id}` 软删除、`POST /reports/{id}/restore` 恢复。沿用 `report.edit` 权限和审计；原 GET/PUT 保持兼容。创建/复制/重命名记录 Artifact，重命名和编辑保留 ReportVersion。公共报告访问助手拒绝回收站报告，恢复与重复删除显式允许读取软删除记录。

前端复用 ContextMenu，ReportLibrary 提供按钮与右键两种操作，复用现有编辑器。标题搜索与数据集筛选在本地列表执行，暂不引入服务端分页；报告量显著增长时应将列表改为摘要分页接口。

## 2026-09-05 增量：可选组件执行链

`Conversation.analysis_capabilities` 存储会话偏好；`AnalysisOptions.capabilities` 随计划写入消息及运行快照，执行时不重新读取最新偏好。兼容迁移为旧会话增加 JSON 字段；旧请求缺省继承会话设置。

服务端 `capabilities.configure_steps` 清除模型提供的组件步骤，再按快照插入 `analysis.deepen`、`report.layout`、`report.review`、`report.alternatives`；组件仍经过工具策略检查。深入分析只允许固定诊断白名单，禁用项不能由模型重新启用。模型审阅只提供意见，不改写事实。Usage 在解析输出前提交；可选组件失败记录在结果和工具状态中，基础报告链继续执行。执行结果保存到消息与报告元数据，前端可展开复核。

初版沿用现有执行器，不增加插件框架、独立服务或依赖。图表排版和章节比较为本地规则；未接入跨表查询引擎。

| 文档属性 | 内容 |
|---|---|
| 文档版本 | 2.0 |
| 状态 | 当前基线 |
| 更新日期 | 2026-09-03 |
| 对应需求 | [vNext 需求说明书](requirements-vnext.md) |
| 历史参考 | [vNext 详细设计](detailed-design-vnext.md) |

## 1. 架构结论

保留 Vue、FastAPI、ECharts、DuckDB、本地确定性分析工具、报告编辑器、模型适配器和 MCP 网关；将系统核心从页面功能集合重构为“项目、不可变数据版本、分析运行、成果与证据”的工作流平台。

Superset 是可选的专业发布端，不是单机核心依赖。单机版与团队版共享领域模型和 API 契约，只替换身份、存储、任务和密钥基础设施。

## 2. 架构原则

1. **本地闭环优先**：没有 Superset、Docker、外部数据库和云模型时，仍可清洗、计算、制图、编辑和导出。
2. **原始数据不可变**：任何清洗和转换都产生新的 DatasetVersion。
3. **模型不是真值计算器**：模型负责意图、计划、解释和工具选择，正式值由确定性引擎产生。
4. **成果是一等对象**：表格、图表、报告、代码和诊断均以 Artifact 保存。
5. **证据随结果保存**：结论必须引用可复核 Evidence。
6. **能力级授权**：权限绑定数据范围和工具能力，不只绑定页面入口。
7. **渐进迁移**：为现有前端保留兼容 API，不进行一次性大爆炸重写。
8. **外部服务可降级**：模型、MCP、Superset 或通知服务失败不破坏本地项目。

## 3. 系统上下文

```text
用户
 ├─ 对话提出分析要求
 ├─ 手动编辑数据配方、图表和报告
 └─ 审批外发、发布和高风险操作
        │
        ▼
Insight Studio
 ├─ 项目与成果管理
 ├─ AI 编排与工具策略
 ├─ 数据/统计计算
 ├─ 图表与报告编译
 └─ 运行、证据、审计与导出
        │
        ├─ 可选模型：DeepSeek / OpenAI / 本地模型
        ├─ 可选工具：MCP 服务
        ├─ 可选发布：Apache Superset
        └─ 可选数据源：MySQL / PostgreSQL 等
```

## 4. 逻辑分层

```text
Presentation
  Vue 工作台、对话流、数据工作台、图表编辑器、报告编辑器

Application
  ProjectService、RunService、ApprovalService、ArtifactService、ExportService

Orchestration
  IntentRouter、Planner、PlanValidator、WorkflowExecutor、QualityGate

Domain
  Project、DatasetVersion、Recipe、Run、RunStep、Artifact、Evidence、ChartSpec、ReportDocument

Engines
  Import/Profile、DuckDB SQL、Cleaning、Statistics、Sandbox Python、Chart Compiler、Report Compiler

Adapters
  Model Provider、MCP、Superset、Database、Notification

Infrastructure
  Metadata Store、Artifact Store、Queue、Secret Store、Audit、Backup/Migration
```

领域层不能依赖 Vue、Superset、具体模型协议或 ECharts option。外部系统通过适配器实现。

## 5. 建议代码边界

### 5.1 后端

```text
backend/app/
├─ api/
│  ├─ projects.py
│  ├─ datasets.py
│  ├─ runs.py
│  ├─ artifacts.py
│  ├─ charts.py
│  ├─ reports.py
│  ├─ connectors.py
│  └─ settings.py
├─ domain/
│  ├─ project.py
│  ├─ dataset.py
│  ├─ workflow.py
│  ├─ artifact.py
│  ├─ chart.py
│  └─ report.py
├─ services/
├─ orchestration/
│  ├─ intent_router.py
│  ├─ planner.py
│  ├─ validator.py
│  ├─ executor.py
│  └─ quality_gate.py
├─ engines/
│  ├─ import_engine.py
│  ├─ duckdb_engine.py
│  ├─ cleaning_engine.py
│  ├─ statistics_engine.py
│  ├─ chart_compiler.py
│  └─ report_compiler.py
├─ tools/
│  ├─ registry.py
│  ├─ contracts.py
│  └─ builtins/
├─ connectors/
│  ├─ models/
│  ├─ mcp.py
│  ├─ superset.py
│  └─ databases/
├─ repositories/
├─ workers/
├─ security/
└─ compatibility/
```

当前 `main.py` 保留应用装配和路由注册，业务逻辑逐步迁出。旧接口通过 `compatibility/` 调用新服务，待前端迁移完成后再退役。

### 5.2 前端

```text
frontend/src/
├─ app/
│  ├─ router/
│  ├─ stores/
│  └─ api/
├─ features/
│  ├─ projects/
│  ├─ datasets/
│  ├─ chat/
│  ├─ runs/
│  ├─ charts/
│  ├─ reports/
│  ├─ templates/
│  ├─ connectors/
│  └─ settings/
├─ components/
└─ shared/
```

`App.vue` 只负责应用框架、路由出口和全局错误边界。业务状态进入对应 feature store，HTTP 调用统一进入 API 客户端。

## 6. 核心领域模型

### 6.1 关系

```text
Workspace 1 ── * Project
Project   1 ── * Dataset
Dataset   1 ── * DatasetVersion
DatasetVersion 1 ── * TransformRecipe
Project   1 ── * Conversation
Project   1 ── * Run
Run       1 ── * RunStep
Run       1 ── * Artifact
Artifact  * ── * Evidence
Artifact  1 ── 0..1 ChartSpec / ReportDocument / Table / File
```

### 6.2 关键对象

**Project**

- `id`, `workspace_id`, `name`, `scenario`, `status`
- `default_dataset_version_id`
- `created_at`, `updated_at`, `archived_at`

**DatasetVersion**

- `id`, `dataset_id`, `parent_version_id`
- `content_hash`, `schema_json`, `row_count`
- `storage_uri`, `storage_format`
- `recipe_id`, `created_by_run_id`
- `created_at`, `immutable=true`

**Run**

- `id`, `project_id`, `conversation_id`
- `analysis_spec`, `plan_version`
- `status`, `permission_profile`
- `model_provider`, `model_name`, `cost_summary`
- `input_dataset_version_ids`
- `started_at`, `finished_at`, `error_code`

**RunStep**

- `id`, `run_id`, `sequence`, `tool_name`, `tool_version`
- `status`, `approval_state`, `risk_level`
- `input_summary`, `output_summary`
- `code_artifact_id`, `error_summary`, `duration_ms`
- `idempotency_key`

**Artifact**

- `id`, `project_id`, `run_id`, `type`, `version`
- `content_uri` 或 `content_json`
- `source_dataset_version_ids`
- `created_at`, `supersedes_artifact_id`

**Evidence**

- `id`, `artifact_id`, `run_step_id`
- `claim`, `method`, `value`, `unit`
- `fields`, `filters`, `sample_size`
- `dataset_version_ids`, `query_or_code_artifact_id`

## 7. 存储设计

### 7.1 单机版

| 数据 | 存储 |
|---|---|
| 项目、运行、索引和设置 | SQLite，启用事务与版本化迁移 |
| 分析查询 | DuckDB |
| 数据版本 | Parquet 优先；原始上传文件单独只读保存 |
| 图表、报告、导出和代码 | 本地 Artifact Store |
| 密钥 | 操作系统凭据库优先；兼容现有加密保险库 |
| 任务 | 本地持久化队列与独立 Worker |

建议项目目录：

```text
data/
├─ metadata.db
├─ originals/<dataset-id>/
├─ versions/<dataset-id>/<version-id>.parquet
├─ artifacts/<project-id>/<artifact-id>/
├─ exports/<project-id>/
├─ backups/
└─ logs/
```

文件写入采用“临时文件 → 校验 → 原子替换 → 元数据提交”。数据库提交失败时清理未登记的新文件，不修改原始文件。

### 7.2 团队版

| 单机实现 | 团队替换 |
|---|---|
| SQLite | PostgreSQL |
| 本地 Artifact Store | S3/MinIO兼容对象存储 |
| 本地 Worker | Redis 队列与独立 Worker |
| 本地密钥库 | KMS/Vault/部署平台 Secret |
| 本机所有者 | OIDC/SAML 身份与工作区权限 |

应用服务和领域模型保持一致，不在业务代码中判断“SQLite还是PostgreSQL”。

## 8. AI 编排设计

### 8.1 AnalysisSpec

模型首先生成受约束的分析契约，而不是自由文本命令：

```json
{
  "intent": "business_report",
  "question": "分析区域销售和利润变化",
  "dataset_version_ids": ["dv_123"],
  "dimensions": ["Region", "Order Month"],
  "measures": ["Sales", "Profit"],
  "filters": [],
  "methods": ["aggregation", "period_comparison"],
  "deliverables": ["chart", "report"],
  "constraints": {
    "formal_values_require_evidence": true,
    "allow_external_publish": false
  }
}
```

后端校验字段、类型、权限、方法前提和数据范围，必要时要求模型修订或向用户说明缺失信息。

### 8.2 模型上下文

默认只向模型提供：

- 项目和用户问题；
- 字段名称、类型和业务描述；
- 数据质量、分布和基数摘要；
- 经脱敏的最小样本；
- 已获授权的聚合结果；
- 当前图表、报告和最近运行的结构化摘要；
- 可调用工具及其 Schema。

不默认提供完整原始文件、密钥、宿主机路径、其他项目内容和不相关历史对话。出站上下文需要生成可查看的清单和审计记录。

### 8.3 执行状态机

```text
draft
  → validating
  → awaiting_approval（按策略可跳过）
  → queued
  → running
      ├─ succeeded
      ├─ failed → retrying → running
      └─ cancelling → cancelled
```

重试复用 `idempotency_key`。已经成功并产生不可变成果的步骤不重复执行；需要重新计算时创建新 Run。

## 9. 工具注册表与安全策略

每个工具必须注册：

- 稳定名称和版本；
- 输入/输出 JSON Schema；
- 是否读取原始数据；
- 是否写入数据副本；
- 是否访问网络；
- 是否产生外部可见结果；
- 风险等级、超时、成本和资源限制；
- 幂等与补偿策略。

权限档位只是预设，最终以能力判断：

| 能力 | 安全 | 部分允许 | 完全访问 |
|---|---:|---:|---:|
| 读取画像和副本聚合 | 自动 | 自动 | 自动 |
| 创建本地草稿成果 | 审批或自动 | 自动 | 自动 |
| 隔离 Python | 审批 | 可按策略自动 | 可按策略自动 |
| 外部 MCP/模型发送数据 | 审批 | 审批或域名白名单 | 仍记录并受数据范围限制 |
| Superset发布 | 审批 | 审批 | 审批或受信工作区策略 |
| 覆盖/删除原始数据 | 禁止 | 禁止 | 默认仍禁止 |
| 宿主机任意命令 | 禁止 | 禁止 | 禁止 |

“完全访问”不等于绕过沙箱、审计和数据边界。

## 10. ChartSpec 与图表编译器

ChartSpec 是图表真源，ECharts option 和 Superset参数均为派生物。

```json
{
  "schema_version": "1.0",
  "type": "line",
  "dataset_version_id": "dv_123",
  "dimensions": ["Order Month", "Region"],
  "measures": [{"field": "Sales", "aggregation": "sum"}],
  "filters": [],
  "sort": [{"field": "Order Month", "direction": "asc"}],
  "encoding": {"x": "Order Month", "y": "Sales", "color": "Region"},
  "format": {"unit": "currency", "show_source": true},
  "quality": {"warnings": []}
}
```

编译流程：Schema校验 → 字段兼容检查 → 数据查询 → 设计规则检查 → ECharts option → 交互预览或静态渲染。禁止保存任意函数、HTML或脚本作为正式配置。

## 11. ReportDocument 与报告编译器

报告由可寻址块组成：标题、摘要、段落、指标、表格、图表、建议、方法、限制、来源和附录。每个事实块包含 `evidence_ids`，人工编辑包含作者、时间和锁定状态。

导出流程：

```text
ReportDocument
  → 引用完整性检查
  → 数值与证据核对
  → 图表静态渲染
  → 模板映射
  → DOCX/PDF/HTML编译
  → 视觉与结构检查
  → Export Artifact
```

AI重新生成只能替换未锁定块。导出总是生成新文件，不覆盖用户上传的模板。

## 12. API 边界

建议新增稳定资源接口：

```text
POST   /api/v1/projects
GET    /api/v1/projects/{id}
POST   /api/v1/projects/{id}/export
POST   /api/v1/projects/import

POST   /api/v1/projects/{id}/datasets/import
GET    /api/v1/dataset-versions/{id}
POST   /api/v1/dataset-versions/{id}/recipes/preview
POST   /api/v1/dataset-versions/{id}/recipes/apply

POST   /api/v1/projects/{id}/runs
GET    /api/v1/runs/{id}
POST   /api/v1/runs/{id}/approve
POST   /api/v1/runs/{id}/cancel
POST   /api/v1/runs/{id}/retry
GET    /api/v1/runs/{id}/events

GET    /api/v1/artifacts/{id}
POST   /api/v1/charts/{id}/revisions
POST   /api/v1/reports/{id}/revisions
POST   /api/v1/reports/{id}/exports
```

API返回稳定错误对象：`code`、`message`、`user_action`、`retryable`、`correlation_id`。前端不根据后端异常字符串判断业务状态。

## 13. MCP 与 Superset

### 13.1 MCP

MCP 网关只调用已发现且位于服务级和工作区级白名单中的工具。Bearer Token 保留在后端。每次调用执行 URL 校验、超时、响应大小、数据出站和审批检查，并保存审计摘要。

第三方 MCP 返回内容一律视为不可信输入，不得直接作为 HTML、脚本、SQL或文件路径执行。

### 13.2 Superset

本地 ChartSpec 和 ReportDocument 是主版本。Superset 保存发布副本和映射：

```text
Local DatasetVersion → Curated Copy → Superset Dataset
Local ChartSpec      → Adapter      → Superset Chart
Local DashboardSpec  → Adapter      → Superset Dashboard
```

发布具备幂等键和补偿记录。Superset不可用时返回可恢复错误，不影响本地编辑、导出和历史。

## 14. 可靠性与可观测性

必须统一记录：

- `correlation_id`, `project_id`, `run_id`, `run_step_id`；
- 状态、耗时、重试、取消和错误代码；
- 模型、token、费用和降级原因；
- 工具名称、版本和资源消耗；
- 数据版本、成果版本和证据覆盖率；
- 导出成功率和视觉检查结果。

日志默认脱敏，不记录 API Key、数据库密码、原始行内容和完整模型请求。诊断包由白名单字段生成，而不是直接打包日志目录。

## 15. 迁移顺序

### M0：基线与兼容层

- 为当前可运行版本建立 Git 基线和黄金测试。
- 增加新领域表和版本字段，不删除旧表。
- 为现有接口建立服务封装，停止向 `main.py` 增加业务逻辑。

### M1：DatasetVersion 与 Artifact

- 迁移上传、清洗结果、图表和报告引用。
- 新操作只写新模型；旧对象首次打开时按需转换。
- 建立项目导出、备份和迁移验证。

### M2：统一 Run 与工具执行器

- 将现有聊天计划、后台任务、SQL/Python和 MCP 运行统一到 Run/RunStep。
- 引入幂等键、审批状态和 Evidence关系。
- 前端运行历史切换到新接口。

### M3：ChartSpec/ReportDocument 版本化

- 统一 AI和人工编辑协议。
- 建立修订、锁定、比较、质量门禁和导出工件。
- Superset适配器只读取正式版本。

### M4：前端功能拆分与商业交付

- 按 feature 迁移 `App.vue`状态和请求。
- 完成安装、升级、诊断、备份和恢复。
- 删除已无调用的旧接口和过渡字段。

每个迁移阶段必须保证已有项目可打开、黄金流程通过、失败可回滚。禁止在同一迭代同时替换领域模型、全部 API和全部前端页面。

## 16. 当前架构决策

| ADR | 决策 |
|---|---|
| ADR-C-001 | 保留 Vue + FastAPI，采用渐进式模块化重构 |
| ADR-C-002 | 单机版以 SQLite + DuckDB + Parquet + 本地 Artifact Store 为默认基础设施 |
| ADR-C-003 | Superset是可选发布端，不是核心图表编辑器 |
| ADR-C-004 | 模型输出 AnalysisSpec/计划，不直接生成正式数值 |
| ADR-C-005 | ChartSpec和ReportDocument是主版本，渲染器配置是派生物 |
| ADR-C-006 | 原始数据不可变，清洗和重新计算创建新版本 |
| ADR-C-007 | 单机与团队版共享领域层，通过基础设施适配器切换部署 |
| ADR-C-008 | MCP属于不可信外部工具边界，必须发现、白名单、授权和审计 |

## 17. 架构完成定义

商业化架构不是以目录调整完成，而是以以下结果验收：

1. 一次运行可以从报告结论追溯到证据、步骤、工具和数据版本。
2. 同一数据版本与配方可以重放出一致正式结果。
3. Superset、MCP或云模型关闭后，本地核心流程仍可用。
4. 应用重启后后台任务、项目和编辑历史可恢复。
5. 单机数据可备份并迁移到新安装或团队部署。
6. 新功能不再需要把业务逻辑加入 `main.py` 或 `App.vue`。
# 2026-09-07 核心模块收敛补充

报告 CRUD/历史/导出归属 `report_routes.py`，共享序列化归属 `presenters.py`；工具计划执行归属 `run_execution.py`，后台生命周期归属 `run_runtime.py`。通过显式 `ExecutionPorts` 接入暂留在组装层的清洗、发布、模型与事件能力，禁止实现模块反向导入 main。

领域不变量与当前兼容边界以本文档中的领域模型和安全边界为准。`python.visualize` 仅为不可用的预留能力描述，不是新增的执行工具。不得将协议与结构重构视为真实模型质量验收通过。
