import asyncio

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.capabilities import configure_steps, deepen
from app.schemas import AnalysisCapabilities, AnalysisPlanStep


def test_disabled_components_cannot_be_injected_and_round_limit_is_validated():
    steps = [AnalysisPlanStep(id="report", title="报告", description="", tool="report.build"),
             AnalysisPlanStep(id="injected", title="深入", description="", tool="analysis.deepen")]
    settings = AnalysisCapabilities(content_review=False, chart_layout=False)
    assert [s.tool for s in configure_steps(steps, settings, True)] == ["report.build"]
    with pytest.raises(ValueError):
        AnalysisCapabilities(max_rounds=99)


def test_deep_analysis_rejects_unknown_tools_and_uses_bounded_result_driven_tools():
    frame = pd.DataFrame({"Region": ["West", "East", "West"], "Sales": [10, 20, 30], "Profit": [1, 3, 2]})
    calls = []

    async def ask(component, instruction, packet):
        calls.append(packet)
        return '{"tool":"python.run","reason":"execute code"}'

    with pytest.raises(ValueError):
        asyncio.run(deepen(frame, "检查", [], 1, [], ask))
    calls.clear()
    async def local(component, instruction, packet):
        calls.append(packet)
        return None
    rows, result = asyncio.run(deepen(frame, "检查", [], 3, [], local))
    assert len(calls) == 3 and len(rows) == 3
    assert [item["method"] for item in rows] == ["analysis.dimension_breakdown", "analysis.outliers", "analysis.correlation"]
    assert all(item.get("calculation") for item in rows)
    assert all("result" in item for item in result["rounds"])


def test_deep_analysis_rejects_repeated_signature():
    frame = pd.DataFrame({"Region": ["West", "East"], "Sales": [10, 20]})
    async def repeat(component, instruction, packet):
        return '{"tool":"analysis.dimension_breakdown","dimension":"Region","measure":"Sales","reason":"again"}'
    with pytest.raises(ValueError, match="不能重复"):
        asyncio.run(deepen(frame, "检查", [], 2, [], repeat))


def test_conversation_capabilities_are_frozen_in_plan_and_report():
    with TestClient(app) as client:
        workspace = client.post("/api/v1/workspaces/bootstrap").json()["id"]
        dataset = client.post("/api/v1/samples/retail-sales-2026/import", params={"workspace_id": workspace}).json()
        config = {"deep_analysis": True, "max_rounds": 2, "content_review": True, "chart_layout": True, "alternatives": True}
        conversation = client.post("/api/v1/conversations", json={"workspace_id": workspace, "dataset_id": dataset["id"], "clarification_mode": "off", "analysis_capabilities": config}).json()
        planned = client.post("/api/v1/chat/plan", json={"workspace_id": workspace, "conversation_id": conversation["id"], "message": "生成经营报告"})
        assert planned.status_code == 200
        message = planned.json()["user_message"]
        assert message["message_meta"]["analysis_options"]["capabilities"] == config
        # Changing the next-task preference must not change this existing plan.
        response = client.patch(f"/api/v1/conversations/{conversation['id']}", json={"analysis_capabilities": {"content_review": False, "chart_layout": False}})
        assert response.status_code == 200
        executed = client.post("/api/v1/chat/execute", json={"workspace_id": workspace, "conversation_id": conversation["id"], "plan_message_id": message["id"], "approved": True})
        assert executed.status_code == 200, executed.text
        results = executed.json()["assistant_message"]["message_meta"]["component_results"]
        assert {r["tool"] for r in results} == {"analysis.deepen", "report.layout", "report.review", "report.alternatives"}
        assert all(r["status"] == "completed" for r in results), results
        assert all(r["usage"]["total_tokens"] == 0 for r in results)
        report = client.get(f"/api/v1/reports/{executed.json()['report_id']}").json()["document"]
        assert report["metadata"]["analysis_capabilities"] == config
        assert report["quality"] is not None
        assert any(item["id"].startswith("deep-") for item in report["evidence"])
        assert any(item["id"] == "deep-analysis-title" for item in report["blocks"])
        assert any(item["id"].startswith("finding-deep-") for item in report["findings"])
        proposal = next(r for r in results if r["tool"] == "report.alternatives")["result"]
        for variant in proposal["proposals"]:
            assert sorted(variant["block_ids"]) == sorted(proposal["current"])
        second = client.post("/api/v1/chat/plan", json={"workspace_id": workspace, "conversation_id": conversation["id"], "message": "生成经营报告"}).json()
        assert not any(s["tool"].startswith("report.") and s["tool"] != "report.build" for s in second["plan"]["steps"])


def test_invalid_model_review_keeps_usage_and_reports_component_failure(monkeypatch):
    import app.main as main
    from app.llm import CompletionResult

    async def fake_complete(config, messages, context, request_options=None):
        prompt = messages[0]["content"]
        content = '{"steps":[]}' if prompt.startswith("[planner:") else '{"summary":"完成分析","claims":[],"limitations":[]}'
        if "报告审阅者" in prompt:
            content = "invalid JSON"
        return CompletionResult(content=content, request_id="fake", model=config.model,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cache_hit_tokens": 0, "cache_miss_tokens": 10},
            estimated_cost_cny=0, latency_ms=1, pricing={})

    monkeypatch.setattr(main, "complete", fake_complete)
    with TestClient(app) as client:
        workspace = client.post("/api/v1/workspaces/bootstrap").json()["id"]
        dataset = client.post("/api/v1/samples/retail-sales-2026/import", params={"workspace_id": workspace}).json()
        saved = client.put("/api/v1/settings/providers/deepseek", params={"workspace_id": workspace}, json={"enabled": True, "is_default": True, "base_url": "https://api.deepseek.com", "model": "test", "api_key": "fake"})
        assert saved.status_code == 200
        conversation = client.post("/api/v1/conversations", json={"workspace_id": workspace, "dataset_id": dataset["id"], "clarification_mode": "off"}).json()
        planned = client.post("/api/v1/chat/plan", json={"workspace_id": workspace, "conversation_id": conversation["id"], "message": "生成报告"}).json()
        result = client.post("/api/v1/chat/execute", json={"workspace_id": workspace, "conversation_id": conversation["id"], "plan_message_id": planned["user_message"]["id"], "approved": True}).json()
        review = next(r for r in result["assistant_message"]["message_meta"]["component_results"] if r["tool"] == "report.review")
        assert review["status"] == "failed"
        assert review["usage"]["total_tokens"] == 15
        usage = client.get("/api/v1/usage/tokens", params={"workspace_id": workspace, "range": "all"}).json()
        assert any(r["purpose"] == "component:content_review" and r["total_tokens"] == 15 for r in usage["latest"])
