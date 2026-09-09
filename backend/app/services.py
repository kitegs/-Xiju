from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import duckdb

from .config import DATA_DIR
from .schemas import (
    ChartSpec, CleaningStep, DataQualityIssue, DataQualitySummary, Evidence, ReportActionItem,
    ReportBlock, ReportDocument, ReportFinding, ReportQualityIssue, ReportQualityReport,
)


def storage_path(storage_key: str) -> Path:
    path = (DATA_DIR / storage_key).resolve()
    root = DATA_DIR.resolve()
    if root not in path.parents:
        raise ValueError("Invalid storage key")
    return path


def read_dataframe(storage_key: str) -> pd.DataFrame:
    path = storage_path(storage_key)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("Unsupported dataset format")


def profile_dataframe(frame: pd.DataFrame) -> dict:
    columns = []
    for name in frame.columns:
        series = frame[name]
        item = {
            "name": str(name), "dtype": str(series.dtype), "null_count": int(series.isna().sum()),
            "unique_count": int(series.nunique(dropna=True)),
            "semantic_type": _semantic_type(str(name), series),
            "sample_values": [_json_cell(value) for value in series.dropna().drop_duplicates().head(5).tolist()],
            "constant": bool(len(frame) > 1 and series.nunique(dropna=True) <= 1),
        }
        if pd.api.types.is_numeric_dtype(series):
            item.update({"min": _json_number(series.min()), "max": _json_number(series.max()), "mean": _json_number(series.mean())})
        if item["semantic_type"] == "date":
            text = series.dropna().astype(str).str.strip()
            parsed = pd.to_datetime(text, errors="coerce", format="mixed")
            has_calendar_date = text.str.contains(r"(?:19|20)\d{2}", regex=True, na=False)
            item["invalid_count"] = int((parsed.isna() | ~has_calendar_date).sum())
        columns.append(item)
    return {
        "row_count": int(len(frame)), "column_count": int(len(frame.columns)), "columns": columns,
        "read_mode": "full", "is_truncated": False,
    }


