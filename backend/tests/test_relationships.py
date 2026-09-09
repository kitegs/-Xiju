import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.main import app


def bike_frames():
    day = pd.DataFrame({
        "dteday": ["2011-01-01", "2011-01-02"],
        "daily_cnt": [985, 801],
        "season": [1, 1],
    })
    hour = pd.DataFrame({
        "instant": [1, 2, 3, 4],
        "dteday": ["2011-01-01", "2011-01-01", "2011-01-02", "2011-01-02"],
        "hr": [0, 1, 0, 1],
        "cnt": [16, 40, 32, 35],
    })
    return hour, day


def test_profile_and_materialize_many_to_one_relationship():
    from app.relationships import materialize_relationship, profile_relationship

    hour, day = bike_frames()
    profile = profile_relationship(hour, day, ["dteday"], ["dteday"], "left", "day")
    assert profile["safe"] is True
    assert profile["cardinality"] == "many_to_one"
    assert profile["left_rows"] == 4
    assert profile["right_rows"] == 2
    assert profile["matched_left_rows"] == 4
    assert profile["matched_right_rows"] == 2
    assert profile["output_rows"] == 4
    assert profile["match_rate"] == 1
    assert profile["non_additive_columns"] == ["day__daily_cnt", "day__season"]

    joined, materialized_profile, lineage = materialize_relationship(
        hour, day, ["dteday"], ["dteday"], "left", "day",
    )
    assert len(joined) == 4
    assert list(joined["day__daily_cnt"]) == [985, 985, 801, 801]
    assert materialized_profile == profile
    assert lineage["day__daily_cnt"]["source_side"] == "right"
    assert lineage["cnt"]["source_side"] == "left"


def test_reversed_one_to_many_relationship_is_rejected_with_swap_guidance():
    from app.relationships import RelationshipValidationError, profile_relationship

    hour, day = bike_frames()
    with pytest.raises(RelationshipValidationError, match="交换左右表"):
        profile_relationship(day, hour, ["dteday"], ["dteday"], "left", "hour")


def test_many_to_many_relationship_is_rejected_before_merge():
    from app.relationships import RelationshipValidationError, profile_relationship

    hour, _ = bike_frames()
    other = pd.DataFrame({"dteday": ["2011-01-01", "2011-01-01"], "value": [1, 2]})
    with pytest.raises(RelationshipValidationError, match="多对多"):
        profile_relationship(hour, other, ["dteday"], ["dteday"], "left", "right")


def test_zero_match_relationship_is_not_applicable():
    from app.relationships import profile_relationship

    hour, day = bike_frames()
    day["dteday"] = ["2012-01-01", "2012-01-02"]
    profile = profile_relationship(hour, day, ["dteday"], ["dteday"], "inner", "day")
    assert profile["safe"] is False
    assert profile["matched_left_rows"] == 0
    assert profile["output_rows"] == 0


def test_null_and_blank_keys_never_match_and_temp_columns_are_preserved():
    from app.relationships import materialize_relationship

    left = pd.DataFrame({"key": ["a", None, "  ", "a"], "__aibi_join_key": [1, 2, 3, 4]})
    right = pd.DataFrame({"key": ["a", None, ""], "value": [10, 99, 88]})
    joined, profile, _ = materialize_relationship(left, right, ["key"], ["key"])
    assert profile["matched_left_rows"] == 2
    assert joined["right__value"].notna().sum() == 2
    assert joined["__aibi_join_key"].tolist() == [1, 2, 3, 4]
    assert len(joined) == profile["output_rows"] == 4
    inner, profile, _ = materialize_relationship(left, right, ["key"], ["key"], "inner")
    assert len(inner) == profile["output_rows"] == 2


def test_composite_null_keys_and_duplicate_key_selection():
    from app.relationships import materialize_relationship, profile_relationship, RelationshipValidationError

    left = pd.DataFrame({"a": [1, 1, 2], "b": ["x", None, "y"]})
    right = pd.DataFrame({"a": [1, 1, 2], "b": ["x", None, "y"], "n": [10, 99, 20]})
    joined, profile, _ = materialize_relationship(left, right, ["a", "b"], ["a", "b"])
    assert profile["matched_left_rows"] == 2
    assert pd.isna(joined.iloc[1]["right__n"])
    with pytest.raises(RelationshipValidationError, match="重复"):
        profile_relationship(left, right, ["a", "a"], ["a", "a"])


