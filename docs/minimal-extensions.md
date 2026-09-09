# 最小内置扩展接口 v1

范围：内置、受信任能力的统一入口，不是插件市场，不会安装或动态加载用户代码。

- 注册位置：`backend/app/extensions.py` 的 `_REGISTRY`。
- 第一个能力：`builtin.report-layout@1.0.0`，工具 `report.layout`，开关 `chart_layout`。
- 查询接口：`GET /api/v1/analysis-capabilities/extensions`；返回 ID、版本、契约版本、能力开关、网络需求和副作用描述。
- 输入：经过验证的 `ReportDocument`；先深拷贝，处理成功且输出通过 schema 校验后才更新草稿。
- 输出：处理结果和 `extension` manifest，进入原有 component_results，随报告保存，可追溯具体版本。
- 禁用时拒绝调用；未知工具拒绝。后端仍先执行现有工具权限策略，注册信息不是权限授予，也不是安全沙箱。
- 持久化仍走 Report/Artifact/Evidence 原有路径，扩展不能直接创建私有报告数据库或跳过版本管理。

新增能力的最小步骤：定义确定性 handler → 登记 manifest → 明确能力开关和工具权限 → 通过既有执行器接入 → 添加禁用、失败不污染输入、版本追溯和黄金回归测试。

当前仅适合内置扩展。第三方插件以后必须另做签名/来源、依赖隔离、资源限制、版本兼容和卸载策略；不能简单给 `_REGISTRY` 增加任意 Python 文件路径就称为安全插件化。
