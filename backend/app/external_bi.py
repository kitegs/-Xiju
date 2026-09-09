from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import create_engine

from .config import (
    CUBE_API_TOKEN, CUBE_API_URL, CURATED_DATABASE_URL, SUPERSET_CURATED_DATABASE_URI,
    SUPERSET_PASSWORD, SUPERSET_URL, SUPERSET_USERNAME,
)


async def probe(url: str, path: str, headers: dict | None = None) -> dict:
    if not url:
        return {"configured": False, "reachable": False, "latency_ms": None, "error": "未配置"}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, trust_env=False) as client:
            response = await client.get(url.rstrip("/") + path, headers=headers)
        return {"configured": True, "reachable": response.status_code < 500, "status_code": response.status_code, "latency_ms": round((time.perf_counter() - started) * 1000), "error": None if response.status_code < 500 else "服务端错误"}
    except Exception as exc:
        return {"configured": True, "reachable": False, "latency_ms": round((time.perf_counter() - started) * 1000), "error": str(exc)[:180]}


async def integration_status() -> dict:
    cube_headers = {"Authorization": CUBE_API_TOKEN} if CUBE_API_TOKEN else None
    superset, cube = await asyncio.gather(
        probe(SUPERSET_URL, "/health"), probe(CUBE_API_URL, "/meta", cube_headers),
    )
    return {
        "superset": {
            **superset, "url": SUPERSET_URL or None, "purpose": "专业图表、仪表盘与人工深度编辑",
            "guest_token_ready": bool(SUPERSET_USERNAME and SUPERSET_PASSWORD),
            "publisher_ready": bool(CURATED_DATABASE_URL and SUPERSET_CURATED_DATABASE_URI),
        },
        "cube": {**cube, "url": CUBE_API_URL or None, "purpose": "语义层、指标治理与行级权限", "token_ready": bool(CUBE_API_TOKEN)},
        "note": "健康状态来自实时探测；密钥只保留在后端。",
    }


async def superset_guest_token(dashboard_id: str, username: str, rls: list[dict] | None = None) -> str:
    if not SUPERSET_URL or not SUPERSET_USERNAME or not SUPERSET_PASSWORD:
        raise HTTPException(503, "Superset 管理服务账号尚未配置")
    async with httpx.AsyncClient(timeout=12.0, trust_env=False) as client:
        login = await client.post(SUPERSET_URL.rstrip("/") + "/api/v1/security/login", json={
            "username": SUPERSET_USERNAME, "password": SUPERSET_PASSWORD, "provider": "db", "refresh": True,
        })
        if login.status_code >= 400:
            raise HTTPException(502, "Superset 服务账号登录失败")
        access = login.json().get("access_token")
        auth = {"Authorization": f"Bearer {access}"}
        csrf = await client.get(SUPERSET_URL.rstrip("/") + "/api/v1/security/csrf_token/", headers=auth)
        response = await client.post(
            SUPERSET_URL.rstrip("/") + "/api/v1/security/guest_token/",
            headers={**auth, "X-CSRFToken": csrf.json().get("result", ""), "Referer": SUPERSET_URL.rstrip("/") + "/"},
            json={"user": {"username": username, "first_name": username, "last_name": "Insight"}, "resources": [{"type": "dashboard", "id": dashboard_id}], "rls": rls or []},
        )
    if response.status_code >= 400:
        detail = response.text.replace("\n", " ")[:300]
        raise HTTPException(502, f"Superset Guest Token 签发失败（{response.status_code}）：{detail}")
    token = response.json().get("token")
    if not token: raise HTTPException(502, "Superset 未返回 Guest Token")
    return token


async def create_embedded_dashboard(title: str, allowed_domains: list[str]) -> dict:
    if not SUPERSET_URL or not SUPERSET_USERNAME or not SUPERSET_PASSWORD:
        raise HTTPException(503, "Superset 管理服务账号尚未配置")
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        login = await client.post(SUPERSET_URL.rstrip("/") + "/api/v1/security/login", json={"username": SUPERSET_USERNAME, "password": SUPERSET_PASSWORD, "provider": "db", "refresh": True})
        if login.status_code >= 400: raise HTTPException(502, "Superset 服务账号登录失败")
        auth = {"Authorization": f"Bearer {login.json().get('access_token')}"}
        csrf = await client.get(SUPERSET_URL.rstrip("/") + "/api/v1/security/csrf_token/", headers=auth)
        headers = {**auth, "X-CSRFToken": csrf.json().get("result", ""), "Referer": SUPERSET_URL.rstrip("/") + "/"}
        created = await client.post(SUPERSET_URL.rstrip("/") + "/api/v1/dashboard/", headers=headers, json={"dashboard_title": title, "published": True})
        if created.status_code >= 400: raise HTTPException(502, f"Superset 看板创建失败（{created.status_code}）")
        dashboard_id = created.json().get("id") or created.json().get("result", {}).get("id")
        embedded = await client.post(SUPERSET_URL.rstrip("/") + f"/api/v1/dashboard/{dashboard_id}/embedded", headers=headers, json={"allowed_domains": normalize_embedded_domains(allowed_domains)})
        if embedded.status_code >= 400: raise HTTPException(502, f"Superset Embedded Dashboard 启用失败（{embedded.status_code}）")
        result = embedded.json().get("result", embedded.json())
        return {"dashboard_id": dashboard_id, "embedded_id": result.get("uuid") or result.get("id"), "title": title}


