# 单机核心领域不变量（2026-09-07）

本轮不重建数据库，不引入账号或重型 DDD 框架。领域模型指业务对象与约束，不是训练领域大模型。

## 对象与职责

| 对象 | 稳定职责与约束 | 当前实施边界 |
| --- | --- | --- |
| Project | 聚合分析目标和业务假设，不替代数据版本 | 现有模型保持兼容 |
| Dataset | 当前可选择的数据入口，current_version_id 可前移 | 上传源文件不由分析工具覆盖 |
| DatasetVersion | 数据文件、内容哈希、字段口径的版本快照 | 口径变更新建版本；不原地改历史语义 |
| Run | 一次已批准计划的执行尝试 | 队列任务保存 analysis_spec 和 dataset_version_ids；执行前拒绝计划/版本漂移 |
| RunEvent | Run 内有序的执行事实 | 现有本地锁和 sequence 保持；不承诺多进程调度 |
| Evidence | 计算结果、来源版本、方法和代码 | 同名冲突证据不得用于总结绑定；代码片段不等于完整独立脚本 |
| Claim | 对证据的事实描述、推断或建议 | 总结 v3 用字段绑定填入数值；报告 Claim 继续走原有图文核验 |
| Report / ReportVersion | 可编辑报告及历史快照 | 编辑不能重签服务端证据；保留原校验基线和恢复入口 |
| Artifact | 版本化交付与来源追溯 | GeneratedArtifact 暂作为已有模板下载记录兼容模型，不与 Artifact 强行合表 |
| DatasetRelationship | 来源版本、关联键、粒度、匹配情况和副本结果 | 限 1:1 / N:1；重复字段的非可加性保留；尚缺提交幂等和服务端预览指纹 |

## Run 状态机

```text
queued → running → completed / failed / cancelled / interrupted
   └────────────→ cancelled
```

completed、failed、cancelled、interrupted 均为终态。重试新建 Run 并递增 attempt，不能把同一终态记录改回 running。后台执行器只接受 queued，重复投递终态任务不重复执行。

`domain.transition_run` 被后台执行、启动中断恢复和排队取消使用。`validate_execution_snapshot` 在进入排队执行的工具链前验证审批快照。当前策略是发现旧版本漂移后拒绝执行，不是自动切回旧版本；用户须生成新计划。同步兼容执行入口仍无持久 Run 快照，后续逐步迁移，不能宣称全部入口已统一。

## 总结协议 v3

模型返回模板与来源绑定，例如：

```json
{
  "summary": "总量为 {{total}}。",
  "bindings": [{"name": "total", "evidence_id": "metric-sales", "path": "value"}],
  "claims": [],
  "limitations": []
}
```

服务端只从 `value`、`calculation` 或 `data` 的标量路径填值。不执行表达式，不接受模型提供替代 value，不自行进行单位换算。未知/冲突证据、缺字段、重复绑定、非有限数值、无声明占位符、直接写入的数字都拒绝。summary 引用来源由服务端生成，客户端不能自证。旧的纯定性格式继续接受；旧的直接写数字格式需更新为引用格式。

这解决数值来源约束，不等于理解所有自然语言：正确数字配错指标名称、中文数词、因果措辞和模板化建议仍需语义质量审查。不得将本协议通过率标为报告准确率。降级保留清晰 provider 标志，失败响应消耗照常记录。

## 模块边界

- `main.py`：兼容 API、应用组装、暂留的图表/集成/规划路由。
- `report_routes.py`：报告 CRUD、版本历史、质量检查与导出。
- `presenters.py`：共享 API 序列化，不导入 main。
- `run_execution.py`：批准计划的工具执行与证据整理。通过 `ExecutionPorts` 显式接入模型调用、预算、用量、清洗副本、发布和事件回调。
- `run_runtime.py`：本地后台 Run 的开始、完成、失败和取消生命周期，不反向导入 main。
- `domain.py`：不依赖框架的状态与快照规则、预留能力描述。

拆分不是终点。执行器仍有较长工具分支，图表和集成路由仍在 main；后续可按黄金测试逐项拆成工具处理器，不在本轮叠加新执行能力。

## 下一轮扩展插口

`GET /api/v1/analysis-capabilities/reserved` 返回 `python.visualize` 的 unavailable/default-off 描述。它不进入可执行工具目录，不改变现有 python.run 权限，不显示可用承诺，也不提供安装或联网权限。

未来模块必须声明输入 DatasetVersion、输出 Artifact/Evidence、资源预算、取消接口及所需工具权限；能力开关只表达用户意愿，服务端策略才决定是否执行。报告写入仍走预览、差异、确认保存，不能一句话覆盖。

## 黄金验收清单

`backend/tests/test_core_golden.py` 固定零售总销售 600、利润 20、West 销售 400，以及小时/日粒度真实总量 70、错误展开总量 100。预期值独立手算，不从被测函数生成；不依赖下载文件、联网模型或逐字措辞。

用例还锁定绑定数值的合法渲染、伪造数值拒绝、引用错误拒绝、状态终态不可重入、审批后不可变更执行快照，以及模块无反向依赖/无重复路由。现有 Global Superstore 和 Bike Sharing 大样本验收脚本保留为独立门槛；小样本黄金不替代真实模型和大数据资源测试。
