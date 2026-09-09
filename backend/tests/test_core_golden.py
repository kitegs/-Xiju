"""Offline acceptance facts: expected values are hand-calculated, not model snapshots."""
from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from app.prompting import validate_synthesis, render_synthesis
from app.services import build_report, profile_dataframe
from app.relationships import materialize_relationship


EVIDENCE = [{"id": "sales", "value": "600.00", "calculation": {
    "metric": "Sales", "result": 600.0, "unit": "元", "current_period": "2026-01",
}}]


def bound_response():
    return {"summary": "总额为 {{total}}。", "bindings": [
        {"name": "total", "evidence_id": "sales", "path": "value"}],
        "claims": [{"text": "核对总额 {{total}}。", "type": "fact", "evidence_ids": ["sales"]}],
        "limitations": []}


def test_golden_bound_numbers_and_legacy_qualitative_output():
    original = deepcopy(EVIDENCE)
    result = validate_synthesis(bound_response(), EVIDENCE)
    assert result.summary == "总额为 600.00。"
    assert "600.00" in render_synthesis(result)
    assert result.summary_evidence_ids == ["sales"]
    assert EVIDENCE == original
    assert validate_synthesis({"summary": "已核对。", "claims": []}, EVIDENCE).summary == "已核对。"


@pytest.mark.parametrize("change", ["invented", "unknown", "wrong_path", "uncited", "duplicate"])
def test_golden_invalid_synthesis_fails_closed(change):
    raw = bound_response()
    if change == "invented": raw["claims"][0]["text"] = "总额为 999.00。"
    if change == "unknown": raw["bindings"][0]["evidence_id"] = "missing"
    if change == "wrong_path": raw["bindings"][0]["path"] = "calculation.missing"
    if change == "uncited": raw["claims"][0]["evidence_ids"] = []
    if change == "duplicate": raw["bindings"].append(raw["bindings"][0])
    with pytest.raises(ValueError): validate_synthesis(raw, EVIDENCE)


def test_golden_conflicting_evidence_ids_are_not_silently_overwritten():
    with pytest.raises(ValueError):
        validate_synthesis(bound_response(), [*EVIDENCE, {"id": "sales", "value": "999"}])


def test_golden_period_unit_and_nested_result_are_filled_without_conversion():
    raw = {"summary": "期间 {{period}}，总量 {{total}}{{unit}}。", "bindings": [
        {"name": "period", "evidence_id": "sales", "path": "calculation.current_period"},
        {"name": "total", "evidence_id": "sales", "path": "calculation.result"},
        {"name": "unit", "evidence_id": "sales", "path": "calculation.unit"}], "claims": []}
    assert validate_synthesis(raw, EVIDENCE).summary == "期间 2026-01，总量 600.0元。"
    raw["bindings"][1]["value"] = 999
    with pytest.raises(ValueError): validate_synthesis(raw, EVIDENCE)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), {"value": 3}, "{{nested}}"])
def test_golden_unsafe_scalar_bindings_are_rejected(value):
    with pytest.raises(ValueError):
        validate_synthesis(bound_response(), [{"id": "sales", "value": value}])


def test_golden_retail_totals_and_ranking_repeat_without_model():
    frame = pd.DataFrame({"Region": ["West", "East", "West"],
                          "Sales": [100., 200., 300.], "Profit": [10., -20., 30.]})
    for _ in range(2):
        report = build_report(frame, profile_dataframe(frame), "Golden", "比较区域")
        evidence = {item.id: item for item in report.evidence}
        assert evidence["metric-sales"].calculation["result"] == 600
        assert evidence["metric-profit"].calculation["result"] == 20
        rankings = [item.calculation for item in report.evidence if item.calculation and item.calculation.get("operation") == "rank"]
        assert any(item["member"] == "West" and item["candidate"] == 400 for item in rankings)


def test_golden_hour_day_join_preserves_grain():
    hour = pd.DataFrame({"date": ["2026-01-01", "2026-01-01", "2026-01-02"], "cnt": [10, 20, 40]})
    day = pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "cnt": [30, 40]})
    joined, profile, _ = materialize_relationship(hour, day, ["date"], ["date"], "left", "day")
    assert len(joined) == 3 and joined.cnt.sum() == day.cnt.sum() == 70
    assert "day__cnt" in profile["non_additive_columns"]
    assert joined["day__cnt"].sum() == 100  # The tempting but wrong expanded sum.


def test_run_terminal_state_and_reserved_capability_contract():
    from app.domain import transition_run, reserved_capabilities
    run = SimpleNamespace(status="queued")
    transition_run(run, "running")
    transition_run(run, "completed")
    with pytest.raises(ValueError): transition_run(run, "running")
    cancelled = SimpleNamespace(status="queued")
    transition_run(cancelled, "cancelled")
    with pytest.raises(ValueError): transition_run(cancelled, "queued")
    assert all(not item["available"] and not item["default_enabled"] for item in reserved_capabilities())


def test_golden_queued_plan_cannot_silently_change_data_or_tools():
    from app.domain import validate_execution_snapshot
    validate_execution_snapshot({"status": "pending", "steps": []}, {"status": "running", "steps": []}, ["v1"], "v1")
    with pytest.raises(ValueError): validate_execution_snapshot({}, {}, ["v1"], "v2")
    with pytest.raises(ValueError): validate_execution_snapshot({"steps": []}, {"steps": ["python.run"]}, ["v1"], "v1")


def test_golden_extracted_modules_have_no_reverse_dependency_and_routes_are_unique():
    import ast
    from pathlib import Path
    from app.main import app
    root = Path(__file__).resolve().parents[1] / "app"
    for name in ["report_routes", "run_execution", "run_runtime", "presenters", "domain"]:
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.ImportFrom) and node.module in {"main", "app.main"} for node in ast.walk(tree))
    routes = [(method, route.path) for route in app.routes for method in getattr(route, "methods", [])]
    assert len(routes) == len(set(routes))
    manifest = __import__("app.domain", fromlist=["reserved_capabilities"]).reserved_capabilities()
    assert manifest[0]["available"] is False
