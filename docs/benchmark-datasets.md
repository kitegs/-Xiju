# 权威测试数据与验收矩阵

公开仓库不应只展示“能跑起来”，还应证明相同输入能得到可复核、可重复的分析结果。本项目把测试数据分成三类：确定性回归、真实业务/时间序列、科研/问卷统计。

## 推荐数据源

| 数据源 | 适合验证 | 使用注意 |
| --- | --- | --- |
| 项目内置虚构零售数据与测试生成的 Global Superstore 形状数据 | 上传、画像、清洗、SQL、图表、报告、Evidence 全链路固定断言 | 完全合成，可随代码发布；不要把来源和许可不明的真实 Global Superstore 文件提交到公开仓库 |
| [UCI Bike Sharing](https://archive.ics.uci.edu/dataset/275/bike%2Bsharing%2Bdataset) | 时间排序、季节性、回归、预测回测、异常和天气因素 | 17,389 条小时记录，CC BY 4.0；发布派生样本时保留署名和 DOI |
| [World Bank World Development Indicators](https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures) | 多国家时间序列、缺失值、单位、来源、API 导入 | World Bank 自产开放数据默认 CC BY 4.0；固定测试必须保存下载日期、查询 URL、原始快照哈希和许可字段，避免上游修订导致断言漂移 |
| [Eurostat Web Services](https://ec.europa.eu/eurostat/data/web-services) | SDMX 多维数据、地区层级、筛选、透视、时间序列 | 允许商业和非商业复用但必须注明来源；在线库只保留最新观测，回归测试应使用带哈希的本地快照 |
| [CDC NHANES](https://wwwn.cdc.gov/nchs/nhanes/tutorials/datasets.aspx) | 加权描述统计、置信区间、t 检验、ANOVA、卡方、回归和科研报告 | 必须读取代码本和分析指南；公共文件仅用于统计分析/报告，不得尝试重新识别或与可识别数据连接 |
| [NYC TLC Trip Records](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) | Parquet 大文件、分页、地理区域、性能和增量导入 | 官方发布但来源为运营商上报，页面明确不保证完整准确；适合作压力测试，不适合作“真值”金标准 |
| [NOAA Climate Data Online](https://www.ncei.noaa.gov/cdo-web/) | 气候时间序列、缺测、异常、预测区间和 API 限流 | API 需要 Token，默认限制为每秒 5 次、每日 10,000 次；CI 中使用固定快照，不实时请求 |

## 最小验收矩阵

1. **确定性回归**：合成 Global Superstore 每次运行的总销售额、总利润、区域汇总、Artifact 与 Evidence ID 完全一致。
2. **时间序列**：UCI Bike Sharing 的日期必须按真实时间排序；预测使用滚动回测，展示误差和置信区间，不能把随机切分当时间回测。
3. **官方指标**：World Bank 或 Eurostat 报告中的每个数字都带指标代码、单位、地区、期间、来源 URL、快照日期和 Evidence ID。
4. **科研统计**：NHANES 必须保留权重、分层和整群变量；未支持复杂抽样设计时明确阻止“全国代表性”结论。
5. **大文件**：NYC TLC 使用一个固定月份测试 Parquet 分页、取消、重试、内存上限和图表采样；不把上报数据当绝对真值。
6. **报告质量**：固定模板至少检查章节顺序、图表顺序、时间轴排序、单位/来源、无证据数字为零、未授权工具调用为零。

## 数据快照规范

每个真实基准数据集都应保存一个不含敏感信息的小型测试快照，并配套 `manifest.json`：

```json
{
  "source_url": "https://example.org/api/query",
  "retrieved_at": "2026-09-04T00:00:00Z",
  "license": "CC BY 4.0",
  "sha256": "...",
  "row_count": 0,
  "expected_metrics": {}
}
```

CI 只运行固定快照，联网任务定期检查上游变化并生成新快照候选；人工确认后再更新金标准。这样既能复现，也能发现真实数据接口变化。
