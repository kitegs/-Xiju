"""Server-side ChartSpec validation, full-data computation, and quality checks.

This module is deliberately renderer-neutral.  It turns a validated ChartSpec into a
small, deterministic data table that ECharts, exports, and external BI adapters can all
use.  It never accepts a model-supplied result table as evidence.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandas as pd

from .schemas import ChartPatch, ChartQualityIssue, ChartQualityReport, ChartSpec


NUMERIC_X_TYPES = {"scatter", "bubble", "density_plot"}
PIE_TYPES = {"pie", "donut"}


def chart_by_id(document: dict[str, Any], chart_id: str) -> ChartSpec:
    for raw in document.get("charts") or []:
        if raw.get("id") == chart_id:
            return ChartSpec.model_validate(raw)
    raise ValueError("报告中不存在指定图表")


def apply_chart_patch(chart: ChartSpec, patch: ChartPatch) -> ChartSpec:
    """Return a chart copy with only explicit, typed fields changed.

    `data` and `evidence_ids` are intentionally excluded: they are produced by the
    server after the patch passes validation.
    """
    payload = chart.model_dump(mode="python")
    for name in ("title", "chart_type", "x", "y", "series", "description", "style"):
        if name in patch.model_fields_set:
            value = getattr(patch, name)
            payload[name] = value.model_dump(mode="python") if hasattr(value, "model_dump") else value
    return ChartSpec.model_validate(payload)


def _numeric(frame: pd.DataFrame, column: str, aggregate: str | None) -> pd.Series:
    if aggregate == "count":
        return frame[column].notna().astype(int)
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.notna().sum() == 0:
        raise ValueError(f"指标字段“{column}”必须是数值，或将聚合改为计数")
    return values


def _operation(aggregate: str | None) -> str:
    values = {"sum": "sum", "avg": "mean", "count": "sum", "min": "min", "max": "max", None: "sum"}
    if aggregate not in values:
        raise ValueError(f"不支持的聚合方式：{aggregate}")
    return values[aggregate]


def validate_chart_fields(frame: pd.DataFrame, chart: ChartSpec) -> None:
    columns = {str(column) for column in frame.columns}
    bindings = [item for item in [chart.x, chart.y, *chart.series] if item]
    missing = [item.column for item in bindings if item.column not in columns]
    if missing:
        raise ValueError(f"图表字段不存在：{', '.join(dict.fromkeys(missing))}")
    if not chart.y and chart.chart_type not in {"table"}:
        raise ValueError("请选择主指标字段")
    if chart.x and chart.chart_type not in NUMERIC_X_TYPES and chart.x.column in columns:
        # Text, category and date columns are all valid dimensions. Numeric dimensions
        # are also accepted for backwards-compatible ordinal charts.
        pass


def compute_chart_data(frame: pd.DataFrame, chart: ChartSpec, limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute chart data from the complete dataset, not a UI sample or model output."""
    validate_chart_fields(frame, chart)
    limit = max(1, min(int(limit), 200))
    measure_fields = []
    for field in [chart.y, *chart.series]:
        if field and field.column not in measure_fields:
            measure_fields.append(field.column)
    if not measure_fields:
        if chart.x:
            rows = frame[[chart.x.column]].head(limit).copy()
            data = [{chart.x.column: "(空值)" if pd.isna(value) else str(value)} for value in rows[chart.x.column]]
        else:
            data = []
        return data, {"method": "完整数据只读预览", "source_columns": [chart.x.column] if chart.x else [], "code": ""}

    aggregate = chart.y.aggregate if chart.y else "sum"
    operation = _operation(aggregate)
    temporary = pd.DataFrame(index=frame.index)
    if chart.x:
        temporary[chart.x.column] = frame[chart.x.column]
    for column in measure_fields:
        field = next(item for item in [chart.y, *chart.series] if item and item.column == column)
        temporary[column] = _numeric(frame, column, field.aggregate or aggregate)

    if chart.x:
        grouped = temporary.groupby(chart.x.column, dropna=False)[measure_fields].agg(operation)
        if chart.chart_type in {"line", "area", "control_chart"}:
            parsed_index = pd.to_datetime(pd.Series(grouped.index.astype(str)), errors="coerce", format="mixed")
            if parsed_index.notna().mean() >= 0.8:
                grouped = grouped.iloc[parsed_index.argsort().to_numpy()]
            else:
                grouped = grouped.sort_index()
        else:
            grouped = grouped.sort_values(measure_fields[0], ascending=False)
        result = grouped.head(limit).reset_index()
        data = []
        for _, row in result.iterrows():
            item: dict[str, Any] = {
                chart.x.column: "(空值)" if pd.isna(row[chart.x.column]) else str(row[chart.x.column]),
            }
            item.update({column: None if pd.isna(row[column]) else float(row[column]) for column in measure_fields})
            data.append(item)
    else:
        data = []
        item: dict[str, Any] = {"label": chart.title}
        for column in measure_fields:
            item[column] = None if pd.isna(temporary[column].agg(operation)) else float(temporary[column].agg(operation))
        data.append(item)

    expression = ", ".join(f"{operation.upper()}({column})" for column in measure_fields)
    evidence = {
        "method": "完整数据上的受控 Pandas 聚合（等价于只读 SQL 聚合）",
        "source_columns": [item.column for item in [chart.x, chart.y, *chart.series] if item],
        "code": f"{expression}; limit={limit}",
        "row_count": len(data),
    }
    return data, evidence


