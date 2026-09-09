"""Paid, serial acceptance of the running API. No hidden retries or source mutations."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import DATA_DIR
from app.services import read_dataframe


REQUESTS = {
    "superstore": "生成 Global Superstore 经营分析报告。全量核算销售额、利润和利润率，分析区域贡献和折扣亏损风险，根据结果做最多三轮固定只读补算。不做预测或推断统计。日期损坏时明确说明不能分析趋势，币种未知时不要猜测。区分事实、待验证解释、可验证行动。",
    "bike": "分析 Bike Sharing 小时需求。比较时段、季节、天气和工作日差异，累计量同时核对观测小时数、观测天数、平均每观测小时和平均每观测日需求。做最多三轮固定只读补算。不做预测或推断统计，不回归分类编码。日级 N:1 右表字段不得直接累加，缺失小时不能补零，不能把相关性解释成因果。生成事实、解释、行动和限制明确的报告。",
}


def require(response, label):
    if response.is_error:
        raise RuntimeError(f"{label}: HTTP {response.status_code}: {response.text[:600]}")
    return response.json()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def usage_for(conversation_id):
    with sqlite3.connect(f"file:{(DATA_DIR / 'aibi-v2.db').as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        calls = [dict(row) for row in conn.execute(
            "SELECT stage,purpose,model,prompt_tokens,completion_tokens,total_tokens,latency_ms,status,"
            "estimated_cost_cny,usage_unavailable FROM llm_usage_logs WHERE conversation_id=? ORDER BY created_at,id",
            (conversation_id,))]
    stages = defaultdict(lambda: {"calls": 0, "tokens": 0, "latency_ms": 0})
    for row in calls:
        group = stages[row["purpose"] or row["stage"]]
        group["calls"] += 1
        group["tokens"] += row["total_tokens"]
        group["latency_ms"] += row["latency_ms"]
    return {"calls": calls, "by_purpose": dict(stages), "total_tokens": sum(r["total_tokens"] for r in calls),
            "estimated_cost_cny": sum(r["estimated_cost_cny"] for r in calls),
            "usage_complete_for_logged_responses": not any(r["usage_unavailable"] for r in calls)}


def source_snapshot(dataset, case):
    with sqlite3.connect(f"file:{(DATA_DIR / 'aibi-v2.db').as_posix()}?mode=ro", uri=True) as conn:
        key = conn.execute("SELECT storage_key FROM datasets WHERE id=?", (dataset["id"],)).fetchone()[0]
    path = DATA_DIR / key
    frame = read_dataframe(key)
    if case == "superstore":
        totals = {"metric-sales": float(frame["Sales"].sum()), "metric-profit": float(frame["Profit"].sum())}
        assert len(frame) == 51290
        assert round(totals["metric-sales"], 2) == 12642905.00
        assert round(totals["metric-profit"], 2) == 1467457.29
        regions = frame.groupby("Region")[["Sales", "Profit"]].sum().to_dict("index")
    else:
        assert len(frame) == 17379 and int(frame["cnt"].sum()) == 3292679
        assert (frame["cnt"] == frame["casual"] + frame["registered"]).all()
        assert "day__cnt" in dataset["semantics"]["non_additive_columns"]
        totals = {"metric-quantity": int(frame["cnt"].sum())}
        regions = None
    return path, {"dataset_id": dataset["id"], "version_id": dataset["current_version_id"],
                  "sha256": digest(path), "rows": len(frame), "totals": totals, "regions": regions}


def run_attempt(client, workspace, dataset, case, index, output, source):
    path, expected = source
    attempt_dir = output / f"{case}-{index}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    record = {"case": case, "attempt": index, "source": expected, "status": "failed"}
    start = time.perf_counter()
    conversation_id = None
    try:
        caps = {"deep_analysis": True, "max_rounds": 3, "content_review": True, "chart_layout": True, "alternatives": False}
        conversation = require(client.post("/api/v1/conversations", json={
            "workspace_id": workspace, "dataset_id": dataset["id"], "title": f"真实回归 {case} {index}",
            "clarification_mode": "off", "analysis_capabilities": caps}), "conversation")
        conversation_id = conversation["id"]
        record["conversation_id"] = conversation_id
        plan = require(client.post("/api/v1/chat/plan", json={
            "workspace_id": workspace, "conversation_id": conversation_id, "dataset_id": dataset["id"],
            "message": REQUESTS[case], "analysis_mode": "business", "execution_mode": "safe",
            "analysis_options": {"include_report": True, "include_recommendations": True, "show_code": True, "capabilities": caps}}), "plan")
        save(attempt_dir / "plan.json", plan)
        record["planning_provider"] = (plan["user_message"]["message_meta"].get("planning") or {}).get("provider")
        assert record["planning_provider"] == "deepseek", "planning degraded"
        result = require(client.post("/api/v1/chat/execute", json={
            "workspace_id": workspace, "conversation_id": conversation_id,
            "plan_message_id": plan["user_message"]["id"], "approved": True}), "execute")
        save(attempt_dir / "execution.json", result)
        meta = result["assistant_message"]["message_meta"]
        record.update(report_id=result.get("report_id"), synthesis_provider=meta.get("provider"),
                      prompt_versions=meta.get("prompt_versions"),
                      synthesis_limitations=(meta.get("claims") or {}).get("limitations"),
                      component_failures=[r for r in meta.get("component_results", []) if r.get("status") == "failed"],
                      tool_failures=[r for r in meta.get("tool_runs", []) if r.get("status") == "failed"])
        assert result.get("report_id"), "no report"
        report = require(client.get(f"/api/v1/reports/{result['report_id']}"), "report")
        save(attempt_dir / "report.json", report)
        document = report["document"]
        evid = {item["id"]: item for item in document["evidence"]}
        actual = {key: evid[key]["calculation"]["result"] for key in expected["totals"]}
        assert all(abs(actual[k] - v) < .0001 for k, v in expected["totals"].items()), "source total mismatch"
        if case == "bike":
            facts = {f["role"]: f["value"] for f in evid["relationship-reconciliation"]["calculation"]["facts"]}
            assert facts == {"left_total": 3292679, "right_total": 3292679, "difference": 0}
        quality = document.get("quality") or {}
        record.update(totals=actual, charts=len(document["charts"]), evidence=len(evid),
                      quality_passed=quality.get("passed"), quality_score=quality.get("score"),
                      unverified_claims=[c for c in quality.get("claim_checks", []) if c.get("status") == "unverified"],
                      deep_evidence_count=sum(k.startswith("deep-") for k in evid))
        record["status"] = "passed" if (
            meta.get("provider") == "deepseek" and quality.get("passed") and
            not record["unverified_claims"] and not record["component_failures"] and not record["tool_failures"]
        ) else "degraded"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:1000]}"
    finally:
        record["elapsed_seconds"] = round(time.perf_counter() - start, 3)
        record["source_hash_unchanged"] = digest(path) == expected["sha256"]
        if not record["source_hash_unchanged"]:
            record["status"] = "failed"
        record["usage"] = usage_for(conversation_id) if conversation_id else {}
        save(attempt_dir / "acceptance.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["both", "superstore", "bike"], default="both")
    parser.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    args = parser.parse_args()
    output = args.output or ROOT / "data" / "acceptance" / datetime.now().strftime("%Y%m%d-%H%M%S-live-suite")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    with httpx.Client(base_url=args.api, timeout=300) as client:
        require(client.get("/api/v1/analysis-capabilities/reserved"), "current API version")
        workspace = require(client.post("/api/v1/workspaces/bootstrap"), "bootstrap")["id"]
        providers = require(client.get("/api/v1/settings/providers", params={"workspace_id": workspace}), "providers")
        enabled = [p for p in providers if p["enabled"] and p.get("has_api_key")]
        assert len(enabled) == 1 and enabled[0]["provider"] == "deepseek", "acceptance requires DeepSeek as the only enabled keyed provider"
        datasets = require(client.get("/api/v1/datasets", params={"workspace_id": workspace}), "datasets")
        cases = ["superstore", "bike"] if args.dataset == "both" else [args.dataset]
        for case in cases:
            candidates = [d for d in datasets if (d["name"].casefold() == "global superstore" if case == "superstore"
                else d["name"] == "Bike Sharing 小时与日级关联" and d["profile"].get("row_count") == 17379)]
            assert candidates, f"missing imported {case}"
            dataset = max(candidates, key=lambda d: d.get("created_at", ""))
            source = source_snapshot(dataset, case)
            for index in range(1, args.repetitions + 1):
                print(f"START {case} {index}", flush=True)
                record = run_attempt(client, workspace, dataset, case, index, output, source)
                records.append(record)
                save(output / "suite.json", {"records": records, "all_passed": all(r["status"] == "passed" for r in records)})
                print(json.dumps({k: record.get(k) for k in ["case", "attempt", "status", "report_id", "error", "synthesis_limitations"]}, ensure_ascii=False), flush=True)
                if record["status"] == "failed":
                    break  # No automatic paid retry on operational failures.
    print(f"RESULT {output / 'suite.json'}", flush=True)


if __name__ == "__main__":
    main()
