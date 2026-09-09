from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


def inferential_statistics(frame: pd.DataFrame, max_results: int = 8, semantics: dict | None = None) -> list[dict[str, Any]]:
    """Conservative automatic inference for small research datasets.

    Results are exploratory unless the user has preregistered a design. Every
    returned record states its assumptions/limitations and carries executable
    pandas/SciPy method text for review.
    """
    from .capabilities import _catalog
    catalog = _catalog(frame, semantics)
    numeric = catalog["measures"]
    categorical = [column for column in catalog["dimensions"] if column not in catalog["dates"]]
    evidence: list[dict[str, Any]] = []
    if len(numeric) >= 2:
        x, y = numeric[:2]
        pair = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(pair) >= 4 and pair[x].nunique() > 1 and pair[y].nunique() > 1:
            pearson = stats.pearsonr(pair[x], pair[y])
            slope, intercept, r_value, p_value, stderr = stats.linregress(pair[x], pair[y])
            evidence.append(_evidence(
                "research-correlation", f"{x} 与 {y} 的相关与线性回归", "Pearson r + OLS 单变量回归；相关不代表因果",
                f"n={len(pair):,}; r={pearson.statistic:.4f}; p={pearson.pvalue:.4g}; slope={slope:.6g}; R²={r_value ** 2:.4f}",
                [x, y], f"stats.pearsonr(frame[{x!r}], frame[{y!r}]); stats.linregress(...)"
            ))
    if categorical and numeric:
        group, measure = categorical[0], numeric[0]
        work = frame[[group, measure]].copy(); work[measure] = pd.to_numeric(work[measure], errors="coerce"); work = work.dropna()
        groups = [(str(name), values.to_numpy(dtype=float)) for name, values in work.groupby(group)[measure] if len(values) >= 2]
        if len(groups) == 2:
            (name_a, a), (name_b, b) = groups
            test = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
            pooled = math.sqrt(((len(a) - 1) * np.var(a, ddof=1) + (len(b) - 1) * np.var(b, ddof=1)) / max(len(a) + len(b) - 2, 1))
            d = (float(np.mean(a)) - float(np.mean(b))) / pooled if pooled else math.nan
            evidence.append(_evidence(
                "research-t-test", f"{group} 两组在 {measure} 上的差异", "Welch 独立样本 t 检验；需检查独立性、异常值和研究设计",
                f"{name_a} n={len(a)}, mean={np.mean(a):.6g}; {name_b} n={len(b)}, mean={np.mean(b):.6g}; t={test.statistic:.4f}; p={test.pvalue:.4g}; Cohen d={d:.4f}",
                [group, measure], f"stats.ttest_ind(a, b, equal_var=False); cohen_d(a, b)"
            ))
        elif len(groups) >= 3:
            chosen = groups[:8]
            result = stats.f_oneway(*(values for _, values in chosen))
            all_values = np.concatenate([values for _, values in chosen])
            grand = float(np.mean(all_values))
            ss_between = sum(len(values) * (float(np.mean(values)) - grand) ** 2 for _, values in chosen)
            ss_total = float(np.sum((all_values - grand) ** 2))
            eta_squared = ss_between / ss_total if ss_total else math.nan
            evidence.append(_evidence(
                "research-anova", f"{group} 各组在 {measure} 上的差异", "单因素 ANOVA；显著后仍需进行多重比较校正的事后检验",
                f"groups={len(chosen)}; n={len(all_values):,}; F={result.statistic:.4f}; p={result.pvalue:.4g}; η²={eta_squared:.4f}",
                [group, measure], "stats.f_oneway(*groups); eta_squared = SS_between / SS_total"
            ))
            if result.pvalue < 0.05:
                comparisons: list[str] = []
                total_pairs = len(chosen) * (len(chosen) - 1) // 2
                for index, (left_name, left_values) in enumerate(chosen):
                    for right_name, right_values in chosen[index + 1:]:
                        pair = stats.ttest_ind(left_values, right_values, equal_var=False, nan_policy="omit")
                        adjusted = min(float(pair.pvalue) * total_pairs, 1.0)
                        comparisons.append(f"{left_name} vs {right_name}: p_Bonferroni={adjusted:.4g}")
                evidence.append(_evidence(
                    "research-anova-posthoc", f"{group} 在 {measure} 上的事后比较", "两两 Welch t 检验，Bonferroni 校正；仅在总体 ANOVA 显著后探索性报告",
                    "; ".join(comparisons[:12]), [group, measure],
                    "pairwise stats.ttest_ind(..., equal_var=False); p_adjusted = min(p * number_of_pairs, 1)"
                ))
    if len(categorical) >= 2:
        left, right = categorical[:2]
        table = pd.crosstab(frame[left], frame[right])
        if table.shape[0] >= 2 and table.shape[1] >= 2 and int(table.to_numpy().sum()) >= 10:
            chi2, p_value, dof, expected = stats.chi2_contingency(table)
            n = int(table.to_numpy().sum()); phi2 = chi2 / n
            denom = min(table.shape[1] - 1, table.shape[0] - 1)
            cramers_v = math.sqrt(phi2 / denom) if denom else math.nan
            low_expected = int((expected < 5).sum())
            evidence.append(_evidence(
                "research-chi-square", f"{left} 与 {right} 的关联", "Pearson 卡方独立性检验；小期望频数时应合并类别或改用精确检验",
                f"n={n:,}; χ²={chi2:.4f}; dof={dof}; p={p_value:.4g}; Cramér's V={cramers_v:.4f}; expected<5 cells={low_expected}",
                [left, right], f"pd.crosstab(frame[{left!r}], frame[{right!r}]); stats.chi2_contingency(table)"
            ))
    if numeric:
        suggested = _two_sample_size(effect_size=0.5)
        evidence.append(_evidence(
            "research-sample-size", "研究样本量提示", "双侧两独立样本均值比较的正态近似；用于规划，不替代正式功效分析",
            f"若目标标准化效应量 d=0.5、α=0.05、power=0.80，建议每组约 {suggested} 人；实际样本量取决于设计、失访和多重比较。",
            numeric[:1], "n_per_group ≈ 2 * (z_(1-α/2)+z_power)^2 / d^2"
        ))
    return evidence[:max_results]


