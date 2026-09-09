"""Run a non-destructive multi-table acceptance with the UCI Bike Sharing CSV files."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import os

import pandas as pd
from httpx import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import DATA_DIR


SOURCE_ROOT = Path(r"C:\Users\Administrator\Downloads\bike+sharing+dataset")


def require(response, label: str):
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text[:1200]}")
    return response.json()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upload(client: Client, workspace_id: str, path: Path) -> dict:
    with path.open("rb") as handle:
        return require(client.post(
            "/api/v1/datasets/upload", data={"workspace_id": workspace_id},
            files={"file": (path.name, handle, "text/csv")},
        ), f"upload {path.name}")


def main() -> None:
    day_path = SOURCE_ROOT / "day.csv"
    hour_path = SOURCE_ROOT / "hour.csv"
    if not day_path.is_file() or not hour_path.is_file():
        raise RuntimeError(f"Bike Sharing CSV files not found under {SOURCE_ROOT}")
    source_hashes = {"day.csv": sha256(day_path), "hour.csv": sha256(hour_path)}
    day_frame = pd.read_csv(day_path)
    hour_frame = pd.read_csv(hour_path)
    if len(day_frame) != 731 or len(hour_frame) != 17_379:
        raise RuntimeError("Unexpected Bike Sharing source row counts")
    if not (day_frame["casual"] + day_frame["registered"]).equals(day_frame["cnt"]):
        raise RuntimeError("day.csv violates cnt = casual + registered")
    if not (hour_frame["casual"] + hour_frame["registered"]).equals(hour_frame["cnt"]):
        raise RuntimeError("hour.csv violates cnt = casual + registered")

    # Test the running application. Do not run a second lifespan/recovery worker
    # against the user's database while their server may already be active.
    with Client(base_url=os.getenv("AIBI_ACCEPTANCE_API", "http://127.0.0.1:8010"), timeout=240) as client:
        require(client.get("/api/v1/health"), "running API")
        workspace = require(client.post("/api/v1/workspaces/bootstrap"), "bootstrap")
        day = upload(client, workspace["id"], day_path)
        hour = upload(client, workspace["id"], hour_path)
        relationship_request = {
            "workspace_id": workspace["id"], "left_dataset_id": hour["id"],
            "right_dataset_id": day["id"], "left_keys": ["dteday"],
            "right_keys": ["dteday"], "join_type": "left", "right_prefix": "day",
        }
        preview = require(client.post(
            "/api/v1/dataset-relationships/preview", json=relationship_request,
        ), "relationship preview")
        expected = {
            "cardinality": "many_to_one", "left_rows": 17_379, "right_rows": 731,
            "matched_left_rows": 17_379, "matched_right_rows": 731,
            "unmatched_left_rows": 0, "unmatched_right_rows": 0,
            "matched_key_count": 731, "output_rows": 17_379,
        }
        for key, value in expected.items():
            if preview.get(key) != value:
                raise RuntimeError(f"Relationship {key} mismatch: {preview.get(key)} != {value}")
        relation = require(client.post("/api/v1/dataset-relationships", json={
            **relationship_request, "name": "Bike Sharing 小时与日级关联",
            "acknowledge_non_additive": True,
        }), "relationship apply")
        result_dataset = relation["result_dataset"]
        if "day__cnt" not in result_dataset["semantics"]["non_additive_columns"]:
            raise RuntimeError("Expanded daily cnt was not marked non-additive")
        result_dataset = require(client.patch(
            f"/api/v1/datasets/{result_dataset['id']}/semantics", json={
                "workspace_id": workspace["id"], "unit": "rental", "grain": "one row per hour",
                "date_formats": {"dteday": "%Y-%m-%d"},
                "column_roles": {"instant": "id", "dteday": "date", "cnt": "measure", "hr": "dimension", "season": "dimension", "weathersit": "dimension", "workingday": "dimension"},
                "column_units": {"cnt": "rentals", "casual": "rentals", "registered": "rentals"},
                "column_labels": {"cnt": "骑行次数", "hr": "小时", "season": "季节", "weathersit": "天气状况", "workingday": "日期类型"},
                "value_labels": {
                    "hr": {str(hour): f"{hour:02d}:00" for hour in range(24)},
                    "season": {"1": "春季", "2": "夏季", "3": "秋季", "4": "冬季"},
                    "weathersit": {"1": "晴朗/少云", "2": "雾或多云", "3": "小雨雪", "4": "恶劣天气"},
                    "workingday": {"0": "周末或节假日", "1": "工作日"},
                },
            },
        ), "semantics")
        blocked = client.post(f"/api/v1/datasets/{result_dataset['id']}/sql", json={
            "workspace_id": workspace["id"], "sql": 'SELECT SUM("day__cnt") FROM dataset',
        })
        if blocked.status_code != 400:
            raise RuntimeError("Non-additive daily total was accepted by SQL")

        conversation = require(client.post("/api/v1/conversations", json={
            "workspace_id": workspace["id"], "dataset_id": result_dataset["id"],
            "title": "Bike Sharing 多表验收", "clarification_mode": "off",
            "analysis_capabilities": {"deep_analysis": True, "max_rounds": 2, "content_review": True},
        }), "conversation")
        planned = require(client.post("/api/v1/chat/plan", json={
            "workspace_id": workspace["id"], "conversation_id": conversation["id"],
            "dataset_id": result_dataset["id"], "analysis_mode": "business", "execution_mode": "safe",
            "message": "分析共享单车小时需求的时间趋势、时段、季节、天气和工作日差异。仅做描述性分析，不做推断统计或预测，不对季节、小时等分类编码做线性回归。日级字段来自 N:1 右表，不得直接求和；生成带证据的报告。",
            "analysis_options": {"include_report": True, "include_recommendations": True, "show_code": True,
                "capabilities": {"deep_analysis": True, "max_rounds": 2, "content_review": True}},
        }), "AI plan")
        planning_provider = (planned["user_message"]["message_meta"].get("planning") or {}).get("provider")
        if planning_provider != "deepseek":
            raise RuntimeError(f"DeepSeek planning fell back: {planning_provider}")
        executed = require(client.post("/api/v1/chat/execute", json={
            "workspace_id": workspace["id"], "conversation_id": conversation["id"],
            "plan_message_id": planned["user_message"]["id"], "approved": True,
        }), "AI execute")
        synthesis_provider = executed["assistant_message"]["message_meta"].get("provider")
        report_id = executed.get("report_id")
        if not report_id:
            raise RuntimeError("AI workflow did not produce a report; no silent deterministic fallback")
        report = require(client.get(f"/api/v1/reports/{report_id}"), "report")
        document = report["document"]
        if not document["quality"]["passed"]:
            raise RuntimeError(f"Report failed quality gate: {document['quality']['issues']}")
        metric = next(item for item in document["evidence"] if item["id"] == "metric-quantity")
        if metric["calculation"]["result"] != int(hour_frame["cnt"].sum()):
            raise RuntimeError("Report total differs from independently computed source total")
        reconciliation = next(item for item in document["evidence"] if item["id"] == "relationship-reconciliation")
        facts = {item["role"]: item["value"] for item in reconciliation["calculation"]["facts"]}
        if facts != {"left_total": 3292679, "right_total": 3292679, "difference": 0}:
            raise RuntimeError("Cross-grain reconciliation failed")
        if sha256(day_path) != source_hashes["day.csv"] or sha256(hour_path) != source_hashes["hour.csv"]:
            raise RuntimeError("Source files changed during acceptance")
        if not any(item["id"] == "dataset-relationship" for item in document["evidence"]):
            raise RuntimeError("Report does not contain relationship evidence")
        if any(
            item.get("id") != "relationship-reconciliation"
            and "SUM(day__cnt)" in (item.get("method") or "")
            for item in document["evidence"]
        ):
            raise RuntimeError("Report summed the expanded daily count")
        if not any(item["id"] == "primary-trend" for item in document["charts"]):
            raise RuntimeError("Report did not produce the validated date trend")

        usage = require(client.get("/api/v1/usage/tokens", params={
            "workspace_id": workspace["id"], "range": "all", "group_by": "stage",
        }), "usage")
        calls = [item for item in usage["latest"] if item.get("conversation_id") == conversation["id"]]
        database = sqlite3.connect(DATA_DIR / "aibi-v2.db")
        result_hash = database.execute("SELECT content_hash FROM dataset_versions WHERE id = ?", (result_dataset["current_version_id"],)).fetchone()[0]
        cost = float(database.execute(
            "SELECT COALESCE(SUM(estimated_cost_cny), 0) FROM llm_usage_logs WHERE conversation_id = ?",
            (conversation["id"],),
        ).fetchone()[0] or 0)
        database.close()
        accepted_at = datetime.now().astimezone()
        output = ROOT / "data" / "acceptance" / accepted_at.strftime("%Y%m%d-%H%M%S-bike-multitable")
        output.mkdir(parents=True, exist_ok=False)
        record = {
            "accepted_at": accepted_at.isoformat(),
            "source": {
                "directory": str(SOURCE_ROOT), "hashes": source_hashes,
                "day_rows": len(day_frame), "hour_rows": len(hour_frame),
                "day_distinct_dates": int(day_frame["dteday"].nunique()),
                "hour_distinct_dates": int(hour_frame["dteday"].nunique()),
                "day_total_cnt": int(day_frame["cnt"].sum()),
                "hour_total_cnt": int(hour_frame["cnt"].sum()),
                "cnt_identity_valid": True,
            },
            "relationship": {"id": relation["id"], **preview},
            "result_dataset": {
                "content_hash": result_hash,
                "id": result_dataset["id"], "version_id": result_dataset["current_version_id"],
                "row_count": result_dataset["profile"]["row_count"],
                "source_dataset_version_ids": result_dataset["semantics"]["source_dataset_version_ids"],
                "non_additive_columns": result_dataset["semantics"]["non_additive_columns"],
            },
            "ai": {
                "synthesis_provider": synthesis_provider,
                "full_model_pipeline_passed": synthesis_provider == "deepseek",
                "status": "passed" if synthesis_provider == "deepseek" else "degraded",
                "conversation_id": conversation["id"], "planning_provider": planning_provider,
                "calls": len(calls), "total_tokens": sum(item["total_tokens"] for item in calls),
                "estimated_cost_cny": round(cost, 8),
            },
            "report": {
                "id": report_id, "title": report["title"], "charts": len(document["charts"]),
                "evidence": len(document["evidence"]), "quality_score": document["quality"]["score"],
                "quality_passed": document["quality"]["passed"],
            },
            "guards": {"expanded_daily_sum_blocked": True, "source_hashes_unchanged": {
                "day.csv": sha256(day_path) == source_hashes["day.csv"],
                "hour.csv": sha256(hour_path) == source_hashes["hour.csv"],
            }},
        }
        (output / "acceptance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**record, "acceptance_file": str(output / "acceptance.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
