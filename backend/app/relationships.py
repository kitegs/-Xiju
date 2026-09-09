from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

import pandas as pd


class RelationshipValidationError(ValueError):
    """Raised when a proposed relationship can duplicate facts or cannot be joined safely."""


def inherit_relationship_restrictions(profile: dict, left_semantics: dict | None, right_semantics: dict | None) -> None:
    """A second join must not erase the grain restrictions from the first join."""
    inherited = list((left_semantics or {}).get("non_additive_columns") or [])
    names = profile["right_column_names"]
    inherited.extend(names[column] for column in (right_semantics or {}).get("non_additive_columns") or [] if column in names)
    profile["non_additive_columns"] = list(dict.fromkeys([*profile["non_additive_columns"], *inherited]))
    if inherited:
        profile["warnings"].append("已继承来源关联副本的不可累计字段限制，继续关联不会解除原有粒度约束")


def cleaning_semantics(semantics: dict | None, steps: list, columns: list[str]) -> dict:
    result = deepcopy(semantics or {})
    for step in steps:
        if step.operation != "rename_column" or not step.column or not step.new_name:
            continue
        old, new = step.column, step.new_name.strip()
        for key in ("column_roles", "column_units", "column_labels", "value_labels", "date_formats", "field_lineage"):
            mapping = result.get(key) or {}
            if old in mapping:
                mapping[new] = mapping.pop(old)
        for key in ("non_additive_columns", "left_keys"):
            if key in result:
                result[key] = [new if name == old else name for name in result[key]]
    for key in ("column_roles", "column_units", "column_labels", "value_labels", "date_formats", "field_lineage"):
        if key in result:
            result[key] = {name: value for name, value in result[key].items() if name in columns}
    for key in ("non_additive_columns", "left_keys"):
        if key in result:
            result[key] = [name for name in result[key] if name in columns]
    return result


def _validate_keys(frame: pd.DataFrame, keys: list[str], side: str) -> None:
    if not keys:
        raise RelationshipValidationError(f"{side}未选择关联键")
    if len(keys) > 4:
        raise RelationshipValidationError("关联键最多支持 4 个字段")
    if len(set(keys)) != len(keys) or not frame.columns.is_unique:
        raise RelationshipValidationError(f"{side}关联键或字段名称重复")
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise RelationshipValidationError(f"{side}关联键不存在：{'、'.join(missing)}")


