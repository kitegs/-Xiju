"""Run one paid, non-destructive DeepSeek acceptance against imported Global Superstore."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.main import app


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "acceptance" / datetime.now().strftime("%Y%m%d-%H%M%S")


def require(response, label: str):
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text[:1000]}")
    return response.json()


def main() -> None:
    with TestClient(app) as client:
        workspace = require(client.post("/api/v1/workspaces/bootstrap"), "bootstrap")
        datasets = require(client.get("/api/v1/datasets", params={"workspace_id": workspace["id"]}), "datasets")
        candidates = [item for item in datasets if item["name"].casefold() == "global superstore"]
        if not candidates:
            raise RuntimeError("Global Superstore is not imported in the active workspace")
        dataset = max(candidates, key=lambda item: int((item.get("profile") or {}).get("row_count", 0)))
        database = sqlite3.connect(DATA_DIR / "aibi-v2.db")
        storage_key = database.execute("SELECT storage_key FROM datasets WHERE id = ?", (dataset["id"],)).fetchone()[0]
        database.close()
        source = DATA_DIR / storage_key
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        providers = require(client.get("/api/v1/settings/providers", params={"workspace_id": workspace["id"]}), "providers")
        deepseek = next((item for item in providers if item["provider"] == "deepseek" and item["enabled"] and item.get("has_api_key")), None)
        if not deepseek:
            raise RuntimeError("An enabled DeepSeek provider with an API key is required")

        conversation = require(client.post("/api/v1/conversations", json={
            "workspace_id": workspace["id"], "dataset_id": dataset["id"],
            "title": "Global Superstore 真实交付验收", "clarification_mode": "off",
            "analysis_capabilities": {"deep_analysis": True, "max_rounds": 3, "content_review": True, "chart_layout": True, "alternatives": False},
        }), "conversation")
        request = {
            "workspace_id": workspace["id"], "conversation_id": conversation["id"], "dataset_id": dataset["id"],
            "message": "生成一份可交付的 Global Superstore 经营分析报告。核算销售额、利润和利润率，分析时间趋势、市场或区域贡献、高折扣亏损风险；根据每轮结果继续做最多三轮固定只读补充分析，并给出有证据、非因果化的解释与可验证建议。",
            "analysis_mode": "business", "execution_mode": "safe",
            "analysis_options": {"include_report": True, "include_recommendations": True, "show_code": True,
                "capabilities": {"deep_analysis": True, "max_rounds": 3, "content_review": True, "chart_layout": True, "alternatives": False}},
        }
        planned = require(client.post("/api/v1/chat/plan", json=request), "plan")
        planning = planned["user_message"]["message_meta"].get("planning") or {}
        if planning.get("provider") != "deepseek":
            raise RuntimeError(f"DeepSeek planning fell back: {planning}")
        executed = require(client.post("/api/v1/chat/execute", json={
            "workspace_id": workspace["id"], "conversation_id": conversation["id"],
            "plan_message_id": planned["user_message"]["id"], "approved": True,
        }), "execute")
        report_id = executed.get("report_id")
        if not report_id:
            raise RuntimeError(f"The model plan produced no report: {executed}")
        report = require(client.get(f"/api/v1/reports/{report_id}"), "report")
        document = report["document"]
        quality = document.get("quality") or {}
        unverified = [item for item in quality.get("claim_checks", []) if item.get("status") == "unverified"]
        if not quality.get("passed") or unverified:
            raise RuntimeError(f"Report quality gate failed: score={quality.get('score')} unverified={unverified[:5]}")
        deep_evidence = [item for item in document.get("evidence", []) if item["id"].startswith("deep-")]
        if not deep_evidence:
            raise RuntimeError("No result-driven evidence reached the report")

        exported = client.get(f"/api/v1/reports/{report_id}/export.docx")
        if exported.status_code != 200:
            raise RuntimeError(f"DOCX export failed: {exported.status_code} {exported.text[:1000]}")
        OUTPUT.mkdir(parents=True, exist_ok=False)
        docx_path = OUTPUT / "global-superstore-deepseek-acceptance.docx"
        docx_path.write_bytes(exported.content)
        docx_hash = hashlib.sha256(exported.content).hexdigest()
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError("Imported source changed during acceptance")

        usage = require(client.get("/api/v1/usage/tokens", params={"workspace_id": workspace["id"], "range": "all", "group_by": "stage"}), "usage")
        calls = [item for item in usage["latest"] if item.get("conversation_id") == conversation["id"]]
        if not calls or sum(item["total_tokens"] for item in calls) <= 0:
            raise RuntimeError("No real token usage was recorded")
        result = {
            "accepted_at": datetime.now().astimezone().isoformat(),
            "workspace_id": workspace["id"], "conversation_id": conversation["id"], "report_id": report_id,
            "dataset": {"id": dataset["id"], "name": dataset["name"], "row_count": (dataset.get("profile") or {}).get("row_count"), "sha256": source_hash},
            "provider": {"name": "deepseek", "model": deepseek["model"]},
            "report": {"title": report["title"], "charts": len(document.get("charts", [])), "findings": len(document.get("findings", [])), "evidence": len(document.get("evidence", [])), "deep_evidence": len(deep_evidence), "quality_score": quality.get("score"), "unverified_claims": len(unverified)},
            "usage": {"calls": len(calls), "total_tokens": sum(item["total_tokens"] for item in calls), "by_call": [{key: item.get(key) for key in ("stage", "purpose", "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "status")} for item in reversed(calls)]},
            "component_results": executed["assistant_message"]["message_meta"].get("component_results", []),
            "docx": {"path": str(docx_path), "sha256": docx_hash},
        }
        (OUTPUT / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