CURATED_DATABASE_NAME = "Insight Studio Curated"

LOCAL_EMBEDDED_ORIGINS = tuple(
    f"{host}:{port}"
    for host in ("http://localhost", "http://127.0.0.1")
    for port in range(5173, 5191)
)


def normalize_embedded_domains(domains: list[str] | None = None) -> list[str]:
    """Keep local launch-port changes from breaking an already published embed."""
    requested = [str(item).strip().rstrip("/") for item in (domains or [])]
    allowed = [*LOCAL_EMBEDDED_ORIGINS, *requested]
    valid = [item for item in allowed if re.fullmatch(r"https?://(?:localhost|127\.0\.0\.1)(?::\d{2,5})?", item)]
    return list(dict.fromkeys(valid))


class SupersetApi:
    def __init__(self) -> None:
        if not SUPERSET_URL or not SUPERSET_USERNAME or not SUPERSET_PASSWORD:
            raise HTTPException(503, "Superset 管理服务账号尚未配置")
        self.client = httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=True)
        self.base_url = SUPERSET_URL.rstrip("/")
        self.headers: dict[str, str] = {}

    async def __aenter__(self):
        login = await self.client.post(self.base_url + "/api/v1/security/login", json={
            "username": SUPERSET_USERNAME, "password": SUPERSET_PASSWORD, "provider": "db", "refresh": True,
        })
        self._raise(login, "服务账号登录")
        self.headers = {"Authorization": f"Bearer {login.json().get('access_token')}"}
        csrf = await self.client.get(self.base_url + "/api/v1/security/csrf_token/", headers=self.headers)
        self._raise(csrf, "CSRF Token 获取")
        self.headers.update({"X-CSRFToken": csrf.json().get("result", ""), "Referer": self.base_url + "/"})
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    @staticmethod
    def _raise(response: httpx.Response, action: str) -> None:
        if response.status_code >= 400:
            detail = response.text.replace("\n", " ")[:500]
            raise HTTPException(502, f"Superset {action}失败（{response.status_code}）：{detail}")

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        response = await self.client.request(method, self.base_url + path, headers=self.headers, json=payload)
        self._raise(response, path)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def list(self, resource: str, page_size: int = 100) -> list[dict]:
        response = await self.request("GET", f"/api/v1/{resource}/?q=(page:0,page_size:{page_size})")
        return response.get("result") or []


async def repair_embedded_dashboard(dashboard_id: int, allowed_domains: list[str] | None = None) -> dict:
    """Upsert an existing dashboard's embed configuration and local origins."""
    domains = normalize_embedded_domains(allowed_domains)
    async with SupersetApi() as api:
        response = await api.request(
            "PUT", f"/api/v1/dashboard/{dashboard_id}/embedded",
            {"allowed_domains": domains},
        )
    result = response.get("result", response)
    return {
        "dashboard_id": dashboard_id,
        "embedded_id": str(result.get("uuid") or result.get("id") or ""),
        "allowed_domains": domains,
    }


def _safe_table_name(dataset_id: str) -> str:
    return "dataset_" + re.sub(r"[^a-zA-Z0-9]", "", dataset_id)[:32].lower()


def _write_curated_database(frame: pd.DataFrame, table_name: str) -> None:
    if not CURATED_DATABASE_URL:
        raise HTTPException(503, "专业分析数据库尚未配置，请重新运行 start-professional.bat")
    engine = create_engine(CURATED_DATABASE_URL, pool_pre_ping=True)
    try:
        frame.to_sql(table_name, engine, if_exists="replace", index=False, chunksize=1000)
    finally:
        engine.dispose()


