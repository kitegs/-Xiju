# AI 图表优化闭环（第一批实现）

## 目的

让用户可以在报告中选中一张图表，要求 AI 优化其图表类型、字段绑定、样式或 Top N；所有显示数值由服务端对报告绑定的数据集完整重新计算，而不是由模型或前端样本生成。

## 用户流程

```text
选中报告图表
  → “AI 优化当前图表”或右键菜单
  → 输入修改要求
  → AI/本地规则返回受控 ChartPatch
  → 服务端校验字段、图表类型和版本
  → 完整数据重新计算并生成预览、质量评分、证据
  → 用户批准
  → 保存图表、证据与 ReportVersion
```

模型只能建议 `title`、`chart_type`、`x`、`y`、`series`、`description`、`style` 与 `limit`，不得提交图表数据、SQL、Python 或 ECharts JavaScript。

## API

| API | 作用 | 写入 |
|---|---|---|
| `GET /reports/{id}/charts/{chart_id}/context` | 读取图表、字段、质量与乐观锁版本 | 否 |
| `POST /reports/{id}/charts/{chart_id}/proposals` | 生成模型或本地规则提案 | 仅模型用量记录 |
| `POST /reports/{id}/charts/{chart_id}/preview` | 完整数据重新计算、预览与证据 | 否 |
| `POST /reports/{id}/charts/{chart_id}/apply` | 用户批准后保存 | 是，创建报告版本与审计记录 |

`base_version` 是当前 ChartSpec 的哈希。若预览后图表已被其他操作更改，应用会返回 409，用户必须重新读取上下文，避免覆盖他人或自己的新修改。

## 当前图表契约

前后端统一支持：`bar`、`line`、`area`、`scatter`、`bubble`、`pie`、`donut`、`table`、`highlight_table`、`heatmap`、`treemap`、`histogram`、`boxplot`、`combo`、`kpi`、`waterfall`、`pareto`、`control_chart`、`gauge`、`radar`、`density_plot`。

`ChartStyle` 统一定义主题、图例、标签、工具栏、缩放、堆叠、方向和数值精度；保留未知旧样式字段以兼容历史报告，但渲染器不会执行任意配置。

## 当前质量规则

- 饼图/环形图分类超过 8 项；
- 竖向柱图类别过多导致标签拥挤；
- 趋势图缺少维度；
- 散点图缺少 X 轴；
- 高级图表缺少第二指标；
- 仪表盘包含多个结果；
- 缺少标题。

下一批将在此基础上增加时间排序、双轴风险、色弱配色、单位/来源、科研误差线和布局冲突检查。
