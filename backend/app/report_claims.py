"""Deterministic claim, calculation and chart provenance checks."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re

from .schemas import ClaimValue, ReportClaim


def growth_rate(current, baseline):
    if not math.isfinite(current) or not math.isfinite(baseline) or baseline <= 0:
        raise ValueError("增长率需要有限数值和正基期；零/负基期应另行解释")
    return (current - baseline) / baseline


def convert_unit(value, source, target):
    groups = ({"ratio": 1, "percent": .01}, {"元": 1, "万元": 10000, "亿元": 100000000})
    for factors in groups:
        if source in factors and target in factors:
            return value * factors[source] / factors[target]
    raise ValueError("单位不兼容；百分比与百分点不能直接互换")


def period_growth(current, baseline, current_period, baseline_period, kind):
    def period(value):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("同比/环比需要明确的 YYYY-MM 完整月度期间")
        year, month = map(int, value.split("-"))
        return year * 12 + month

    distance = period(current_period) - period(baseline_period)
    if kind not in {"yoy", "mom"} or distance != {"yoy": 12, "mom": 1}[kind]:
        raise ValueError("比较期间不匹配：同比相隔十二个月，环比相隔一个月")
    return growth_rate(current, baseline)


def descending_rank(values, value):
    if not values or not all(math.isfinite(v) for v in [*values, value]) or value not in values:
        raise ValueError("排名需要完整有效的数值及候选项")
    return 1 + sum(v > value for v in values)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def subjects(document):
    yield "summary", "summary", document.summary, [], "fact"
    for finding in document.findings:
        yield "finding", finding.id, finding.statement, finding.evidence_ids, "fact"
        if finding.business_impact:
            yield "interpretation", finding.id, finding.business_impact, finding.evidence_ids, "inference"
        if finding.recommendation:
            yield "recommendation", finding.id, finding.recommendation, finding.evidence_ids, "recommendation"
    for block in document.blocks:
        if block.kind in {"paragraph", "insight", "callout"} and block.content.strip():
            category = "assumption" if block.id == "unconfirmed-assumptions" and block.content.startswith("未经确认的业务假设：") else "fact"
            yield "block", block.id, block.content, block.evidence_ids, category


_NUMBER = re.compile(r"(?<![A-Za-z0-9])([+-]?\d[\d,]*(?:\.\d+)?)(%)?")


def _numbers(text: str) -> list[tuple[float, str]]:
    values = []
    for raw, percent in _NUMBER.findall(text or ""):
        try:
            values.append((round(float(raw.replace(",", "")), 10), "percent" if percent else "number"))
        except ValueError:
            pass
    return values


def _terms(text: str, evidence) -> list[str]:
    candidates = [evidence.statement, *evidence.source_columns]
    calculation = evidence.calculation or {}
    candidates.extend(str(calculation.get(key, "")) for key in ("metric", "dimension", "member", "current_period", "baseline_period"))
    folded = text.casefold()
    return list(dict.fromkeys(str(term) for term in candidates if term and str(term).casefold() in folded))


def _subject_claims(kind: str, key: str, text: str, refs: list[str], category: str, evidence_by_id: dict):
    selected = refs
    if kind == "summary":
        selected = [evidence_id for evidence_id, item in evidence_by_id.items() if item.statement.casefold() in text.casefold()]
    claims = []
    for evidence_id in selected:
        item = evidence_by_id.get(evidence_id)
        if not item or not item.calculation:
            continue
        calculation = item.calculation
        values = []
        for fact in calculation.get("facts", []):
            try:
                values.append(ClaimValue(role=str(fact.get("role", "value")), value=float(fact["value"]), unit=str(fact.get("unit", ""))))
            except (KeyError, TypeError, ValueError):
                continue
        claims.append(ReportClaim(
            id=f"claim-{kind}-{key}-{evidence_id}", target_kind="finding" if kind in {"interpretation", "recommendation"} else kind,
            target_id=key, claim_type=category, operation=str(calculation.get("operation", "")),
            metric=str(calculation.get("metric", item.statement)), dimension=str(calculation.get("dimension", "")),
            member=str(calculation.get("member", "")),
            periods=[str(value) for value in (calculation.get("baseline_period"), calculation.get("current_period")) if value],
            required_terms=_terms(text, item), values=values, evidence_ids=[evidence_id],
        ))
    return claims


def _chart_certificate(chart) -> dict:
    return {
        "data_hash": fingerprint(chart.data),
        "binding": fingerprint({"x": chart.x, "y": chart.y, "series": chart.series}),
        "evidence_ids": chart.evidence_ids,
        "unit": chart.style.unit,
        "title": chart.title,
        "description": chart.description,
    }


def seal_claims(document):
    """Only call immediately after deterministic generation, never on user edits."""
    evidence_by_id = {item.id: item for item in document.evidence}
    claims = []
    subject_rows = {}
    for kind, key, text, refs, category in subjects(document):
        generated = _subject_claims(kind, key, text, refs, category, evidence_by_id)
        claims.extend(generated)
        subject_rows[f"{kind}:{key}"] = {
            "text": text, "evidence_ids": refs, "type": category,
            "numbers": _numbers(text), "required_terms": list(dict.fromkeys(term for claim in generated for term in claim.required_terms)),
            "claim_ids": [claim.id for claim in generated],
        }
    document.claims = claims
    document.metadata["claim_baseline"] = {
        "version": "structured-claims-v2",
        "evidence": {item.id: fingerprint(item.model_dump(mode="json")) for item in document.evidence},
        "subjects": subject_rows,
        "claims_hash": fingerprint([claim.model_dump(mode="json") for claim in claims]),
        "charts": {chart.id: _chart_certificate(chart) for chart in document.charts},
    }


def seal_chart(document, chart_id: str) -> None:
    """Certify one server-recomputed chart without blessing unrelated narrative edits."""
    charts = document.metadata.setdefault("claim_baseline", {}).setdefault("charts", {})
    chart = next((item for item in document.charts if item.id == chart_id), None)
    if chart:
        charts[chart_id] = _chart_certificate(chart)
        evidence_by_id = {item.id: item for item in document.evidence}
        evidence_baseline = document.metadata["claim_baseline"].setdefault("evidence", {})
        for evidence_id in chart.evidence_ids:
            if evidence_id in evidence_by_id:
                evidence_baseline[evidence_id] = fingerprint(evidence_by_id[evidence_id].model_dump(mode="json"))


def _same_numbers(current: str, prior: dict) -> bool:
    expected = [(round(float(value), 10), unit) for value, unit in prior.get("numbers", [])]
    return Counter(expected) == Counter(_numbers(current))


def _same_terms(current: str, prior: dict) -> bool:
    folded = current.casefold()
    return all(str(term).casefold() in folded for term in prior.get("required_terms", []))


def _calculation_status(evidence):
    calculation = evidence.calculation
    if not calculation:
        return None
    try:
        values = calculation.get("operands", [])
        operation = calculation["operation"]
        if operation == "sum":
            expected, expected_unit = sum(values), calculation.get("unit", "number")
        elif operation == "growth":
            expected = growth_rate(*values) if calculation.get("period_kind") == "interval" else period_growth(*values, calculation["current_period"], calculation["baseline_period"], calculation["period_kind"])
            expected_unit = "ratio"
        elif operation == "ratio":
            if values[1] == 0:
                raise ValueError("分母为零")
            expected, expected_unit = values[0] / values[1], "ratio"
        elif operation == "rank":
            expected, expected_unit = descending_rank(values, calculation["candidate"]), "rank"
        elif operation == "correlation":
            aggregates = calculation.get("aggregates")
            if aggregates:
                n, sx, sy = aggregates["n"], aggregates["sum_x"], aggregates["sum_y"]
                numerator = n * aggregates["sum_xy"] - sx * sy
                denominator = math.sqrt((n * aggregates["sum_x2"] - sx * sx) * (n * aggregates["sum_y2"] - sy * sy))
                expected = numerator / denominator
            else:
                expected = calculation["result"]
            if not -1 <= expected <= 1:
                raise ValueError("相关系数超出 [-1, 1]")
            expected_unit = "correlation"
        elif operation == "count":
            expected = sum(values)
            if expected < 0 or int(expected) != expected:
                raise ValueError("计数必须为非负整数")
            expected_unit = "count"
        else:
            raise ValueError("未知计算类型")
        if calculation.get("unit") != expected_unit or not math.isfinite(float(calculation["result"])) or not math.isclose(float(expected), float(calculation["result"]), rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("计算结果或单位不一致")
        return "verified", "已按结构化操作数复算；数据真实性仍依赖来源。"
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        return "unverified", str(exc)


def check_chart_consistency(document):
    baseline = (document.metadata.get("claim_baseline") or {}).get("charts") or {}
    evidence_by_id = {item.id: item for item in document.evidence}
    results = []
    chart_blocks = {block.chart_id: block for block in document.blocks if block.chart_id}
    for chart in document.charts:
        prior = baseline.get(chart.id)
        reasons = []
        if not prior:
            reasons.append("缺少服务端图表证书")
        else:
            current = _chart_certificate(chart)
            for field, label in (("data_hash", "绘图数据"), ("binding", "字段绑定"), ("evidence_ids", "证据引用"), ("unit", "单位"), ("title", "标题"), ("description", "说明")):
                if current[field] != prior.get(field):
                    reasons.append(f"{label}与已核验版本不一致")
        linked = [evidence_by_id.get(item) for item in chart.evidence_ids]
        original_evidence = (document.metadata.get("claim_baseline") or {}).get("evidence") or {}
        if any(not item or fingerprint(item.model_dump(mode="json")) != original_evidence.get(item.id) for item in linked):
            reasons.append("图表引用的证据缺失或内容已变化")
        source_columns = {column for item in linked if item for column in item.source_columns}
        bound = [field.column for field in [chart.y, *chart.series] if field]
        unknown = [column for column in bound if column not in source_columns and column not in {"period", "value", "count"}]
        if unknown:
            reasons.append("度量字段未出现在所引证据中：" + "、".join(unknown))
        block = chart_blocks.get(chart.id)
        if block and not set(chart.evidence_ids).issubset(block.evidence_ids):
            reasons.append("正文图表块与图表引用的证据不一致")
        calculation = next((item.calculation for item in linked if item and item.calculation), None)
        if calculation:
            try:
                operation = calculation.get("operation")
                if chart.chart_type == "kpi" and chart.data:
                    actual = float(chart.data[0]["value"])
                    expected = float(calculation["result"]) * (100 if operation == "ratio" else 1)
                    if not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-4):
                        reasons.append("指标卡金额或比率与证据计算结果不一致")
                    if operation == "ratio" and chart.style.unit != "%":
                        reasons.append("比率指标卡单位不是百分号")
                elif operation == "growth" and chart.data:
                    baseline_value, current_value = float(calculation["operands"][1]), float(calculation["operands"][0])
                    if str(chart.data[0].get("period")) != str(calculation["baseline_period"]) or str(chart.data[-1].get("period")) != str(calculation["current_period"]):
                        reasons.append("趋势图首末期间与证据不一致")
                    metric = calculation["metric"]
                    if not math.isclose(float(chart.data[0][metric]), baseline_value, rel_tol=1e-8) or not math.isclose(float(chart.data[-1][metric]), current_value, rel_tol=1e-8):
                        reasons.append("趋势图首末金额与证据不一致")
                elif operation == "rank" and chart.data:
                    metric, dimension = calculation["metric"], calculation["dimension"]
                    if str(chart.data[0].get(dimension)) != str(calculation["member"]) or not math.isclose(float(chart.data[0][metric]), float(calculation["candidate"]), rel_tol=1e-8):
                        reasons.append("图表第一名、金额或维度成员与排名证据不一致")
                    if any(float(chart.data[index][metric]) < float(chart.data[index + 1][metric]) for index in range(len(chart.data) - 1)):
                        reasons.append("排名图未按指标降序排列")
            except (KeyError, TypeError, ValueError, IndexError):
                reasons.append("无法按结构化证据核对图表金额、期间、单位或排名")
        results.append({
            "target_kind": "chart", "target_id": chart.id, "type": "fact", "text": chart.title,
            "evidence_ids": chart.evidence_ids, "status": "unverified" if reasons else "verified",
            "reason": "；".join(reasons) if reasons else "图表数据、字段、单位、标题、说明和正文证据引用一致。",
        })
    return results


def check_claims(document):
    baseline = document.metadata.get("claim_baseline") or {}
    known = baseline.get("subjects") or {}
    evidence = {item.id: fingerprint(item.model_dump(mode="json")) for item in document.evidence}
    original_evidence = baseline.get("evidence") or {}
    result = []
    for item in document.evidence:
        checked = _calculation_status(item)
        if checked:
            status, reason = checked
            result.append({"target_kind": "calculation", "target_id": item.id, "type": "fact", "text": item.statement, "evidence_ids": [item.id], "status": status, "reason": reason})

    claims_intact = baseline.get("claims_hash") == fingerprint([claim.model_dump(mode="json") for claim in document.claims])
    for kind, key, text, refs, category in subjects(document):
        prior = known.get(f"{kind}:{key}")
        checked_refs = (prior or {}).get("evidence_ids", refs)
        if kind == "summary" and not checked_refs:
            checked_refs = list(original_evidence)
        same_evidence = all(evidence.get(ref) == original_evidence.get(ref) and ref in original_evidence for ref in checked_refs)
        unchanged = bool(prior and prior["text"] == text and prior["evidence_ids"] == refs)
        semantic_rewrite = bool(prior and category == "fact" and prior["evidence_ids"] == refs and prior.get("claim_ids") and _same_numbers(text, prior) and _same_terms(text, prior))
        status = "verified" if claims_intact and same_evidence and (unchanged or semantic_rewrite) else "unverified"
        if status == "verified":
            reason = "与服务端基线及证据一致。" if unchanged else "文字已改写；结构化指标、数值、单位语义、实体和证据引用仍一致。"
        else:
            reason = "内容中的结构化事实、引用、服务端 Claim 或底层证据已变化；需要重新计算并核验。"
        if category == "assumption":
            status, reason = "assumption", "未经确认的业务假设，不作为已验证事实。"
        result.append({"target_kind": kind, "target_id": key, "type": category, "text": text, "evidence_ids": refs, "status": status, "reason": reason})
    return [*result, *check_chart_consistency(document)]
