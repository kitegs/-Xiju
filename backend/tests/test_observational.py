import pandas as pd
import pytest
from app.services import build_report, profile_dataframe


def test_normalized_comparison_distinguishes_total_from_observed_hour_mean():
    from app.observational import hourly_comparison
    frame = pd.DataFrame({"dteday": ["2026-01-01"] * 3, "hr": [0, 1, 2],
                          "group": ["A", "A", "B"], "cnt": [10, 10, 15]})
    result = hourly_comparison(frame, "group", "cnt", "dteday", "hr")
    rows = {r["group"]: r for r in result}
    assert rows["A"]["total"] == 20 and rows["B"]["total"] == 15
    assert rows["A"]["mean_per_observed_hour"] == 10
    assert rows["B"]["mean_per_observed_hour"] == 15
    assert rows["A"]["observed_hours"] == 2 and rows["A"]["observed_days"] == 1
    assert result[0]["group"] == "B"
    assert rows["B"]["mean_per_observed_day"] == 15  # Not divided by a fabricated full day.


def test_hourly_grain_rejects_duplicate_slots_and_nonfinite_values():
    from app.observational import hourly_comparison
    frame = pd.DataFrame({"dteday": ["2026-01-01"] * 2, "hr": [0, 0], "group": ["A", "B"], "cnt": [1, 2]})
    with pytest.raises(ValueError, match="重复"):
        hourly_comparison(frame, "group", "cnt", "dteday", "hr")
    frame["hr"] = [0, 1]
    frame["cnt"] = [1, float("inf")]
    with pytest.raises(ValueError, match="有限"):
        hourly_comparison(frame, "group", "cnt", "dteday", "hr")


def test_hourly_report_contains_normalized_evidence_and_nonfinancial_advice():
    frame = pd.DataFrame({"dteday": ["2026-01-01"] * 3, "hr": [0, 1, 2], "workingday": [0, 0, 1], "cnt": [10, 10, 15]})
    document = build_report(frame, profile_dataframe(frame), "单车", "分析工作日", {
        "grain": "one row per hour", "column_roles": {"hr": "dimension", "workingday": "dimension", "cnt": "measure"}})
    ev = next(e for e in document.evidence if e.id == "observed-workingday")
    assert ev.data[0]["mean_per_observed_hour"] == 15
    assert document.quality.passed, document.quality.issues
    content = "\n".join(b.content for b in document.blocks)
    assert "未补零" in content and "待验证" in content
    assert "盈利质量" not in content


def test_deep_intermediate_results_expose_normalized_comparison_to_next_round():
    from app.capabilities import _run_diagnostic, DiagnosticChoice
    frame = pd.DataFrame({"dteday": ["2026-01-01"] * 3, "hr": [0, 1, 2], "group": ["A", "A", "B"], "cnt": [10, 10, 15]})
    result = _run_diagnostic(frame, DiagnosticChoice(tool="analysis.dimension_breakdown", dimension="group", measure="cnt", reason="compare"), "deep-1", {"grain": "one row per hour"})
    assert "最高组为 B" in result["value"]
    assert result["data"][0]["observed_hours"] == 2