def test_deep_analysis_respects_declared_dimensions_and_non_additive_fields():
    from app.capabilities import _catalog, _validate_choice, DiagnosticChoice

    frame = pd.DataFrame({"hr": [0, 1, 2], "season": [1, 1, 2], "cnt": [10, 20, 30],
                          "day__cnt": [60, 60, 60], "code": [1, 2, 3], "instant": [1, 2, 3]})
    catalog = _catalog(frame, {"column_roles": {"code": "dimension", "instant": "id"},
                               "non_additive_columns": ["day__cnt"]})
    assert catalog["measures"] == ["cnt"]
    assert "hr" in catalog["dimensions"]
    with pytest.raises(ValueError):
        _validate_choice(DiagnosticChoice(tool="analysis.correlation", measure="cnt", second_measure="season", reason="test"), catalog)


def test_negated_forecast_is_not_injected_by_keyword_or_model():
    from app.main import _validate_model_plan
    plan = _validate_model_plan({'steps': [{'tool': 'timeseries.forecast'}, {'tool': 'research.inferential'}]},
                                '仅做描述性分析，不做推断统计或预测，生成报告', 'test', 'business')
    assert not {'timeseries.forecast', 'research.inferential'} & {step.tool for step in plan.steps}
    assert 'report.build' in {step.tool for step in plan.steps}


@pytest.mark.parametrize("sql", [
    'SELECT SUM(d."day__cnt") FROM dataset d',
    'SELECT SUM("day__cnt" + 0) FROM dataset',
    'SELECT AVG("day__cnt") FROM dataset',
    'WITH t AS (SELECT "day__cnt" AS x FROM dataset) SELECT SUM(x) FROM t',
    'WITH t AS (SELECT * FROM dataset) SELECT SUM(day__cnt) FROM t',
])
def test_non_additive_aggregation_cannot_hide_behind_alias_or_expression(sql):
    from app.services import validate_non_additive_sql
    with pytest.raises(ValueError, match="原始粒度"):
        validate_non_additive_sql(sql, {"non_additive_columns": ["day__cnt"]})


def test_restrictions_survive_chained_relationship_and_cleaning_rename():
    from app.relationships import inherit_relationship_restrictions, cleaning_semantics
    from app.schemas import CleaningStep
    original = {"non_additive_columns": ["daily"], "column_units": {"daily": "次"}}
    profile = {"non_additive_columns": [], "warnings": [], "right_column_names": {"daily": "r__daily"}}
    inherit_relationship_restrictions(profile, original, original)
    assert profile["non_additive_columns"] == ["daily", "r__daily"]
    result = cleaning_semantics(original, [CleaningStep(operation="rename_column", column="daily", new_name="renamed")], ["renamed"])
    assert result["non_additive_columns"] == ["renamed"]
    assert result["column_units"] == {"renamed": "次"}
    assert original["non_additive_columns"] == ["daily"]