def quality_report(chart: ChartSpec, data: list[dict[str, Any]], fields: list[dict[str, Any]] | None = None) -> ChartQualityReport:
    issues: list[ChartQualityIssue] = []
    category_count = len(data)
    field_meta = {str(item.get("name")): item for item in (fields or []) if item.get("name")}
    x_meta = field_meta.get(chart.x.column) if chart.x else None
    if chart.chart_type in PIE_TYPES and category_count > 8:
        issues.append(ChartQualityIssue(
            id="pie-too-many-categories", severity="warning", title="饼图分类过多",
            detail=f"当前有 {category_count} 个分类，扇区和标签会难以比较。",
            suggestion="改为横向条形图，或仅显示前 6～8 项并合并其余项。",
        ))
    if chart.chart_type == "bar" and chart.style.orientation == "vertical" and category_count > 9:
        issues.append(ChartQualityIssue(
            id="bar-label-crowding", severity="warning", title="类别标签可能拥挤",
            detail=f"当前柱状图有 {category_count} 个类别。",
            suggestion="使用横向条形图、Top N 或缩短标签。",
        ))
    if chart.chart_type in {"line", "area", "control_chart"} and not chart.x:
        issues.append(ChartQualityIssue(
            id="trend-without-dimension", severity="error", title="趋势图缺少时间或序列字段",
            detail="折线、面积和控制图需要 X 轴维度来表达顺序或时间。",
            suggestion="绑定日期、月份或其他有序字段。",
        ))
    elif chart.chart_type in {"line", "area", "control_chart"} and chart.x:
        is_date = (x_meta or {}).get("semantic_type") == "date" or any(word in chart.x.column.casefold() for word in ("date", "time", "period", "year", "month", "quarter", "日期", "时间", "月份", "季度", "年度"))
        labels = [str(row.get(chart.x.column, "")) for row in data]
        parsed = pd.to_datetime(pd.Series(labels), errors="coerce", format="mixed") if labels else pd.Series(dtype="datetime64[ns]")
        if is_date and (parsed.empty or parsed.isna().mean() > 0.2):
            issues.append(ChartQualityIssue(
                id="time-axis-unparseable", severity="warning", title="时间轴包含不可识别的日期",
                detail=f"“{chart.x.column}”被识别为时间字段，但部分值无法按日期排序。",
                suggestion="先在数据工作台统一日期格式，再生成趋势图。",
            ))
        elif is_date and not parsed.is_monotonic_increasing:
            issues.append(ChartQualityIssue(
                id="time-axis-unsorted", severity="warning", title="时间轴未按时间顺序排列",
                detail="趋势图如果按文本或录入顺序显示，可能产生错误趋势印象。",
                suggestion="按完整可解析日期升序排序。",
            ))
        elif not is_date:
            issues.append(ChartQualityIssue(
                id="trend-non-temporal-dimension", severity="info", title="趋势图未绑定时间字段",
                detail=f"当前 X 轴“{chart.x.column}”不是已识别的日期字段。",
                suggestion="若要表达时间趋势，请选择日期、月份或季度字段；否则可考虑条形图。",
            ))
    if chart.chart_type in {"scatter", "bubble", "density_plot"} and not chart.x:
        issues.append(ChartQualityIssue(
            id="scatter-without-x", severity="error", title="散点图缺少 X 轴指标",
            detail="散点、气泡和密度图至少需要两个连续数值变量。",
            suggestion="为 X 轴绑定一个连续数值字段。",
        ))
    if chart.chart_type in {"scatter", "bubble", "density_plot", "combo"} and len(chart.series) < 2:
        issues.append(ChartQualityIssue(
            id="advanced-chart-limited-encoding", severity="info", title="可增加第二指标",
            detail="当前图表使用一个主指标，信息表达较有限。",
            suggestion="加入第二指标、颜色或大小编码以增强比较。",
        ))
    if chart.chart_type == "gauge" and category_count > 1:
        issues.append(ChartQualityIssue(
            id="gauge-multiple-values", severity="warning", title="仪表盘应展示单一 KPI",
            detail=f"当前仪表盘有 {category_count} 个结果值。",
            suggestion="筛选到一个总指标，或改为条形图比较多个值。",
        ))
    if chart.style.dual_axis:
        if chart.chart_type != "combo":
            issues.append(ChartQualityIssue(
                id="dual-axis-non-combo", severity="warning", title="双轴只适用于组合图",
                detail="当前图表启用了双轴，但不是组合图。",
                suggestion="改用组合图，或关闭双轴。",
            ))
        elif len(chart.series) < 2:
            issues.append(ChartQualityIssue(
                id="dual-axis-missing-measure", severity="error", title="双轴缺少第二指标",
                detail="双轴图至少需要两个数值指标。",
                suggestion="增加第二指标，或关闭双轴。",
            ))
        elif not chart.style.unit:
            issues.append(ChartQualityIssue(
                id="dual-axis-missing-unit", severity="warning", title="双轴缺少单位说明",
                detail="不同量纲放在双轴上容易被误读。",
                suggestion="填写统一单位，或在标题/说明中明确左右轴分别代表什么。",
            ))
    if chart.style.palette == "risk" and len(chart.series) > 1:
        issues.append(ChartQualityIssue(
            id="risk-palette-accessibility", severity="info", title="风险配色不适合作为多系列默认色",
            detail="红绿类组合对部分色觉差异用户辨识度较低。",
            suggestion="改用“无障碍”配色，或同时启用标签和形状区分。",
        ))
    if not chart.style.unit and chart.chart_type not in {"table", "pie", "donut", "treemap"}:
        issues.append(ChartQualityIssue(
            id="missing-unit", severity="info", title="缺少指标单位", detail="读者难以判断数值是金额、数量、比例还是其他单位。",
            suggestion="在图表设置中填写单位，例如“元”“件”“%”。",
        ))
    if not chart.style.source_label and not chart.evidence_ids:
        issues.append(ChartQualityIssue(
            id="missing-source", severity="warning", title="缺少数据来源", detail="该图表没有来源标签或证据引用。",
            suggestion="绑定报告证据，或填写数据来源说明。",
        ))
    if chart.style.scenario == "research" and chart.chart_type in {"bar", "line", "area", "scatter"} and not chart.style.show_error_bars:
        issues.append(ChartQualityIssue(
            id="research-no-uncertainty", severity="warning", title="科研图表未表达不确定性",
            detail="均值或估计值图通常需要误差线、置信区间或样本量说明。",
            suggestion="启用误差线，并在说明中注明置信区间、样本量和统计方法。",
        ))
    if not chart.title.strip():
        issues.append(ChartQualityIssue(
            id="missing-title", severity="warning", title="缺少图表标题",
            detail="读者无法快速理解比较对象和分析口径。",
            suggestion="补充指标、维度和时间范围。",
        ))
    score = max(0, 100 - sum({"error": 30, "warning": 12, "info": 3}[item.severity] for item in issues))
    return ChartQualityReport(score=score, issues=issues)


def chart_version_hint(chart: ChartSpec) -> str:
    """Stable optimistic-lock token for a selected chart, without adding a DB migration."""
    import hashlib
    import json

    payload = chart.model_dump(mode="json", exclude={"data"})
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def apply_computed_chart(chart: ChartSpec, data: list[dict[str, Any]], evidence_id: str) -> ChartSpec:
    payload = deepcopy(chart.model_dump(mode="python"))
    payload["data"] = data
    payload["evidence_ids"] = list(dict.fromkeys([*(payload.get("evidence_ids") or []), evidence_id]))
    return ChartSpec.model_validate(payload)