def prepare_curated_dataset(frame: pd.DataFrame, dataset_id: str) -> str:
    """Write a replaceable copy for Superset; the imported original stays untouched."""
    table_name = _safe_table_name(dataset_id)
    _write_curated_database(frame, table_name)
    return table_name


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def _sql_metric(column: str, aggregate: str | None, label: str | None = None) -> dict:
    aggregate_name = {"avg": "AVG", "count": "COUNT", "min": "MIN", "max": "MAX"}.get(aggregate or "sum", "SUM")
    expression = f"{aggregate_name}({_quote_identifier(column)})"
    return {
        "expressionType": "SQL", "sqlExpression": expression,
        "label": label or f"{aggregate_name}({column})", "optionName": f"metric_{abs(hash(expression))}",
    }


def chart_to_superset_params(chart: dict, superset_dataset_id: int) -> tuple[str, dict]:
    chart_type = chart.get("chart_type") or "table"
    x_column = (chart.get("x") or {}).get("column")
    y = chart.get("y") or {}
    series = chart.get("series") or ([y] if y else [])
    metrics = [_sql_metric(item["column"], item.get("aggregate"), item.get("column")) for item in series if item.get("column")]
    base = {
        "datasource": f"{superset_dataset_id}__table", "adhoc_filters": [], "row_limit": 1000,
        "time_range": "No filter", "show_legend": bool((chart.get("style") or {}).get("show_legend", True)),
        "color_scheme": "supersetColors", "show_value": bool((chart.get("style") or {}).get("show_labels", False)),
    }
    if chart_type == "kpi":
        if "利润率" in str(chart.get("title")) and chart.get("data"):
            value = chart["data"][0].get("value")
            metric = {"expressionType": "SQL", "sqlExpression": str(float(value or 0)), "label": chart.get("title"), "optionName": f"metric_{chart.get('id')}"}
        else:
            metric = metrics[0] if metrics else _sql_metric(y.get("column", "*"), y.get("aggregate"), chart.get("title"))
        return "big_number_total", {**base, "viz_type": "big_number_total", "metric": metric, "y_axis_format": "SMART_NUMBER", "header_font_size": 0.4}
    if chart_type in {"pie", "donut", "treemap"}:
        return "pie", {**base, "viz_type": "pie", "groupby": [x_column] if x_column else [], "metric": metrics[0] if metrics else None, "donut": chart_type == "donut", "show_labels": True}
    if chart_type in {"scatter", "bubble"}:
        scatter_metric = _sql_metric(y.get("column"), y.get("aggregate") or "avg", y.get("column"))
        return "echarts_timeseries_scatter", {
            **base, "viz_type": "echarts_timeseries_scatter", "x_axis": x_column,
            "metrics": [scatter_metric], "groupby": [], "markerSize": 7,
            "rich_tooltip": True, "only_total": True, "row_limit": 10000,
        }
    if chart_type in {"table", "highlight_table", "heatmap"}:
        return "table", {**base, "viz_type": "table", "groupby": [x_column] if x_column else [], "metrics": metrics, "include_search": True, "order_desc": True}
    viz_type = "echarts_timeseries_line" if chart_type in {"line", "area"} else "echarts_timeseries_bar"
    return viz_type, {
        **base, "viz_type": viz_type, "x_axis": x_column, "metrics": metrics,
        "groupby": [], "order_desc": True, "stack": "Stack" if chart_type == "area" else None,
        "show_legend": len(metrics) > 1, "truncate_metric": True,
    }


def dashboard_position(charts: list[dict]) -> str:
    position: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "GRID_ID": {"id": "GRID_ID", "type": "GRID", "parents": ["ROOT_ID"], "children": []},
    }
    for row_index in range(0, len(charts), 2):
        row_id = f"ROW-{row_index // 2 + 1}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {"id": row_id, "type": "ROW", "parents": ["ROOT_ID", "GRID_ID"], "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for chart in charts[row_index:row_index + 2]:
            chart_id = int(chart["id"])
            node_id = f"CHART-{chart_id}"
            position[row_id]["children"].append(node_id)
            position[node_id] = {
                "id": node_id, "type": "CHART", "parents": ["ROOT_ID", "GRID_ID", row_id], "children": [],
                "meta": {"chartId": chart_id, "height": 48, "width": 6, "sliceName": chart["title"], **({"uuid": chart["uuid"]} if chart.get("uuid") else {})},
            }
    return json.dumps(position, ensure_ascii=False)