def dataframe_rows(frame: pd.DataFrame, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    sample = frame.iloc[offset:offset + limit]
    return [{str(column): _json_cell(value) for column, value in row.items()} for row in sample.to_dict(orient="records")]


def quality_summary(frame: pd.DataFrame) -> DataQualitySummary:
    issues: list[DataQualityIssue] = []
    total_cells = max(len(frame) * len(frame.columns), 1)
    missing_cells = int(frame.isna().sum().sum())
    duplicate_rows = int(frame.duplicated().sum())
    for column in frame.columns:
        series = frame[column]
        missing = int(series.isna().sum())
        if missing:
            rate = missing / max(len(frame), 1)
            issues.append(DataQualityIssue(
                id=f"missing:{column}", severity="error" if rate >= .3 else "warning",
                issue_type="missing", title=f"“{column}”存在缺失值",
                detail=f"{missing:,} 行缺失（{rate:.1%}）", columns=[str(column)],
            ))
        unique_count = int(series.nunique(dropna=True))
        if len(frame) > 1 and unique_count <= 1:
            issues.append(DataQualityIssue(
                id=f"constant:{column}", severity="warning", issue_type="constant",
                title=f"“{column}”只有一个有效值",
                detail="该字段无法用于分组、趋势或相关分析，可能是导入或格式解析问题。", columns=[str(column)],
            ))
        semantic_type = _semantic_type(str(column), series)
        if semantic_type == "date":
            text = series.dropna().astype(str).str.strip()
            parsed = pd.to_datetime(text, errors="coerce", format="mixed")
            has_calendar_date = text.str.contains(r"(?:19|20)\d{2}", regex=True, na=False)
            invalid = int((parsed.isna() | ~has_calendar_date).sum())
            if invalid:
                rate = invalid / max(len(text), 1)
                issues.append(DataQualityIssue(
                    id=f"invalid_date:{column}", severity="error" if rate >= .3 else "warning",
                    issue_type="invalid_date", title=f"“{column}”不是可用的日历日期",
                    detail=f"{invalid:,} 个有效值无法识别为包含年份的日期（{rate:.1%}）", columns=[str(column)],
                ))
        if series.dtype == "object":
            text = series.dropna().astype(str)
            whitespace = int((text != text.str.strip()).sum())
            if whitespace:
                issues.append(DataQualityIssue(
                    id=f"whitespace:{column}", severity="info", issue_type="whitespace",
                    title=f"“{column}”含首尾空格", detail=f"发现 {whitespace:,} 个可能需要修剪的值", columns=[str(column)],
                ))
    if duplicate_rows:
        issues.append(DataQualityIssue(
            id="duplicates", severity="warning", issue_type="duplicates", title="存在重复记录",
            detail=f"发现 {duplicate_rows:,} 行完全重复的数据", columns=[],
        ))
    constant_count = sum(issue.issue_type == "constant" for issue in issues)
    invalid_date_count = sum(issue.issue_type == "invalid_date" for issue in issues)
    penalty = (
        min(55, round(missing_cells / total_cells * 100))
        + min(20, round(duplicate_rows / max(len(frame), 1) * 100))
        + min(15, constant_count * 3)
        + min(25, invalid_date_count * 10)
    )
    return DataQualitySummary(score=max(0, 100 - penalty), missing_cells=missing_cells, duplicate_rows=duplicate_rows, issues=issues)


def apply_cleaning_steps(frame: pd.DataFrame, steps: list[CleaningStep]) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    result = frame.copy(deep=True)
    step_results: list[dict[str, Any]] = []
    changed_cells = 0
    for index, step in enumerate(steps, 1):
        before_rows = len(result)
        before_snapshot = result.copy(deep=True)
        description = _apply_cleaning_step(result, step)
        result = result.reset_index(drop=True)
        same_shape = len(before_snapshot) == len(result) and list(before_snapshot.columns) == list(result.columns)
        if same_shape and len(result):
            left = before_snapshot.reset_index(drop=True).astype("string").fillna("<NA>")
            right = result.reset_index(drop=True).astype("string").fillna("<NA>")
            changed_cells += int((left != right).sum().sum())
        step_results.append({
            "index": index, "operation": step.operation, "description": description,
            "before_rows": before_rows, "after_rows": len(result), "removed_rows": before_rows - len(result),
        })
    return result, step_results, changed_cells


def _require_column(frame: pd.DataFrame, column: str | None) -> str:
    if not column or column not in frame.columns:
        raise ValueError(f"字段不存在：{column or '未选择'}")
    return column


def _apply_cleaning_step(frame: pd.DataFrame, step: CleaningStep) -> str:
    if step.operation == "drop_duplicates":
        subset = step.columns or None
        unknown = [column for column in (subset or []) if column not in frame.columns]
        if unknown:
            raise ValueError(f"去重字段不存在：{', '.join(unknown)}")
        before = len(frame)
        frame.drop_duplicates(subset=subset, inplace=True)
        return f"删除 {before - len(frame)} 行重复记录"

    column = _require_column(frame, step.column)
    if step.operation == "fill_missing":
        if not step.method:
            raise ValueError("缺失值填充需要选择方法")
        missing = int(frame[column].isna().sum())
        if step.method == "constant":
            fill_value = step.value
        elif step.method in {"mean", "median"}:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            fill_value = numeric.mean() if step.method == "mean" else numeric.median()
            if pd.isna(fill_value):
                raise ValueError(f"字段“{column}”无法计算{step.method}")
            frame[column] = numeric
        else:
            modes = frame[column].mode(dropna=True)
            if modes.empty:
                raise ValueError(f"字段“{column}”没有可用于众数填充的值")
            fill_value = modes.iloc[0]
        frame[column] = frame[column].fillna(fill_value)
        return f"填充“{column}”的 {missing} 个缺失值"
    if step.operation == "convert_type":
        if not step.target_type:
            raise ValueError("类型转换需要目标类型")
        if step.target_type == "text":
            frame[column] = frame[column].astype("string")
        elif step.target_type == "integer":
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round().astype("Int64")
        elif step.target_type == "float":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        elif step.target_type == "date":
            frame[column] = pd.to_datetime(
                frame[column], errors="coerce", format=step.date_format or "mixed",
            ).dt.strftime("%Y-%m-%d")
        elif step.target_type == "boolean":
            mapping = {"true": True, "1": True, "yes": True, "是": True, "false": False, "0": False, "no": False, "否": False}
            frame[column] = frame[column].map(lambda value: mapping.get(str(value).strip().lower()) if not pd.isna(value) else pd.NA).astype("boolean")
        return f"将“{column}”转换为 {step.target_type}"
    if step.operation == "trim_text":
        non_null = frame[column].notna()
        frame.loc[non_null, column] = frame.loc[non_null, column].astype(str).str.strip()
        return f"修剪“{column}”的首尾空格"
    if step.operation == "replace_value":
        matches = int((frame[column].astype("string") == str(step.old_value)).sum())
        frame.loc[frame[column].astype("string") == str(step.old_value), column] = step.new_value
        return f"替换“{column}”中的 {matches} 个值"
    if step.operation == "rename_column":
        new_name = (step.new_name or "").strip()
        if not new_name:
            raise ValueError("新字段名不能为空")
        if new_name != column and new_name in frame.columns:
            raise ValueError(f"字段名已存在：{new_name}")
        frame.rename(columns={column: new_name}, inplace=True)
        return f"将“{column}”改名为“{new_name}”"
    if step.operation == "filter_rows":
        if not step.operator:
            raise ValueError("筛选需要选择条件")
        series = frame[column]
        if step.operator == "not_empty":
            mask = series.notna() & series.astype("string").str.strip().ne("")
        elif step.operator == "contains":
            mask = series.astype("string").str.contains(str(step.value), case=False, na=False, regex=False)
        elif step.operator in {"gt", "gte", "lt", "lte"}:
            numeric = pd.to_numeric(series, errors="coerce")
            try:
                expected = float(step.value)
            except (TypeError, ValueError) as exc:
                raise ValueError("数值筛选条件必须填写数字") from exc
            mask = {"gt": numeric > expected, "gte": numeric >= expected, "lt": numeric < expected, "lte": numeric <= expected}[step.operator]
        else:
            mask = series.astype("string").eq(str(step.value))
            if step.operator == "neq":
                mask = ~mask
        frame.drop(index=frame.index[~mask.fillna(False)], inplace=True)
        return f"按“{column}”筛选，保留 {len(frame)} 行"
    raise ValueError(f"不支持的清洗操作：{step.operation}")


def build_report(
    frame: pd.DataFrame, profile: dict, title: str, prompt: str, semantics: dict | None = None,
) -> ReportDocument:
    """Create an evidence-bound report using business-aware field selection.

    The model may describe the result later, but every number and chart here is
    produced locally from the complete dataframe.
    """
    semantics = semantics or {}
    column_labels = semantics.get("column_labels") or {}
    value_labels = semantics.get("value_labels") or {}
    non_additive = set(semantics.get("non_additive_columns") or [])
    ignored = {column for column, role in (semantics.get("column_roles") or {}).items() if role in {"id", "ignore"}}
    numeric = [
        str(c) for c in frame.columns
        if pd.api.types.is_numeric_dtype(frame[c]) and str(c) not in non_additive and str(c) not in ignored
        and not re.search(r"(^|[_\s-])(id|index|instant|row)([_\s-]|$)", str(c), re.I)
    ]
    categorical = [str(c) for c in frame.columns if not pd.api.types.is_numeric_dtype(frame[c])]
    sales = _find_column(frame, ["sales", "revenue", "amount", "销售额", "营收", "收入"])
    profit = _find_column(frame, ["profit", "利润", "毛利"])
    discount = _find_column(frame, ["discount", "折扣"])
    quantity = _find_column(frame, ["quantity", "qty", "数量", "cnt", "rental count", "rentals", "bike count"])
    date_column = _find_column(frame, ["order date", "date", "dteday", "订单日期", "日期", "时间"])
    for column, role in (semantics.get("column_roles") or {}).items():
        if role == "date" and column in frame.columns:
            date_column = column
    sales = sales if sales in numeric else None
    profit = profit if profit in numeric else None
    quantity = quantity if quantity in numeric else None
    discount = discount if discount in numeric else None
    measure = sales or profit or quantity or (numeric[0] if numeric else None)
    declared_dimensions = [
        column for column, role in (semantics.get("column_roles") or {}).items()
        if role == "dimension" and column in frame.columns
    ]
    alias_dimensions = []
    for aliases in (
        ["region", "区域", "地区"], ["market", "市场"], ["category", "品类", "类别"],
        ["sub-category", "subcategory", "子类别", "子品类"], ["segment", "客户细分", "细分"],
    ):
        column = _find_column(frame, aliases)
        if column:
            alias_dimensions.append(column)
    dimensions = list(dict.fromkeys([*declared_dimensions, *alias_dimensions]))
    if not dimensions and categorical:
        dimensions = [column for column in categorical if column != date_column][:1]
    if len(dimensions) < 2:
        low_cardinality = [
            str(column) for column in frame.columns
            if str(column) not in {measure, sales, profit, quantity, discount, date_column, *ignored, *non_additive}
            and 1 < frame[column].nunique(dropna=True) <= min(24, max(4, len(frame) // 20))
            and not re.search(r"(^|[_\s-])(id|index|instant|row)([_\s-]|$)", str(column), re.I)
        ]
        dimensions = list(dict.fromkeys([*dimensions, *low_cardinality]))[:2]

    evidence: list[Evidence] = [Evidence(
        id="dataset-shape", statement="完整数据集规模", method="导入文件全量读取",
        value=f"{len(frame):,} 行 × {len(frame.columns)} 列", source_columns=[],
    )]
    relationship = semantics.get("relationship_id")
    if relationship:
        relationship_warning = "；".join(semantics.get("warnings") or []) or "已按已验证关系生成分析副本"
        evidence.append(Evidence(
            id="dataset-relationship", statement="多表关系与分析粒度",
            method=f"{semantics.get('cardinality', 'relationship')} 关系物化；保留来源版本与字段血缘",
            value=f"当前粒度：{semantics.get('grain', '左表明细粒度')}。{relationship_warning}",
            source_columns=list((semantics.get("field_lineage") or {}).keys())[:50],
        ))
    charts: list[ChartSpec] = []
    findings: list[ReportFinding] = []
    actions: list[ReportActionItem] = []
    blocks: list[ReportBlock] = [
        ReportBlock(id="executive-title", kind="heading", content="管理层摘要"),
        ReportBlock(id="shape", kind="paragraph", content=f"分析覆盖完整的 {len(frame):,} 行数据和 {len(frame.columns)} 个字段。报告中的数字、图表和结论均绑定本地计算证据。", evidence_ids=["dataset-shape"]),
    ]
    if relationship:
        blocks.append(ReportBlock(
            id="relationship-grain", kind="callout",
            content=f"多表口径：当前结果保持{semantics.get('grain', '左表明细粒度')}。右表展开字段不得直接求和：{'、'.join(sorted(non_additive)) or '无'}。",
            evidence_ids=["dataset-relationship"],
        ))

    metric_ids: list[str] = []
    metric_values: dict[str, float] = {}
    metric_specs = (
        ("sales", sales, column_labels.get(sales, "总销售额")),
        ("profit", profit, column_labels.get(profit, "总利润")),
        ("quantity", quantity, f"总{column_labels.get(quantity, '数量')}" if quantity else "总数量"),
    )
    for key, column, label in metric_specs:
        if not column or column in non_additive:
            continue
        total = float(pd.to_numeric(frame[column], errors="coerce").sum(skipna=True))
        metric_values[key] = total
        evidence_id = f"metric-{key}"
        evidence.append(Evidence(
            id=evidence_id, statement=label, method=f"SUM({column})",
            calculation={"operation": "sum", "operands": [total], "result": total, "unit": "number", "metric": column,
                         "facts": [{"role": "total", "value": total, "unit": "number"}]},
            value=_format_number(total), source_columns=[column], code=f'SELECT SUM("{column}") FROM dataset',
        ))
        metric_ids.append(evidence_id)
        charts.append(ChartSpec(
            id=f"kpi-{key}", title=label, chart_type="kpi", y={"column": column, "aggregate": "sum"},
            data=[{"label": label, "value": _json_number(total)}], evidence_ids=[evidence_id],
            position={"x": 0, "y": 0, "w": 3, "h": 2},
            style={"palette": "accessible", "show_legend": False, "show_toolbox": False, "number_format": "compact", "height": 150, "unit": (semantics.get("column_units") or {}).get(column, semantics.get("unit", "")), "source_label": "完整导入数据，本地确定性计算"},
        ))
    if relationship and measure:
        field_lineage = semantics.get("field_lineage") or {}
        right_equivalent = next((
            output for output, lineage in field_lineage.items()
            if lineage.get("source_side") == "right" and lineage.get("source_column") == measure
            and output in non_additive and output in frame.columns
        ), None)
        left_keys = [column for column in semantics.get("left_keys") or [] if column in frame.columns]
        if right_equivalent and left_keys:
            left_total = float(pd.to_numeric(frame[measure], errors="coerce").sum(skipna=True))
            right_total = float(pd.to_numeric(
                frame.drop_duplicates(subset=left_keys)[right_equivalent], errors="coerce",
            ).sum(skipna=True))
            difference = left_total - right_total
            evidence.append(Evidence(
                id="relationship-reconciliation", statement="左右表同名指标独立口径核对",
                method=f"左表 SUM({measure})；右表先按 {' + '.join(left_keys)} 去重后 SUM({right_equivalent})",
                value=f"左表 {_format_number(left_total)}；右表 {_format_number(right_total)}；差额 {_format_number(difference)}",
                source_columns=[*left_keys, measure, right_equivalent],
                calculation={"operation": "sum", "operands": [right_total], "result": right_total, "unit": "number", "metric": right_equivalent,
                             "facts": [{"role": "left_total", "value": left_total, "unit": "number"}, {"role": "right_total", "value": right_total, "unit": "number"}, {"role": "difference", "value": difference, "unit": "number"}]},
                code=(f'SELECT (SELECT SUM("{measure}") FROM dataset) AS left_total, '
                      f'(SELECT SUM(right_value) FROM (SELECT MAX("{right_equivalent}") AS right_value '
                      'FROM dataset GROUP BY ' + ', '.join('"' + key.replace('"', '""') + '"' for key in left_keys)
                      + ')) AS right_total'),
            ))
            blocks.append(ReportBlock(
                id="relationship-reconciliation", kind="paragraph",
                content=f"跨表核对：左表 {measure} 合计 {_format_number(left_total)}；右表 {right_equivalent} 按关联键去重后合计 {_format_number(right_total)}，差额 {_format_number(difference)}。右表值未在小时明细上重复累计。",
                evidence_ids=["relationship-reconciliation"],
            ))
    if sales and profit:
        total_sales = metric_values["sales"]
        total_profit = metric_values["profit"]
        margin = total_profit / total_sales if total_sales else math.nan
        evidence.append(Evidence(
            id="metric-margin", statement="总体利润率", method=f"SUM({profit}) / SUM({sales})",
            calculation={"operation":"ratio", "operands":[total_profit,total_sales], "result":margin, "unit":"ratio", "metric":"margin",
                         "facts":[{"role":"ratio", "value":margin * 100, "unit":"percent"}]} if math.isfinite(margin) else None,
            value=f"{margin:.2%}" if math.isfinite(margin) else "—", source_columns=[sales, profit],
            code=f'SELECT SUM("{profit}") / NULLIF(SUM("{sales}"), 0) FROM dataset',
        ))
        metric_ids.append("metric-margin")
        charts.append(ChartSpec(
            id="kpi-margin", title="总体利润率", chart_type="kpi", y={"column": profit, "aggregate": "sum"},
            data=[{"label": "总体利润率", "value": round(margin * 100, 4) if math.isfinite(margin) else None, "suffix": "%"}],
            evidence_ids=["metric-margin"], position={"x": 0, "y": 0, "w": 3, "h": 2},
            style={"palette": "accessible", "show_legend": False, "show_toolbox": False, "number_format": "percent", "height": 150, "unit": "%", "source_label": "完整导入数据，本地确定性计算"},
        ))
    if metric_ids:
        parts = []
        if "sales" in metric_values: parts.append(f"总销售额为 {_format_number(metric_values['sales'])}")
        if "profit" in metric_values: parts.append(f"总利润为 {_format_number(metric_values['profit'])}")
        if "quantity" in metric_values: parts.append(f"总{column_labels.get(quantity, '数量')}为 {_format_number(metric_values['quantity'])}")
        if sales and profit and math.isfinite(margin): parts.append(f"总体利润率为 {margin:.2%}")
        finding = ReportFinding(
            id="finding-overall", headline="核心经营规模已完成全量核算",
            statement="，".join(parts) + "。" if parts else "核心指标已完成全量核算。",
            business_impact="这些指标是后续趋势、结构和风险分析的统一基线。",
            recommendation="经营复盘应同时观察规模与利润率，避免只按销售额判断表现。" if sales and profit else "结合时间、分类分布与数据覆盖范围解释总量；相关关系不代表因果。",
            evidence_ids=metric_ids,
        )
        findings.append(finding); blocks.append(_finding_block(finding))
        for chart in [item for item in charts if item.chart_type == "kpi"]:
            blocks.append(ReportBlock(id=f"block-{chart.id}", kind="chart", chart_id=chart.id, evidence_ids=chart.evidence_ids, style={"width": "quarter"}))

    trend = _time_trend(
        frame, date_column, measure, (semantics.get("date_formats") or {}).get(date_column),
    ) if date_column and measure else None
    if trend:
        trend_data, period_label, change = trend
        measure_label = column_labels.get(measure, measure)
        period_frequency = {"年": "Y", "月": "M", "日": "D"}[period_label]
        date_format = (semantics.get("date_formats") or {}).get(date_column) or "mixed"
        trend_evidence = Evidence(
            id="trend-primary", statement=f"{measure_label}时间趋势", method=f"按{period_label}汇总 SUM({measure})",
            calculation={"operation":"growth", "operands":[trend_data[-1][measure],trend_data[0][measure]], "result":change, "unit":"ratio", "metric":measure, "period_kind":"interval", "current_period":trend_data[-1]['period'], "baseline_period":trend_data[0]['period'],
                         "facts":[{"role":"baseline", "value":trend_data[0][measure], "unit":"number"}, {"role":"current", "value":trend_data[-1][measure], "unit":"number"}, {"role":"change", "value":change * 100, "unit":"percent"}]},
            value=f"{trend_data[0]['period']} 为 {_format_number(trend_data[0][measure])}，{trend_data[-1]['period']} 为 {_format_number(trend_data[-1][measure])}，区间变化 {change:+.2%}",
            source_columns=[date_column, measure], data=trend_data,
            code=(f'dates = pd.to_datetime(frame[{date_column!r}], errors="coerce", format={date_format!r})\n'
                  f'values = pd.to_numeric(frame[{measure!r}], errors="coerce")\n'
                  'valid = dates.notna() & values.notna()\n'
                  f'result = pd.DataFrame({{"period": dates[valid].dt.to_period({period_frequency!r}).astype(str), '
                  f'{measure!r}: values[valid].to_numpy()}}).groupby("period", as_index=False)[{measure!r}].sum().sort_values("period").head(120)'),
        )
        evidence.append(trend_evidence)
        direction = "上升" if change >= 0 else "下降"
        trend_chart = ChartSpec(
            id="primary-trend", title=f"{measure_label}从 {trend_data[0]['period']} 到 {trend_data[-1]['period']} {direction} {abs(change):.1%}", chart_type="line",
            x={"column": "period"}, y={"column": measure, "aggregate": "sum"}, series=[{"column": measure, "aggregate": "sum"}],
            description=f"按{period_label}汇总完整数据。首末期变化用于描述区间方向，不等同于同比或因果结论。",
            data=trend_data, evidence_ids=[trend_evidence.id], position={"x": 0, "y": 0, "w": 12, "h": 5},
            style={"palette": "accessible", "show_legend": False, "show_labels": False, "number_format": "compact", "height": 320, "unit": (semantics.get("column_units") or {}).get(measure, semantics.get("unit", "")), "source_label": "完整导入数据，本地确定性计算"},
        )
        charts.insert(0, trend_chart)
        finding = ReportFinding(
            id="finding-trend", headline=trend_chart.title,
            statement=trend_evidence.value + "。", business_impact="时间趋势用于识别增长方向和需要进一步解释的拐点。",
            recommendation="结合上一周期或业务目标复核变化来源，再决定资源调整。", caveats=["首末期变化不等同于同比。"], evidence_ids=[trend_evidence.id],
        )
        findings.append(finding)
        blocks.extend([ReportBlock(id="trend-title", kind="heading", content="时间趋势"), _finding_block(finding), ReportBlock(id="trend-chart", kind="chart", chart_id=trend_chart.id, evidence_ids=[trend_evidence.id])])

    if measure and dimensions:
        blocks.append(ReportBlock(id="comparison-title", kind="heading", content="结构与贡献"))
        for index, dimension in enumerate(dimensions[:4]):
            grouped = _grouped_records(frame, dimension, [measure], 10)
            if not grouped:
                continue
            dimension_label = column_labels.get(dimension, dimension)
            measure_label = column_labels.get(measure, measure)
            labels = value_labels.get(dimension) or {}
            for row in grouped:
                row[dimension] = labels.get(str(row.get(dimension)), row.get(dimension))
            total = float(pd.to_numeric(frame[measure], errors="coerce").sum(skipna=True))
            top_value = float(grouped[0].get(measure) or 0)
            share = top_value / total if total else math.nan
            evidence_id = "group-primary" if index == 0 else f"group-{_slug(dimension)}"
            grouped_evidence = Evidence(
                id=evidence_id, statement=f"按{dimension_label}汇总{measure_label}", method=f"GROUP BY {dimension}；SUM({measure})；降序取前 10 项",
                calculation={"operation":"rank", "operands":[float(row[measure]) for row in grouped], "candidate":top_value, "result":1, "unit":"rank", "metric":measure, "dimension":dimension, "member":str(grouped[0].get(dimension)),
                             "facts":[{"role":"top_value", "value":top_value, "unit":"number"}, *([{"role":"share", "value":share * 100, "unit":"percent"}] if math.isfinite(share) else [])]},
                value=f"{dimension_label}“{grouped[0].get(dimension)}”的{measure_label}最高，为 {_format_number(top_value)}" + (f"，占全部 {share:.2%}" if math.isfinite(share) else ""),
                source_columns=[dimension, measure], data=grouped,
                code=f'SELECT "{dimension}", SUM("{measure}") AS "{measure}" FROM dataset GROUP BY 1 ORDER BY 2 DESC LIMIT 10',
            )
            evidence.append(grouped_evidence)
            chart = ChartSpec(
                id="primary-comparison" if index == 0 else f"comparison-{_slug(dimension)}", title=grouped_evidence.value, chart_type="bar",
                x={"column": dimension}, y={"column": measure, "aggregate": "sum"}, series=[{"column": measure, "aggregate": "sum"}],
                description=f"按{dimension_label}汇总完整数据并降序排列；显示前 {len(grouped)} 项。占比以全部{measure_label}为分母。",
                data=grouped, evidence_ids=[grouped_evidence.id], position={"x": 0, "y": 0, "w": 12, "h": 5},
                style={"palette": "accessible", "show_legend": False, "show_labels": True, "orientation": "horizontal" if len(grouped) > 6 else "vertical", "number_format": "compact", "height": 320, "unit": (semantics.get("column_units") or {}).get(measure, semantics.get("unit", "")), "source_label": "完整导入数据，本地确定性计算"},
            )
            charts.insert(index + (1 if trend else 0), chart)
            finding = ReportFinding(
                id=f"finding-{evidence_id}", headline=chart.title, statement=grouped_evidence.value + "。",
                business_impact="该结果展示指标的结构集中度，但不能单独说明盈利质量或形成原因。" if sales and profit else "累计量受观测数量和时间覆盖影响，不能直接解释需求强度或形成原因。",
                recommendation=f"继续比较{dimension_label}的增长、稳定性或目标完成率，确认头部分组是否持续。",
                evidence_ids=[grouped_evidence.id],
            )
            findings.append(finding); blocks.extend([_finding_block(finding), ReportBlock(id=f"block-{chart.id}", kind="chart", chart_id=chart.id, evidence_ids=[grouped_evidence.id])])
            if index == 0:
                actions.append(ReportActionItem(
                    id="action-structure", action=f"复核头部{dimension_label}的增长与稳定性。",
                    rationale="销售或规模排名不能替代盈利质量判断。" if sales and profit else "累计量排名不能替代同观测时间口径下的需求比较。", priority="medium",
                    expected_impact="避免仅按单一总量分配资源。", validation_metric=f"头部{dimension_label}的增长率与波动", evidence_ids=[grouped_evidence.id],
                ))

    if discount and profit:
        all_scatter = pd.DataFrame({discount: pd.to_numeric(frame[discount], errors="coerce"), profit: pd.to_numeric(frame[profit], errors="coerce")}).dropna()
        correlation = float(all_scatter[discount].corr(all_scatter[profit])) if len(all_scatter) > 1 else math.nan
        risky = all_scatter[(all_scatter[discount] >= .3) & (all_scatter[profit] < 0)]
        scatter_frame = all_scatter.sample(n=min(1200, len(all_scatter)), random_state=42) if len(all_scatter) else all_scatter
        scatter_data = dataframe_rows(scatter_frame, limit=1200)
        evidence.append(Evidence(
            id="discount-profit", statement="折扣与利润的线性关系及高折扣亏损记录", method="Pearson correlation；筛选 Discount >= 0.3 且 Profit < 0",
            calculation={"operation":"correlation", "operands":[], "result":correlation, "unit":"correlation", "metric":profit,
                         "facts":[{"role":"correlation", "value":correlation, "unit":"number"}, {"role":"sample_count", "value":len(all_scatter), "unit":"count"}, {"role":"risk_count", "value":len(risky), "unit":"count"}]} if math.isfinite(correlation) else None,
            value=f"相关系数 {correlation:.4f}；有效样本 {len(all_scatter):,}；高折扣亏损记录 {len(risky):,} 条",
            source_columns=[discount, profit], data=scatter_data[:50], code=f'frame[["{discount}", "{profit}"]].corr(); frame[(frame["{discount}"] >= 0.3) & (frame["{profit}"] < 0)]',
        ))
        scatter = ChartSpec(
            id="discount-profit-scatter", title=f"高折扣亏损记录共 {len(risky):,} 条", chart_type="scatter",
            x={"column": discount}, y={"column": profit, "aggregate": None}, series=[{"column": profit, "aggregate": None}], data=scatter_data,
            description=f"每个点代表一条有效记录。折扣与利润的 Pearson 相关系数为 {correlation:.4f}；相关性仅用于探索，不代表折扣导致利润变化。",
            evidence_ids=["discount-profit"], position={"x": 0, "y": 0, "w": 12, "h": 5},
            style={"palette": "accessible", "show_legend": False, "show_labels": False, "number_format": "auto", "height": 320, "source_label": "完整导入数据，本地确定性计算"},
        )
        charts.append(scatter)
        finding = ReportFinding(
            id="finding-discount-risk", headline=scatter.title,
            statement=f"在 {len(all_scatter):,} 条有效记录中，折扣不低于 0.3 且利润为负的记录有 {len(risky):,} 条；折扣与利润的线性相关系数为 {correlation:.4f}。",
            business_impact="高折扣亏损记录是可直接复核的风险清单。",
            recommendation="按区域、品类和客户继续拆分这些记录，确认折扣规则、产品毛利或履约成本是否需要调整。",
            caveats=["相关性不代表因果关系。", "0.3 是筛查阈值，不是业务审批阈值。"], evidence_ids=["discount-profit"],
        )
        findings.append(finding)
        actions.append(ReportActionItem(
            id="action-discount-risk", action="复核高折扣亏损记录并定位集中分组。",
            rationale=f"当前筛查发现 {len(risky):,} 条折扣不低于 0.3 且利润为负的记录。", priority="high",
            expected_impact="减少可识别的折扣相关亏损风险。", validation_metric="高折扣亏损记录数及亏损额", evidence_ids=["discount-profit"],
        ))
        blocks.extend([ReportBlock(id="risk-title", kind="heading", content="风险与进一步调查"), _finding_block(finding), ReportBlock(id="discount-profit-block", kind="chart", chart_id=scatter.id, evidence_ids=["discount-profit"])])

    invalid_dates = [item for item in profile.get("columns", []) if item.get("semantic_type") == "date" and item.get("invalid_count")]
    if invalid_dates:
        invalid_value = "；".join(f"{item['name']} 有 {item['invalid_count']:,} 个不可识别值" for item in invalid_dates)
        evidence.append(Evidence(
            id="data-limit-date", statement="日期字段限制", method="全列日期解析与日历年份检查",
            value=invalid_value, source_columns=[item["name"] for item in invalid_dates],
            code="pd.to_datetime(column, errors='coerce')",
        ))
        blocks.extend([
            ReportBlock(id="limitations-title", kind="heading", content="数据限制"),
            ReportBlock(id="date-limit", kind="paragraph", content=f"{invalid_value}。因此本报告未生成不可靠的时间趋势；请在数据工作台恢复完整日期后重新运行。", evidence_ids=["data-limit-date"]),
        ])

    if actions:
        blocks.extend([
            ReportBlock(id="actions-title", kind="heading", content="建议行动"),
            ReportBlock(id="actions", kind="callout", content="\n".join(f"{index}. {item.action} 验证指标：{item.validation_metric}。" for index, item in enumerate(actions, 1)), evidence_ids=list(dict.fromkeys(evidence_id for item in actions for evidence_id in item.evidence_ids))),
        ])
    if not measure:
        blocks.append(ReportBlock(id="note", kind="callout", content="未检测到可汇总的数值列。请先在数据工作台修正字段类型。"))
    blocks.append(ReportBlock(id="review", kind="paragraph", content="限制说明：统计关系不等于因果关系。正式发布前仍需结合业务定义确认指标口径、币种和目标基准。"))
    summary_parts = ["本报告使用完整数据进行确定性计算"]
    if "sales" in metric_values: summary_parts.append(f"总销售额 {_format_number(metric_values['sales'])}")
    if "profit" in metric_values: summary_parts.append(f"总利润 {_format_number(metric_values['profit'])}")
    if "quantity" in metric_values: summary_parts.append(f"总{column_labels.get(quantity, '数量')} {_format_number(metric_values['quantity'])}")
    summary = "；".join(summary_parts) + "。关键结论和行动建议均可追溯到证据。"
    result = ReportDocument(
        version="2.0", title=title, summary=summary, blocks=blocks, charts=charts, evidence=evidence,
        findings=findings, actions=actions,
        metadata={"prompt": prompt, "profile": profile, "semantics": semantics, "generation": "deterministic-v3", "row_count": len(frame), "column_count": len(frame.columns), "is_truncated": False},
    )
    from .observational import attach_hourly_comparisons
    attach_hourly_comparisons(result, frame, semantics)
    from .report_claims import seal_claims
    seal_claims(result)
    result.quality = assess_report_quality(result)
    return result


def assess_report_quality(document: ReportDocument | dict[str, Any]) -> ReportQualityReport:
    """Run a deterministic publication gate over content, evidence and chart semantics."""
    from .charting import quality_report

    report = document if isinstance(document, ReportDocument) else ReportDocument.model_validate(document)
    from .report_claims import check_claims
    claim_checks = check_claims(report)
    issues: list[ReportQualityIssue] = []
    evidence_ids = [item.id for item in report.evidence]
    evidence_set = set(evidence_ids)
    chart_ids = {item.id for item in report.charts}
    fields = (report.metadata.get("profile") or {}).get("columns", [])

    def add(issue_id: str, severity: str, title: str, detail: str, suggestion: str = "") -> None:
        issues.append(ReportQualityIssue(id=issue_id, severity=severity, title=title, detail=detail, suggestion=suggestion))

    if (report.metadata.get('execution_outcome') or {}).get('status') == 'degraded':
        add('execution-degraded', 'error', '运行含失败或降级', '部分工具或总结未成功，不能将局部结果标为完整交付。', '查看执行记录，解决失败步骤后重新运行；文字重算不能替代缺失分析。')
    if len(evidence_ids) != len(evidence_set):
        add("duplicate-evidence-id", "error", "证据编号重复", "证据编号必须唯一，否则结论无法稳定追溯。", "重新生成重复编号的证据。")
    if not report.findings:
        add("missing-findings", "error", "缺少结构化结论", "报告只有图表或段落，没有可检查的关键结论。", "至少生成一条包含业务影响和证据编号的结论。")
    if not report.actions:
        add("missing-actions", "warning", "缺少行动建议", "商业报告没有明确的后续动作和验证指标。", "增加负责人可确认、结果可验证的行动项。")
    for field in fields:
        if field.get("semantic_type") == "date" and field.get("invalid_count"):
            add(
                f"invalid-date-{_slug(str(field.get('name')))}", "warning", "日期字段不可用于可靠趋势",
                f"{field.get('name')} 有 {int(field.get('invalid_count')):,} 个不可识别值。",
                "统一日期格式并重新生成报告。",
            )
    for finding in report.findings:
        missing = set(finding.evidence_ids) - evidence_set
        if not finding.evidence_ids or missing:
            add(f"finding-evidence-{finding.id}", "error", "结论证据不完整", f"结论“{finding.headline}”没有有效证据引用。", "为事实结论绑定存在的 Evidence ID。")
        if not finding.business_impact:
            add(f"finding-impact-{finding.id}", "warning", "结论缺少业务意义", f"结论“{finding.headline}”没有说明为什么重要。")
    for action in report.actions:
        missing = set(action.evidence_ids) - evidence_set
        if not action.evidence_ids or missing:
            add(f"action-evidence-{action.id}", "error", "行动建议缺少依据", f"行动“{action.action}”没有有效证据引用。")
        if not action.validation_metric.strip():
            add(f"action-validation-{action.id}", "error", "行动建议不可验证", f"行动“{action.action}”缺少验证指标。")
    for chart in report.charts:
        missing = set(chart.evidence_ids) - evidence_set
        if not chart.evidence_ids or missing:
            add(f"chart-evidence-{chart.id}", "error", "图表证据不完整", f"图表“{chart.title}”没有有效证据引用。")
        if chart.chart_type != "kpi" and not chart.description.strip():
            add(f"chart-description-{chart.id}", "warning", "图表缺少解释", f"图表“{chart.title}”没有口径、发现或限制说明。")
        chart_quality = quality_report(chart, chart.data, fields)
        for item in chart_quality.issues:
            if item.severity in {"error", "warning"}:
                add(f"chart-{chart.id}-{item.id}", item.severity, item.title, f"{chart.title}：{item.detail}", item.suggestion)
            elif item.id == "trend-non-temporal-dimension":
                add(f"chart-{chart.id}-{item.id}", "error", item.title, f"{chart.title}：{item.detail}", item.suggestion)
    for block in report.blocks:
        if block.chart_id and block.chart_id not in chart_ids:
            add(f"missing-chart-{block.id}", "error", "报告引用了不存在的图表", f"对象 {block.id} 引用了 {block.chart_id}。")
        if re.search(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?", block.content) and block.kind in {"paragraph", "insight", "callout"} and not block.evidence_ids:
            add(f"ungrounded-number-{block.id}", "error", "正文数字没有证据", f"对象 {block.id} 包含数字但没有 Evidence ID。")
    for check in claim_checks:
        if check['status']=='unverified':
            add(f"claim-{check['target_kind']}-{check['target_id']}", "error", "结论待核验",
                f"{check['target_kind']} {check['target_id']}：{check['text'][:160]}", check['reason'])
    score = max(0, 100 - sum({"error": 25, "warning": 8, "info": 2}[item.severity] for item in issues))
    return ReportQualityReport(
        score=score, passed=not any(item.severity == "error" for item in issues) and score >= 70,
        issues=issues, claim_checks=claim_checks, checked_at=datetime.now(timezone.utc).isoformat(),
    )


def _finding_block(finding: ReportFinding) -> ReportBlock:
    parts = [finding.statement]
    if finding.business_impact: parts.append(f"业务意义：{finding.business_impact}")
    if finding.recommendation: parts.append(f"建议：{finding.recommendation}")
    if finding.caveats: parts.append("限制：" + " ".join(finding.caveats))
    return ReportBlock(id=f"block-{finding.id}", kind="insight", content="\n".join(parts), evidence_ids=finding.evidence_ids, style={"headline": finding.headline})


def _time_trend(
    frame: pd.DataFrame, date_column: str, measure: str, date_format: str | None = None,
) -> tuple[list[dict[str, Any]], str, float] | None:
    dates = pd.to_datetime(frame[date_column], errors="coerce", format=date_format or "mixed")
    values = pd.to_numeric(frame[measure], errors="coerce")
    valid = dates.notna() & values.notna()
    if valid.mean() < .8 or valid.sum() < 2:
        return None
    span_days = int((dates[valid].max() - dates[valid].min()).days)
    if span_days > 740:
        periods, label = dates[valid].dt.to_period("Y").astype(str), "年"
    elif span_days > 120:
        periods, label = dates[valid].dt.to_period("M").astype(str), "月"
    else:
        periods, label = dates[valid].dt.strftime("%Y-%m-%d"), "日"
    grouped = pd.DataFrame({"period": periods, measure: values[valid].to_numpy()}).groupby("period", as_index=False)[measure].sum().sort_values("period")
    data = dataframe_rows(grouped, limit=120)
    if len(data) < 2 or data[0][measure] <= 0:
        return None
    from .report_claims import growth_rate
    return data, label, growth_rate(float(data[-1][measure]), float(data[0][measure]))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "field-" + "".join(f"{ord(character):x}" for character in value)[:24]


def normalize_sql_columns(sql: str, columns) -> str:
    """Quote only known non-identifier columns in model-authored read-only SQL."""
    normalized = sql
    special = [str(column) for column in columns if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(column))]
    for column in sorted(special, key=len, reverse=True):
        pattern = rf"(?<![\"'`\[])\b{re.escape(column)}\b(?![\"'`\]])"
        normalized = re.sub(pattern, '"' + column.replace('"', '""') + '"', normalized, flags=re.I)
    return normalized


def validate_non_additive_sql(sql: str, semantics: dict | None) -> None:
    """Conservatively reject aggregates referencing duplicated fields, including
    CTE aliases and expressions. AVG is also unsafe with unequal detail counts.
    This is a grain guard, not a general SQL parser or arbitrary-code sandbox.
    """
    if not re.search(r"\b(SUM|AVG|MEAN|MEDIAN|COUNT|MIN|MAX|STDDEV\w*|VAR\w*|QUANTILE\w*|PERCENTILE\w*)\s*\(", sql, re.I):
        return
    wildcard = re.search(r"\bSELECT\s+(?:DISTINCT\s+)?(?:[\w\"`]+\.)?\*", sql, re.I)
    for column in (semantics or {}).get("non_additive_columns") or []:
        quoted = re.escape(str(column))
        if wildcard or re.search(rf"(?<!\w){quoted}(?!\w)", sql, re.I):
            raise ValueError(f"字段“{column}”来自 N:1 右表并在明细行重复，禁止直接 SUM/AVG 等聚合；请在右表原数据集按其原始粒度计算")


def run_sql_query(frame: pd.DataFrame, sql: str, max_rows: int = 200) -> tuple[list[str], list[dict[str, Any]], int, bool, int]:
    """Run read-only analytical SQL against an in-memory dataset copy."""
    statement = sql.strip().rstrip(";")
    forbidden = re.compile(r"\b(ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|CALL|PRAGMA|CREATE|DROP|ALTER|UPDATE|DELETE|INSERT)\b", re.I)
    if forbidden.search(statement) or not re.match(r"^(SELECT|WITH)\b", statement, re.I):
        raise ValueError("SQL 沙箱当前只允许 SELECT/WITH 查询，禁止文件、扩展和写入操作")
    started = time.perf_counter()
    connection = duckdb.connect(database=":memory:", config={"enable_external_access": "false"})
    try:
        connection.register("dataset", frame)
        result = connection.execute(f"SELECT * FROM ({statement}) AS result LIMIT {int(max_rows) + 1}").fetchdf()
    finally:
        connection.close()
    truncated = len(result) > max_rows
    if truncated:
        result = result.head(max_rows)
    rows = dataframe_rows(result, limit=max_rows)
    return [str(column) for column in result.columns], rows, len(rows), truncated, max(1, round((time.perf_counter() - started) * 1000))


def analysis_context(frame: pd.DataFrame, profile: dict, quality: DataQualitySummary, sample_limit: int = 12) -> str:
    safe_columns = [column for column in frame.columns if not re.search(r"(customer.?name|客户.?姓名|email|电话|phone|address|地址)", str(column), re.I)]
    samples = dataframe_rows(frame[safe_columns], limit=sample_limit)
    compact_profile = [{key: item.get(key) for key in ("name", "dtype", "semantic_type", "null_count", "unique_count", "min", "max", "mean", "constant", "invalid_count")} for item in profile.get("columns", [])]
    return (
        f"读取模式：全量，未截断。数据规模：{len(frame)} 行 × {len(frame.columns)} 列。\n"
        f"字段画像：{compact_profile}\n质量问题：{[issue.model_dump() for issue in quality.issues[:20]]}\n"
        f"脱敏样本（仅用于理解字段，不用于计算）：{samples}"
    )


def _find_column(frame: pd.DataFrame, aliases: list[str]) -> str | None:
    normalized = {re.sub(r"[\s_\-]+", "", str(column)).casefold(): str(column) for column in frame.columns}
    for alias in aliases:
        key = re.sub(r"[\s_\-]+", "", alias).casefold()
        if key in normalized:
            return normalized[key]
    return None


def _grouped_records(frame: pd.DataFrame, dimension: str, measures: list[str], limit: int) -> list[dict[str, Any]]:
    work = frame[[dimension, *measures]].copy()
    for measure in measures:
        work[measure] = pd.to_numeric(work[measure], errors="coerce")
    grouped = work.groupby(dimension, dropna=False)[measures].sum().sort_values(measures[0], ascending=False).head(limit).reset_index()
    return [{str(column): _json_cell(value) for column, value in row.items()} for row in grouped.to_dict(orient="records")]


def _semantic_type(name: str, series: pd.Series) -> str:
    lowered = name.casefold()
    if re.search(r"(^|[\s_\-])(date|time|year|month)([\s_\-]|$)|日期|时间|年月|年度", lowered):
        return "date"
    if re.search(r"latitude|longitude|经度|纬度|country|state|city|region|国家|省|市|地区|区域", lowered):
        return "geography"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "measure"
    return "dimension"


def new_storage_key(workspace_id: str, suffix: str) -> str:
    return f"workspaces/{workspace_id}/datasets/{uuid4().hex}{suffix.lower()}"


def _json_number(value):
    if value is None or pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return float(value)


def _json_value(value):
    if value is None or pd.isna(value):
        return "(空值)"
    return str(value)


def _json_cell(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _format_number(value: float) -> str:
    return f"{value:,.2f}" if math.isfinite(value) else "—"