def survey_cross_analysis(frame: pd.DataFrame, max_results: int = 6) -> list[dict[str, Any]]:
    result = []
    candidates = []
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(values) >= 8 and 2 <= values.nunique() <= 7 and values.min() >= 0 and values.max() <= 10:
            candidates.append(str(column))
    groups = [str(column) for column in frame.columns if str(column) not in candidates and frame[column].nunique(dropna=True) in range(2, 9)]
    if candidates and groups:
        item, group = candidates[0], groups[0]
        table = pd.crosstab(frame[group], frame[item])
        if table.shape[0] >= 2 and table.shape[1] >= 2:
            chi2, p_value, dof, expected = stats.chi2_contingency(table)
            n = int(table.to_numpy().sum()); denom = min(table.shape[0] - 1, table.shape[1] - 1)
            v = math.sqrt((chi2 / n) / denom) if n and denom else math.nan
            result.append(_evidence(
                "survey-cross-analysis", f"{group} 与量表题 {item} 的交叉分析", "卡方独立性检验与 Cramér's V；Likert 分数是有序数据，解释应结合题项设计",
                f"n={n:,}; χ²={chi2:.4f}; p={p_value:.4g}; Cramér's V={v:.4f}; expected<5 cells={int((expected < 5).sum())}",
                [group, item], "pd.crosstab(group, item); stats.chi2_contingency(table)"
            ))
    return result


def _two_sample_size(effect_size: float, alpha: float = 0.05, power: float = 0.80) -> int:
    return math.ceil(2 * (stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)) ** 2 / effect_size ** 2)


def _evidence(identifier: str, statement: str, method: str, value: str, columns: list[str], code: str) -> dict[str, Any]:
    return {"id": identifier, "statement": statement, "method": method, "value": value, "source_columns": columns, "data": [], "code": code}