def _prefix(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", value.strip()).strip("_")
    return normalized[:40] or "right"


def _normalized_value(value: Any) -> str | None:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _key_series(frame: pd.DataFrame, keys: list[str]) -> pd.Series:
    values = []
    for row in frame[keys].itertuples(index=False, name=None):
        normalized = tuple(_normalized_value(value) for value in row)
        values.append(None if any(value is None or value == "" for value in normalized) else normalized)
    return pd.Series(values, index=frame.index, dtype="object")


def _right_output_names(left: pd.DataFrame, right: pd.DataFrame, right_keys: list[str], prefix: str) -> dict[str, str]:
    used = {str(column) for column in left.columns}
    output: dict[str, str] = {}
    for column in (str(item) for item in right.columns if str(item) not in right_keys):
        candidate = f"{prefix}__{column}"
        suffix = 2
        while candidate in used:
            candidate = f"{prefix}__{column}_{suffix}"
            suffix += 1
        output[column] = candidate
        used.add(candidate)
    return output


def profile_relationship(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
    join_type: str = "left",
    right_prefix: str = "right",
) -> dict[str, Any]:
    if join_type not in {"left", "inner"}:
        raise RelationshipValidationError("第一版仅支持左连接和内连接")
    if len(left_keys) != len(right_keys):
        raise RelationshipValidationError("左右关联键数量必须一致")
    _validate_keys(left, left_keys, "左表")
    _validate_keys(right, right_keys, "右表")

    left_tokens = _key_series(left, left_keys)
    right_tokens = _key_series(right, right_keys)
    left_valid = left_tokens.dropna()
    right_valid = right_tokens.dropna()
    left_duplicate_rows = int(left_valid.duplicated(keep=False).sum())
    right_duplicate_rows = int(right_valid.duplicated(keep=False).sum())
    left_unique = left_duplicate_rows == 0
    right_unique = right_duplicate_rows == 0

    if not left_unique and not right_unique:
        raise RelationshipValidationError("关联键在左右表都重复，会形成多对多连接并重复累计指标；请先聚合或去重")
    if left_unique and not right_unique:
        raise RelationshipValidationError("当前方向是 1:N；请交换左右表，让明细表位于左侧、唯一键表位于右侧")
    cardinality = "one_to_one" if left_unique else "many_to_one"

    left_set = set(left_valid.tolist())
    right_set = set(right_valid.tolist())
    matched_keys = left_set & right_set
    matched_left_rows = int(left_valid.isin(matched_keys).sum())
    matched_right_rows = int(right_valid.isin(matched_keys).sum())
    output_rows = matched_left_rows if join_type == "inner" else len(left)
    prefix = _prefix(right_prefix)
    renames = _right_output_names(left, right, right_keys, prefix)
    non_additive = []
    if cardinality == "many_to_one":
        non_additive = [
            renames[str(column)] for column in right.columns
            if str(column) not in right_keys and pd.api.types.is_numeric_dtype(right[column])
        ]

    warnings = []
    if int(left_tokens.isna().sum()):
        warnings.append(f"左表有 {int(left_tokens.isna().sum()):,} 行关联键为空")
    if int(right_tokens.isna().sum()):
        warnings.append(f"右表有 {int(right_tokens.isna().sum()):,} 行关联键为空")
    if matched_left_rows < len(left):
        warnings.append(f"左表有 {len(left) - matched_left_rows:,} 行未匹配右表")
    if non_additive:
        warnings.append("右表数值会在明细行重复，已标记为不可求和：" + "、".join(non_additive))
    if not matched_left_rows:
        warnings.append("两个数据集没有匹配记录，不能生成关联副本")

    return {
        "safe": bool(matched_left_rows),
        "cardinality": cardinality,
        "join_type": join_type,
        "left_keys": list(left_keys),
        "right_keys": list(right_keys),
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_distinct_keys": int(left_valid.nunique()),
        "right_distinct_keys": int(right_valid.nunique()),
        "left_duplicate_key_rows": left_duplicate_rows,
        "right_duplicate_key_rows": right_duplicate_rows,
        "matched_key_count": int(len(matched_keys)),
        "matched_left_rows": matched_left_rows,
        "matched_right_rows": matched_right_rows,
        "unmatched_left_rows": int(len(left) - matched_left_rows),
        "unmatched_right_rows": int(len(right) - matched_right_rows),
        "match_rate": round(matched_left_rows / max(len(left), 1), 8),
        "output_rows": int(output_rows),
        "right_prefix": prefix,
        "right_column_names": renames,
        "non_additive_columns": non_additive,
        "warnings": warnings,
    }


def materialize_relationship(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
    join_type: str = "left",
    right_prefix: str = "right",
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]]]:
    profile = profile_relationship(left, right, left_keys, right_keys, join_type, right_prefix)
    if not profile["safe"]:
        raise RelationshipValidationError("关联预览未通过：没有匹配记录")

    left_work = left.copy(deep=True)
    right_work = right.copy(deep=True)
    # Use exactly the same composite-key normalization as the preview. Missing
    # keys never match; pandas' default null-to-null merge semantics are unsafe.
    temp_key = "__aibi_join_key"
    reserved = set(left.columns) | set(right.columns) | set(profile["right_column_names"].values())
    while temp_key in reserved:
        temp_key += "_"
    left_tokens = _key_series(left, left_keys)
    right_tokens = _key_series(right, right_keys)
    codes = {token: index for index, token in enumerate(dict.fromkeys(
        left_tokens.dropna().tolist() + right_tokens.dropna().tolist()
    ))}
    left_work[temp_key] = [codes[token] if token is not None else -(index + 1)
                           for index, token in enumerate(left_tokens)]
    right_work[temp_key] = [codes[token] if token is not None else -1 for token in right_tokens]
    right_work = right_work.loc[right_tokens.notna()].copy()
    temp_keys = [temp_key]
    right_work.rename(columns=profile["right_column_names"], inplace=True)
    right_payload = [*temp_keys, *profile["right_column_names"].values()]
    result = left_work.merge(
        right_work[right_payload], how=join_type, on=temp_keys,
        validate="one_to_one" if profile["cardinality"] == "one_to_one" else "many_to_one",
        sort=False,
    ).drop(columns=temp_keys)

    lineage: dict[str, dict[str, Any]] = {
        str(column): {"source_side": "left", "source_column": str(column), "additive": True}
        for column in left.columns
    }
    for source, output in profile["right_column_names"].items():
        lineage[output] = {
            "source_side": "right", "source_column": source,
            "additive": output not in profile["non_additive_columns"],
        }
    return result, profile, lineage