async def publish_superset_dashboard(
    *, frame: pd.DataFrame, local_dataset_id: str, dataset_name: str, charts: list[dict], title: str,
    allowed_domains: list[str], dashboard_id: int | None = None, embedded_id: str | None = None,
) -> dict:
    if not SUPERSET_CURATED_DATABASE_URI:
        raise HTTPException(503, "Superset 专业分析数据库连接尚未配置，请重新运行 start-professional.bat")
    table_name = await asyncio.to_thread(prepare_curated_dataset, frame, local_dataset_id)
    suffix = local_dataset_id.replace("-", "")[:8]
    async with SupersetApi() as api:
        databases = await api.list("database")
        database = next((item for item in databases if item.get("database_name") == CURATED_DATABASE_NAME), None)
        if not database:
            created = await api.request("POST", "/api/v1/database/", {
                "database_name": CURATED_DATABASE_NAME, "sqlalchemy_uri": SUPERSET_CURATED_DATABASE_URI,
                "expose_in_sqllab": True, "allow_run_async": False, "allow_file_upload": False,
                "allow_ctas": False, "allow_cvas": False, "allow_dml": False,
                "extra": json.dumps({}),
            })
            database_id = int(created.get("id") or created.get("result", {}).get("id"))
        else:
            database_id = int(database["id"])

        datasets = await api.list("dataset")
        superset_dataset = next((item for item in datasets if item.get("table_name") == table_name and int(item.get("database", {}).get("id") or item.get("database", 0)) == database_id), None)
        if not superset_dataset:
            created = await api.request("POST", "/api/v1/dataset/", {"database": database_id, "schema": None, "table_name": table_name})
            superset_dataset_id = int(created.get("id") or created.get("result", {}).get("id"))
        else:
            superset_dataset_id = int(superset_dataset["id"])

        dashboard_title = f"{title} [{suffix}]"
        if not dashboard_id:
            dashboards = await api.list("dashboard")
            dashboard = next((item for item in dashboards if item.get("dashboard_title") == dashboard_title), None)
            if dashboard:
                dashboard_id = int(dashboard["id"])
            else:
                created = await api.request("POST", "/api/v1/dashboard/", {"dashboard_title": dashboard_title, "published": True})
                dashboard_id = int(created.get("id") or created.get("result", {}).get("id"))
        else:
            await api.request("PUT", f"/api/v1/dashboard/{dashboard_id}", {"dashboard_title": dashboard_title, "published": True})

        existing_charts = await api.list("chart", page_size=500)
        published_charts: list[dict] = []
        for index, chart in enumerate(charts[:10]):
            chart_title = f"{chart.get('title') or f'图表 {index + 1}'} [{suffix}]"
            existing = next((item for item in existing_charts if item.get("slice_name") == chart_title), None)
            viz_type, params = chart_to_superset_params(chart, superset_dataset_id)
            payload = {
                "slice_name": chart_title, "description": chart.get("description") or "由 Insight Studio 证据化分析生成",
                "viz_type": viz_type, "datasource_id": superset_dataset_id, "datasource_type": "table",
                "params": json.dumps(params, ensure_ascii=False), "dashboards": [dashboard_id],
            }
            if existing:
                chart_id = int(existing["id"])
                await api.request("PUT", f"/api/v1/chart/{chart_id}", payload)
                chart_uuid = existing.get("uuid")
            else:
                created = await api.request("POST", "/api/v1/chart/", payload)
                result = created.get("result", created)
                chart_id = int(created.get("id") or result.get("id"))
                chart_uuid = result.get("uuid")
            published_charts.append({"id": chart_id, "uuid": chart_uuid, "title": chart_title, "chart_spec_id": chart.get("id"), "viz_type": viz_type})

        await api.request("PUT", f"/api/v1/dashboard/{dashboard_id}", {
            "dashboard_title": dashboard_title, "published": True, "position_json": dashboard_position(published_charts),
            "json_metadata": json.dumps({"timed_refresh_immune_slices": [], "expanded_slices": {}, "refresh_frequency": 0}),
        })
        # Superset POST/PUT both upsert. Always refresh this configuration:
        # start.bat may pick a different Vite port on a later launch.
        embedded = await api.request(
            "PUT", f"/api/v1/dashboard/{dashboard_id}/embedded",
            {"allowed_domains": normalize_embedded_domains(allowed_domains)},
        )
        result = embedded.get("result", embedded)
        embedded_id = str(result.get("uuid") or result.get("id") or embedded_id or "")
    return {
        "database_id": database_id, "superset_dataset_id": superset_dataset_id, "dashboard_id": dashboard_id,
        "embedded_id": embedded_id, "title": dashboard_title, "charts": published_charts,
        "dashboard_url": f"{SUPERSET_URL.rstrip('/')}/superset/dashboard/{dashboard_id}/",
        "table_name": table_name, "dataset_name": dataset_name,
    }
