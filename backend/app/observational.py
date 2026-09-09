"""Fixed descriptive exposure comparisons, only for explicitly declared hourly grain."""
import math
import pandas as pd
from .schemas import Evidence, ReportBlock, ReportFinding, ReportActionItem, ChartSpec


def hourly_comparison(frame, dimension, measure, date_column, hour_column):
    dates = pd.to_datetime(frame[date_column], errors="coerce", format="mixed")
    hours = pd.to_numeric(frame[hour_column], errors="coerce")
    values = pd.to_numeric(frame[measure], errors="coerce")
    if dates.isna().any() or hours.isna().any() or not ((hours >= 0) & (hours <= 23) & (hours % 1 == 0)).all():
        raise ValueError("小时粒度要求有效日期与整数小时")
    if values.isna().any() or not values.map(math.isfinite).all():
        raise ValueError("小时指标必须全部为有限数值，缺失值不可作为零")
    work = pd.DataFrame({"group": frame[dimension].astype("string").fillna("（空）"),
                         "date": dates.dt.normalize(), "hour": hours, "value": values})
    if work.duplicated(["date", "hour"]).any():
        raise ValueError("存在重复日期小时槽，无法当作单一小时粒度")
    grouped = work.groupby("group", dropna=False).agg(
        total=("value", "sum"), observed_hours=("value", "count"), observed_days=("date", "nunique"))
    grouped["mean_per_observed_hour"] = grouped["total"] / grouped["observed_hours"]
    grouped["mean_per_observed_day"] = grouped["total"] / grouped["observed_days"]
    grouped = grouped.reset_index().rename(columns={"group": dimension}).sort_values(
        ["mean_per_observed_hour", dimension], ascending=[False, True], kind="stable")
    return grouped.to_dict("records")


def attach_hourly_comparisons(document, frame, semantics):
    grain = str(semantics.get("grain", "")).casefold()
    if not any(term in grain for term in ("per hour", "每小时", "一小时")) or not {"dteday", "hr", "cnt"}.issubset(frame.columns):
        return
    excluded = set(semantics.get("non_additive_columns") or [])
    if "cnt" in excluded:
        return
    labels = semantics.get("column_labels") or {}
    value_labels = semantics.get("value_labels") or {}
    dimensions = [d for d in ("workingday", "hr", "season", "weathersit") if d in frame and frame[d].nunique() > 1]
    if not dimensions:
        return
    document.blocks.append(ReportBlock(id="observed-title", kind="heading", content="按观测时间比较需求"))
    try:
        comparisons = {dimension: hourly_comparison(frame, dimension, "cnt", "dteday", "hr") for dimension in dimensions}
    except ValueError as exc:
        document.blocks.append(ReportBlock(id="observed-limit", kind="paragraph", content=f"无法计算可比的小时需求：{exc}。请先核实记录粒度和缺失情况。"))
        return
    for dimension, rows in comparisons.items():
        field_label = labels.get(dimension, dimension)
        mapping = value_labels.get(dimension) or {}
        for row in rows:
            row[dimension] = mapping.get(str(row[dimension]), str(row[dimension]))
            row["value"] = row["mean_per_observed_hour"]
        top = rows[0]
        total_top = max(rows, key=lambda r: r["total"])
        key = f"observed-{dimension}"
        interpretation = (
            f"累计量最高的组为“{total_top[dimension]}”，平均观测小时需求最高的组为“{top[dimension]}”；"
            "两种排序回答不同问题。观察到的差异可能与时段构成、季节或人群有关，原因尚待验证。"
        )
        limitation = "分母仅包含实际观测小时，缺失小时未补零。每观测日均量仅统计该类出现的记录，不代表完整日需求；小样本组不宜直接用于调度决策。"
        evidence = Evidence(id=key, statement=f"{field_label}的可比小时需求", method="按类别汇总骑行量并除以实际观测小时数；另列观测日均量",
            value=f"“{top[dimension]}”平均每观测小时 {top['value']:.2f} 次，基于 {top['observed_hours']} 个观测小时、{top['observed_days']} 个观测日；累计 {top['total']:,.0f} 次。",
            source_columns=[dimension, "cnt", "dteday", "hr"], data=rows,
            code=f'from app.observational import hourly_comparison\nresult = hourly_comparison(frame, {dimension!r}, "cnt", "dteday", "hr")',
            calculation={"operation": "rank", "operands": [r["value"] for r in rows], "candidate": top["value"], "result": 1, "unit": "rank",
                "metric": "value", "dimension": dimension, "member": top[dimension],
                "facts": [{"role": "mean_per_observed_hour", "value": top["value"], "unit": "次/观测小时"},
                          {"role": "observed_hours", "value": top["observed_hours"], "unit": "count"},
                          {"role": "observed_days", "value": top["observed_days"], "unit": "count"},
                          {"role": "total", "value": top["total"], "unit": "count"}]})
        document.evidence.append(evidence)
        finding = ReportFinding(id=f"finding-{key}", headline=evidence.statement, statement=evidence.value,
            business_impact=interpretation, recommendation="按同季节、同星期和同小时分层复核，核对样本量与需求波动后，再做小范围调度试验。",
            caveats=[limitation], evidence_ids=[key])
        document.findings.append(finding)
        document.blocks.append(ReportBlock(id=f"block-{key}", kind="insight", evidence_ids=[key], style={"headline": finding.headline},
            content=f"事实：{finding.statement}\n解释（待验证）：{interpretation}\n行动：{finding.recommendation}\n限制：{limitation}"))
        if dimension == "workingday":
            chart = ChartSpec(id="observed-workday-mean", title="日期类型的平均观测小时需求", chart_type="bar",
                x={"column": dimension}, y={"column": "value", "aggregate": None}, series=[{"column": "value", "aggregate": None}],
                data=rows, description="累计骑行次数除以该组实际观测小时数，未对缺失小时补零。未控制时段、季节等因素，不是因果效应。",
                evidence_ids=[key], style={"unit": "次/观测小时", "source_label": "完整小时副本，按实际观测时间归一化", "height": 300})
            document.charts.append(chart)
            document.blocks.append(ReportBlock(id="observed-workday-chart", kind="chart", chart_id=chart.id, evidence_ids=[key]))
    document.actions.append(ReportActionItem(id="action-observed-validation", action="复核高需求组的观测覆盖并设计小范围调度试验。",
        rationale="累计规模与观测小时均量可能排序不同，需先排除时间构成差异。", priority="medium",
        expected_impact="减少因样本覆盖不均导致的资源误配；不承诺未经验证的改善幅度。",
        validation_metric="同季节、同星期、同时段的每观测小时需求与缺车记录，试验前后对照。",
        evidence_ids=[f"observed-{d}" for d in dimensions]))
