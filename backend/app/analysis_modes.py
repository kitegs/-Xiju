from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AnalysisMode:
    id: str
    name: str
    description: str
    intent: str
    recommended_tools: tuple[str, ...]


ANALYSIS_MODES: dict[str, AnalysisMode] = {
    "auto": AnalysisMode("auto", "智能自动", "根据问题和字段自动选择分析方法", "auto", ()),
    "explore": AnalysisMode("explore", "快速探索", "快速识别结构、质量、趋势和异常", "general exploration", ("dataset.profile", "data.quality")),
    "deep": AnalysisMode("deep", "深度分析", "增加描述统计和证据化报告", "deep evidence-based analysis", ("dataset.profile", "data.quality", "statistics.describe", "report.build")),
    "cleaning": AnalysisMode("cleaning", "数据清洗", "诊断数据质量并给出可执行清洗建议", "data cleaning", ("dataset.profile", "data.quality", "cleaning.recommend")),
    "business": AnalysisMode("business", "商务报告", "围绕指标、结构、趋势和行动生成报告", "business intelligence", ("dataset.profile", "data.quality", "report.build")),
    "research": AnalysisMode("research", "科研统计", "提供描述统计、显著性检验、效应量和研究限制", "research statistics", ("dataset.profile", "data.quality", "statistics.describe", "research.inferential")),
    "survey": AnalysisMode("survey", "问卷分析", "识别量表题、信度和分组差异/交叉分析", "survey analysis", ("dataset.profile", "data.quality", "survey.profile", "survey.cross_analysis")),
    "professional": AnalysisMode("professional", "专业看板", "生成报告并发布到 Superset 继续精修", "professional dashboard", ("dataset.profile", "data.quality", "report.build", "superset.publish")),
}


def mode_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": mode.id,
            "name": mode.name,
            "description": mode.description,
            "recommended_tools": list(mode.recommended_tools),
        }
        for mode in ANALYSIS_MODES.values()
    ]


def resolve_mode(requested: str, message: str, profile: dict | None = None) -> tuple[str, str]:
    if requested in ANALYSIS_MODES and requested != "auto":
        return requested, "用户手动选择"
    text = message.casefold()
    rules = (
        ("professional", ("superset", "专业看板", "dashboard", "仪表盘")),
        ("survey", ("问卷", "量表", "likert", "信度", "cronbach")),
        ("research", ("科研", "实验", "显著性", "置信区间", "论文", "假设检验", "anova", "t检验")),
        ("cleaning", ("清洗", "缺失值", "重复值", "异常值", "格式修正")),
        ("business", ("管理层", "经营", "销售", "利润", "商务", "业绩", "报告")),
        ("deep", ("深度", "全面分析", "深入", "原因分析")),
    )
    for mode_id, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return mode_id, f"智能识别到“{next(keyword for keyword in keywords if keyword in text)}”场景"
    semantic_types = {item.get("semantic_type") for item in (profile or {}).get("columns", [])}
    if "measure" in semantic_types and "dimension" in semantic_types:
        return "explore", "检测到维度与度量字段，采用通用探索"
    return "explore", "未发现明确场景关键词，采用安全的快速探索"


def describe_statistics(frame: pd.DataFrame, max_columns: int = 12) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    numeric_columns = [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])][:max_columns]
    for column in numeric_columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if values.empty:
            continue
        mean = float(values.mean())
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        margin = 1.96 * std / (len(values) ** 0.5) if len(values) > 1 else 0.0
        evidence.append({
            "id": f"describe-{len(evidence) + 1}",
            "statement": f"{column} 的描述统计",
            "method": "有效样本、均值、中位数、样本标准差与正态近似 95% 均值置信区间",
            "value": f"n={len(values):,}; mean={mean:.6g}; median={float(values.median()):.6g}; sd={std:.6g}; 95% CI=[{mean - margin:.6g}, {mean + margin:.6g}]",
            "source_columns": [str(column)],
            "data": [],
            "code": f'frame["{column}"].describe()',
        })
    return evidence


def survey_statistics(frame: pd.DataFrame, max_columns: int = 30) -> list[dict[str, Any]]:
    candidates: list[str] = []
    for column in frame.columns[:max_columns]:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        unique = set(float(value) for value in values.unique())
        if len(values) >= 3 and 2 <= len(unique) <= 7 and unique <= set(range(0, 11)):
            candidates.append(str(column))
    evidence: list[dict[str, Any]] = [{
        "id": "survey-scale-candidates",
        "statement": "候选量表字段",
        "method": "识别取值为 0–10 且离散水平不超过 7 个的数值字段",
        "value": "、".join(candidates) if candidates else "未自动识别到量表字段",
        "source_columns": candidates,
        "data": [],
        "code": "deterministic scale-field detection",
    }]
    if len(candidates) >= 2:
        items = frame[candidates].apply(pd.to_numeric, errors="coerce").dropna()
        item_count = len(candidates)
        item_variances = items.var(ddof=1).sum()
        total_variance = items.sum(axis=1).var(ddof=1)
        alpha = item_count / (item_count - 1) * (1 - item_variances / total_variance) if total_variance else float("nan")
        evidence.append({
            "id": "survey-cronbach-alpha",
            "statement": "候选量表内部一致性",
            "method": "Cronbach α；仅对完整作答记录计算，正式解释前需确认题项方向和同一构念",
            "value": f"alpha={alpha:.4f}; complete n={len(items):,}; items={item_count}" if pd.notna(alpha) else "无法计算",
            "source_columns": candidates,
            "data": [],
            "code": "alpha = k/(k-1) * (1 - sum(item_variances)/variance(total_score))",
        })
    return evidence


def cleaning_recommendations(frame: pd.DataFrame, quality: Any) -> list[dict[str, Any]]:
    recommendations: list[str] = []
    if quality.duplicate_rows:
        recommendations.append(f"先复制数据集，再删除 {quality.duplicate_rows:,} 行完全重复记录")
    for issue in quality.issues:
        if issue.issue_type == "missing" and issue.columns:
            recommendations.append(f"检查“{issue.columns[0]}”缺失原因，再选择删除、固定值或统计量填充")
        elif issue.issue_type == "invalid_date" and issue.columns:
            recommendations.append(f"把“{issue.columns[0]}”转换为日期并复核无法解析的原始值")
    if not recommendations:
        recommendations.append("未发现必须自动处理的问题；建议保留原始版本并检查业务口径、单位和异常极值")
    return [{
        "id": "cleaning-recommendations",
        "statement": "推荐清洗顺序",
        "method": "基于全表质量扫描生成建议；不会直接改写原文件",
        "value": "；".join(recommendations[:8]),
        "source_columns": [str(column) for column in frame.columns],
        "data": [],
        "code": "quality rules v1",
    }]
