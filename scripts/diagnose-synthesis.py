"""One paid synthesis-only replay; saves response and accounts usage without modifying a report."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select
from app.database import SessionLocal
from app.models import ProviderConfig
from app.main import enforce_llm_budget, usage_log
from app.llm import complete
from app.prompting import synthesis_context, synthesis_prompt, validate_synthesis, parse_json_object


async def main():
    source = Path(sys.argv[1])
    result = json.loads(source.read_text(encoding="utf-8"))
    meta = result["assistant_message"]["message_meta"]
    import httpx
    with httpx.Client(base_url="http://127.0.0.1:8010") as client:
        workspace = client.post("/api/v1/workspaces/bootstrap").json()["id"]
    async with SessionLocal() as session:
        provider = await session.scalar(select(ProviderConfig).where(ProviderConfig.workspace_id == workspace, ProviderConfig.provider == "deepseek", ProviderConfig.enabled.is_(True)))
        await enforce_llm_budget(session, workspace)
        completion = await complete(provider, [{"role": "user", "content": synthesis_prompt()}],
            synthesis_context(objective="总结共享单车需求分析，区分事实、解释、建议。", evidence=meta["evidence"], report_id=result["report_id"], dashboard_url=None),
            request_options={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "max_tokens": 1800})
        session.add(usage_log(workspace, None, None, provider, completion, stage="synthesis", purpose="validation:synthesis-replay"))
        await session.commit()
    record = {"content": completion.content, "usage": completion.as_meta()}
    try:
        record["validated"] = validate_synthesis(parse_json_object(completion.content), meta["evidence"]).model_dump(mode="json")
    except ValueError as exc:
        record["error"] = str(exc)
    output = source.parent / "synthesis-replay.json"
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
