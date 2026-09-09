# Insight Studio 文档索引

## 当前基线

- [2026-09-08 Alpha 真实对照与故障验收](alpha-acceptance-2026-09-08.md)：五组 DeepSeek Token、失败原因、专题质量与发布边界。
- [单机首次使用](quick-start-local.md)：环境检查、模型配置、示例、生成与修改。
- [最小内置扩展接口](minimal-extensions.md)：只接入 report.layout，不加载任意第三方代码。

- [单机主线收敛与剩余阻断项](convergence-plan.md)：2026-09-06 当前排期与冻结范围。

- [商业化产品需求基线](product-requirements-commercial.md)：产品定位、目标用户、发布范围、功能需求、质量门槛和商业验证指标。
- [商业化目标架构](target-architecture-commercial.md)：目标领域模型、模块边界、存储、AI工作流、工具安全、迁移顺序和架构决策。
- [分阶段完善方案](phased-delivery-plan.md)：历史实施记录与阶段进度参考；后续排期以商业化需求基线为准。

## 专题设计

- [AI 图表 Copilot](ai-chart-copilot.md)
- [MCP 网关](mcp-gateway.md)
- [权威测试数据与验收矩阵](benchmark-datasets.md)

## 历史参考

- [vNext 需求说明书](requirements-vnext.md)
- [vNext 详细设计说明书](detailed-design-vnext.md)

历史参考文档保留已有接口、字段和实施细节，但其中的阶段编号、产品定位和 Superset/Cube 优先级不再作为当前决策依据。出现冲突时，按“商业化产品需求基线 → 商业化目标架构 → 专题设计 → 历史参考”的顺序解释。

## 文档维护规则

1. 用户可见能力变化必须更新产品需求或对应专题设计。
2. 领域模型、信任边界、部署形态和外部依赖变化必须更新目标架构。
3. 新需求应具有稳定编号、优先级和可验证的验收标准。
4. 已实现不等于已达到商业质量；实施状态和发布门禁分别记录。
5. 旧文档不得静默删除，先标记为历史参考并保留迁移关系。