def _upload_csv(client, workspace_id, name, text):
    response = client.post(
        "/api/v1/datasets/upload",
        data={"workspace_id": workspace_id},
        files={"file": (name, text.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_relationship_api_materializes_versioned_copy_and_preserves_sources():
    from app.database import SessionLocal
    from app.models import Dataset
    from app.services import storage_path
    import asyncio
    import hashlib

    day_csv = "dteday,daily_cnt,season\n2011-01-01,56,1\n2011-01-02,67,1\n"
    hour_csv = "instant,dteday,hr,cnt\n1,2011-01-01,0,16\n2,2011-01-01,1,40\n3,2011-01-02,0,32\n4,2011-01-02,1,35\n"
    with TestClient(app) as client:
        workspace = client.post("/api/v1/workspaces/bootstrap").json()
        day = _upload_csv(client, workspace["id"], "day.csv", day_csv)
        hour = _upload_csv(client, workspace["id"], "hour.csv", hour_csv)

        async def source_hashes():
            async with SessionLocal() as session:
                left = await session.get(Dataset, hour["id"])
                right = await session.get(Dataset, day["id"])
                return {
                    left.id: hashlib.sha256(storage_path(left.storage_key).read_bytes()).hexdigest(),
                    right.id: hashlib.sha256(storage_path(right.storage_key).read_bytes()).hexdigest(),
                }

        before = asyncio.run(source_hashes())
        payload = {
            "workspace_id": workspace["id"], "left_dataset_id": hour["id"],
            "right_dataset_id": day["id"], "left_keys": ["dteday"],
            "right_keys": ["dteday"], "join_type": "left", "right_prefix": "day",
        }
        preview = client.post("/api/v1/dataset-relationships/preview", json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["cardinality"] == "many_to_one"
        assert preview.json()["output_rows"] == 4

        blocked = client.post("/api/v1/dataset-relationships", json={**payload, "name": "Bike joined"})
        assert blocked.status_code == 400
        assert "不可求和" in blocked.json()["detail"]

        applied = client.post("/api/v1/dataset-relationships", json={
            **payload, "name": "Bike joined", "acknowledge_non_additive": True,
        })
        assert applied.status_code == 201, applied.text
        relation = applied.json()
        result = relation["result_dataset"]
        assert result["profile"]["row_count"] == 4
        assert result["current_version_id"]
        assert result["semantics"]["grain"] == "左表明细粒度"
        assert result["semantics"]["non_additive_columns"] == ["day__daily_cnt", "day__season"]
        assert set(result["semantics"]["source_dataset_version_ids"]) == {
            relation["left_version_id"], relation["right_version_id"],
        }
        rows = client.get(
            f"/api/v1/datasets/{result['id']}/preview",
            params={"workspace_id": workspace["id"], "limit": 10},
        ).json()["rows"]
        assert [row["day__daily_cnt"] for row in rows] == [56, 56, 67, 67]

        semantic_update = client.patch(f"/api/v1/datasets/{result['id']}/semantics", json={
            "workspace_id": workspace["id"], "unit": "次", "grain": "每小时一行",
            "date_formats": {"dteday": "%Y-%m-%d"},
            "column_roles": {"instant": "id", "dteday": "date", "cnt": "measure"},
            "column_units": {"cnt": "次"},
        })
        assert semantic_update.status_code == 200, semantic_update.text
        assert semantic_update.json()["semantics"]["grain"] == "每小时一行"
        assert semantic_update.json()["semantics"]["relationship_id"] == relation["id"]
        assert semantic_update.json()["current_version_id"] != result["current_version_id"]
        from app.models import DatasetVersion
        async def version_semantics():
            async with SessionLocal() as session:
                old = await session.get(DatasetVersion, result["current_version_id"])
                new = await session.get(DatasetVersion, semantic_update.json()["current_version_id"])
                return old.profile["semantics"], new.profile["semantics"], old.content_hash == new.content_hash
        old, new, same_file = asyncio.run(version_semantics())
        assert old["grain"] == "左表明细粒度"
        assert new["grain"] == "每小时一行"
        assert same_file

        unsafe_sql = client.post(f"/api/v1/datasets/{result['id']}/sql", json={
            "workspace_id": workspace["id"], "sql": 'SELECT SUM("day__daily_cnt") FROM dataset',
        })
        assert unsafe_sql.status_code == 400
        assert "禁止直接 SUM" in unsafe_sql.json()["detail"]

        report_response = client.post("/api/v1/analysis/run", json={
            "workspace_id": workspace["id"], "dataset_id": result["id"],
            "prompt": "分析共享单车小时需求并生成报告",
        })
        assert report_response.status_code == 200, report_response.text
        document = report_response.json()["document"]
        assert any(item["id"] == "dataset-relationship" for item in document["evidence"])
        quantity = next(item for item in document["evidence"] if item["id"] == "metric-quantity")
        assert quantity["source_columns"] == ["cnt"]
        assert quantity["calculation"]["result"] == 123
        assert all("SUM(day__daily_cnt)" not in (item.get("method") or "") for item in document["evidence"])
        assert any(chart["id"] == "primary-trend" for chart in document["charts"])
        assert asyncio.run(source_hashes()) == before

        listed = client.get("/api/v1/dataset-relationships", params={
            "workspace_id": workspace["id"],
        })
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [relation["id"]]
