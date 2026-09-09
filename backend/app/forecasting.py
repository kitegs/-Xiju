from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastResult:
    date_column: str
    target_column: str
    frequency: str
    aggregate: str
    method: str
    horizon: int
    metrics: dict[str, float | None]
    history: list[dict[str, Any]]
    forecast: list[dict[str, Any]]
    candidate_metrics: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    warnings: list[str]
    code: str


FREQUENCIES = {"D": "日", "W": "周", "MS": "月", "QS": "季度"}


def forecast_time_series(
    frame: pd.DataFrame,
    *,
    date_column: str | None = None,
    target_column: str | None = None,
    horizon: int = 6,
    frequency: str = "MS",
    aggregate: str = "sum",
) -> ForecastResult:
    """Deterministic baseline forecasting with holdout model selection.

    This intentionally avoids generated code and heavyweight AutoML. It provides
    reproducible baselines, a backtest, and uncertainty bounds. The result is an
    analytical aid, not an autonomous business decision.
    """
    if frequency not in FREQUENCIES:
        raise ValueError("预测频率只支持 D、W、MS、QS")
    if aggregate not in {"sum", "mean"}:
        raise ValueError("预测聚合只支持 sum 或 mean")
    horizon = max(1, min(int(horizon), 36))
    date_column = date_column or _detect_date_column(frame)
    target_column = target_column or _detect_target_column(frame)
    if not date_column or date_column not in frame.columns:
        raise ValueError("没有找到可用于预测的日期字段，请在工具栏选择日期字段")
    if not target_column or target_column not in frame.columns:
        raise ValueError("没有找到可用于预测的数值指标，请在工具栏选择指标")

    work = pd.DataFrame({
        "date": pd.to_datetime(frame[date_column], errors="coerce"),
        "value": pd.to_numeric(frame[target_column], errors="coerce"),
    }).dropna()
    if work.empty:
        raise ValueError("日期或指标转换后没有有效记录")
    grouped = getattr(work.set_index("date")["value"].sort_index().resample(frequency), aggregate)().dropna()
    if len(grouped) < 8:
        raise ValueError(f"聚合后只有 {len(grouped)} 个周期；正式预测至少需要 8 个周期")

    values = grouped.to_numpy(dtype=float)
    holdout = min(max(2, min(horizon, 6)), max(2, len(values) // 4))
    train = values[:-holdout]
    actual = values[-holdout:]
    if len(train) < 5:
        raise ValueError("可用于回测的历史周期不足")

    season = _season_length(frequency)
    scored = _rolling_backtest(values, horizon, season)
    scored.sort(key=lambda item: (math.inf if item["mae"] is None else item["mae"], item["method"]))
    selected = scored[0]["method"]

    future_values = _predict(selected, values, horizon, season)
    fitted = _predict(selected, train, holdout, season)
    residuals = actual - fitted
    residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    z = 1.96
    bounds = [z * residual_std * math.sqrt(1 + (step + 1) / max(len(values), 1)) for step in range(horizon)]
    future_index = pd.date_range(start=grouped.index[-1], periods=horizon + 1, freq=frequency)[1:]
    forecast_rows = [
        {
            "date": date.isoformat(), "forecast": _number(value),
            "lower": _number(value - bounds[index]), "upper": _number(value + bounds[index]),
        }
        for index, (date, value) in enumerate(zip(future_index, future_values))
    ]
    history_rows = [
        {"date": date.isoformat(), "actual": _number(value)}
        for date, value in grouped.tail(120).items()
    ]
    warnings = ["预测区间基于留出集残差的正态近似；极端事件和结构变化可能不在区间内。"]
    if len(grouped) < 2 * max(season or 1, 6):
        warnings.append("历史周期较短，季节性和长期趋势结论需谨慎。")
    if float(grouped.isna().mean()) > 0:
        warnings.append("时间聚合后存在缺失周期。")
    diagnostics = _diagnostics(grouped, residuals, season, len(scored[0].get("fold_metrics", [])))
    if diagnostics["anomaly_count"]:
        warnings.append(f"检测到 {diagnostics['anomaly_count']} 个历史异常周期；预测会保留它们，但建议结合业务事件复核。")
    if selected != "seasonal_naive" and season:
        warnings.append("季节性基线未在滚动回测中胜出；不要把季节模式视为已验证结论。")
    code = _reproducible_code(date_column, target_column, frequency, aggregate, horizon, selected)
    return ForecastResult(
        date_column=date_column, target_column=target_column, frequency=frequency,
        aggregate=aggregate, method=selected, horizon=horizon,
        metrics={key: scored[0][key] for key in ("mae", "rmse", "mape")},
        history=history_rows, forecast=forecast_rows, candidate_metrics=scored, diagnostics=diagnostics,
        warnings=warnings, code=code,
    )


def recommendation_actions(
    frame: pd.DataFrame,
    quality: Any,
    forecast: ForecastResult | None = None,
) -> list[dict[str, Any]]:
    """Create conservative, evidence-ready actions instead of free-form advice."""
    actions: list[dict[str, Any]] = []
    if getattr(quality, "duplicate_rows", 0):
        actions.append({
            "id": "action-deduplicate", "finding": f"检测到 {quality.duplicate_rows:,} 行完全重复记录",
            "recommendation": "在数据副本中预览去重影响，确认业务主键后再生成清洗版本",
            "priority": "high", "confidence": "high", "risk": "错误主键可能误删合法重复业务记录",
            "validation": "比较去重前后行数、关键指标总额和抽样明细", "evidence_ids": ["quality-summary"],
        })
    if getattr(quality, "missing_cells", 0):
        actions.append({
            "id": "action-missing", "finding": f"检测到 {quality.missing_cells:,} 个缺失单元格",
            "recommendation": "先按字段和业务原因分类缺失，再选择删除、业务常量或统计量填充",
            "priority": "high", "confidence": "high", "risk": "直接均值填充可能压低方差并扭曲关系",
            "validation": "对比处理前后分布、均值、标准差和样本量", "evidence_ids": ["quality-summary"],
        })
    if forecast and forecast.forecast:
        first = forecast.forecast[0]["forecast"]
        last = forecast.forecast[-1]["forecast"]
        direction = "上升" if last > first else "下降" if last < first else "基本持平"
        delta = (last - first) / abs(first) if first else None
        actions.append({
            "id": "action-forecast", "finding": f"{forecast.target_column} 基线预测呈{direction}趋势" + (f"，首末期变化约 {delta:.1%}" if delta is not None else ""),
            "recommendation": "将预测作为容量和目标设定的基线，同时准备预测区间上下界两种情景",
            "priority": "medium", "confidence": "medium", "risk": "预测不是因果结论，促销、政策和结构突变会使结果失效",
            "validation": f"每个{FREQUENCIES[forecast.frequency]}度用实际值回填并监控 MAE/MAPE",
            "evidence_ids": ["timeseries-forecast"],
        })
    if not actions:
        numeric = [str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
        actions.append({
            "id": "action-review", "finding": "未发现需要立即自动处理的高置信度问题",
            "recommendation": "确认指标口径、业务目标和决策约束后，再运行分组、趋势或对比分析",
            "priority": "low", "confidence": "medium", "risk": "缺少业务上下文时建议可能过于宽泛",
            "validation": "由数据负责人确认字段定义和目标指标", "evidence_ids": ["dataset-shape"],
            "candidate_columns": numeric[:8],
        })
    return actions[:8]


def _detect_date_column(frame: pd.DataFrame) -> str | None:
    preferred = [column for column in frame.columns if any(token in str(column).casefold() for token in ("date", "time", "日期", "时间"))]
    for column in [*preferred, *[item for item in frame.columns if item not in preferred]]:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            return str(column)
        parsed = pd.to_datetime(frame[column].dropna().head(200), errors="coerce")
        if len(parsed) >= 3 and parsed.notna().mean() >= 0.8:
            return str(column)
    return None


def _detect_target_column(frame: pd.DataFrame) -> str | None:
    aliases = ("sales", "revenue", "amount", "profit", "销售", "营收", "收入", "利润")
    numeric = [str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
    return next((column for column in numeric if any(alias in column.casefold() for alias in aliases)), numeric[0] if numeric else None)


def _season_length(frequency: str) -> int | None:
    return {"D": 7, "W": 52, "MS": 12, "QS": 4}.get(frequency)


def _predict(name: str, values: np.ndarray, horizon: int, season: int | None) -> np.ndarray:
    if name == "naive":
        return _predict_naive(values, horizon)
    if name == "moving_average":
        return _predict_moving_average(values, horizon)
    if name == "linear_trend":
        return _predict_linear(values, horizon)
    return _predict_seasonal(values, horizon, season or 1)


def _predict_naive(values: np.ndarray, horizon: int) -> np.ndarray:
    return np.repeat(values[-1], horizon).astype(float)


def _predict_moving_average(values: np.ndarray, horizon: int) -> np.ndarray:
    window = min(3, len(values))
    return np.repeat(float(np.mean(values[-window:])), horizon)


def _predict_linear(values: np.ndarray, horizon: int) -> np.ndarray:
    window = min(24, len(values))
    x = np.arange(window, dtype=float)
    slope, intercept = np.polyfit(x, values[-window:], 1)
    return intercept + slope * np.arange(window, window + horizon, dtype=float)


def _predict_seasonal(values: np.ndarray, horizon: int, season: int) -> np.ndarray:
    pattern = values[-min(season, len(values)):]
    return np.resize(pattern, horizon).astype(float)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    errors = actual - predicted
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    non_zero = actual != 0
    mape = float(np.mean(np.abs(errors[non_zero] / actual[non_zero])) * 100) if np.any(non_zero) else None
    return {"mae": _number(mae), "rmse": _number(rmse), "mape": _number(mape) if mape is not None else None}


def _rolling_backtest(values: np.ndarray, horizon: int, season: int | None) -> list[dict[str, Any]]:
    """Evaluate each baseline at several historical cutoffs, not one lucky split."""
    names = ["naive", "moving_average", "linear_trend"]
    if season and len(values) >= season * 2:
        names.append("seasonal_naive")
    test_size = min(max(1, min(horizon, 6)), max(1, len(values) // 5))
    # Non-seasonal baselines remain useful on short histories. Seasonal naive
    # is individually skipped until a full season is available.
    minimum_train = 5
    possible = max(1, (len(values) - minimum_train) // test_size)
    folds = min(3, possible)
    first_end = max(minimum_train, len(values) - folds * test_size)
    by_method: dict[str, list[dict[str, float | None]]] = {name: [] for name in names}
    for fold in range(folds):
        end = first_end + fold * test_size
        train = values[:end]
        actual = values[end:min(end + test_size, len(values))]
        if not len(actual):
            continue
        for name in names:
            if name == "seasonal_naive" and (not season or len(train) < season):
                continue
            by_method[name].append(_metrics(actual, _predict(name, train, len(actual), season)))
    scores: list[dict[str, Any]] = []
    for name, folds_for_method in by_method.items():
        if not folds_for_method:
            continue
        scores.append({
            "method": name,
            "mae": _mean_metric(folds_for_method, "mae"),
            "rmse": _mean_metric(folds_for_method, "rmse"),
            "mape": _mean_metric(folds_for_method, "mape"),
            "backtest_folds": len(folds_for_method),
            "fold_metrics": folds_for_method,
        })
    return scores


def _mean_metric(rows: list[dict[str, float | None]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return _number(float(np.mean(values))) if values else None


def _diagnostics(series: pd.Series, residuals: np.ndarray, season: int | None, folds: int) -> dict[str, Any]:
    values = series.to_numpy(dtype=float)
    center = float(np.median(values)); mad = float(np.median(np.abs(values - center)))
    scale = 1.4826 * mad
    anomalies = []
    if scale > 0:
        for date, value in series.items():
            robust_z = (float(value) - center) / scale
            if abs(robust_z) >= 3.5:
                anomalies.append({"date": date.isoformat(), "actual": _number(float(value)), "robust_z": _number(robust_z)})
    slope = float(np.polyfit(np.arange(min(24, len(values))), values[-min(24, len(values)):], 1)[0]) if len(values) >= 2 else 0.0
    return {
        "observation_count": len(values), "backtest_folds": folds, "seasonal_period": season,
        "trend_per_period": _number(slope), "anomaly_count": len(anomalies), "anomalies": anomalies[:20],
        "residual_standard_deviation": _number(float(np.std(residuals, ddof=1))) if len(residuals) > 1 else 0.0,
    }


def _number(value: float) -> float:
    return round(float(value), 6)


def _reproducible_code(date_column: str, target_column: str, frequency: str, aggregate: str, horizon: int, method: str) -> str:
    return (
        "# Insight Studio deterministic forecast v1\n"
        f"series = (df.assign(_date=pd.to_datetime(df[{date_column!r}], errors='coerce'), "
        f"_value=pd.to_numeric(df[{target_column!r}], errors='coerce'))\n"
        f"  .dropna(subset=['_date', '_value']).set_index('_date')['_value'].resample({frequency!r}).{aggregate}().dropna())\n"
        f"# selected by holdout MAE: {method}; horizon={horizon}\n"
        "# Candidate baselines: naive, moving_average, linear_trend, seasonal_naive (when enough history)."
    )
