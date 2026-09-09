from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import AnalysisBrief, AnalysisBriefUpdate, ClarificationMode, IntakeDecision, IntakeQuestion, ReportBlock, ReportDocument


SKILL_VERSION = "analysis-intake-v1"
DEFAULT_QUESTIONS = [
    {"question_key": "audience", "prompt": "这份分析主要给谁看？", "recommended_default": "业务负责人", "reason": "受众决定解释深度和措辞。", "affects": ["报告语气", "摘要层级"]},
    {"question_key": "decision", "prompt": "你希望这份分析帮助做什么决定？", "recommended_default": "识别趋势、结构与异常，并给出可验证建议", "reason": "决策目标决定分析重点。", "affects": ["分析计划", "建议"]},
    {"question_key": "time_range", "prompt": "需要分析哪个时间范围？", "recommended_default": "使用数据中全部可靠时间范围", "reason": "时间范围会改变聚合结果。", "affects": ["趋势", "筛选"]},
    {"question_key": "comparison", "prompt": "需要与什么基准比较？", "recommended_default": "与上一可靠周期及总体平均比较", "reason": "比较基准决定变化的解释方式。", "affects": ["同比环比", "异常判断"]},
    {"question_key": "metric_definition", "prompt": "是否有必须遵循的指标口径？", "recommended_default": "使用原字段名和本地聚合口径", "reason": "指标口径必须可复核。", "affects": ["计算", "证据"]},
    {"question_key": "unit_currency", "prompt": "数值的单位或币种是什么？", "recommended_default": "沿用数据源单位，未知时明确标注", "reason": "单位缺失会导致错误解读。", "affects": ["图表单位", "报告说明"]},
    {"question_key": "targets", "prompt": "是否有目标值、预算或预警线？", "recommended_default": "无已确认目标值，仅做描述性比较", "reason": "未确认目标不能作为达标判断依据。", "affects": ["参考线", "行动建议"]},
    {"question_key": "output", "prompt": "希望最终产出什么形式？", "recommended_default": "可编辑专业报告", "reason": "输出形式影响内容结构。", "affects": ["报告", "看板"]},
]
DEFAULT_SKILL = {
    "version": SKILL_VERSION,
    "triggers": ["生成报告", "经营报告", "管理层报告", "商业报告", "研究报告", "问卷报告", "创建看板", "生成看板", "复杂分析", "新业务目标", "dashboard", "report"],
    "questions": DEFAULT_QUESTIONS,
}


def load_intake_skill() -> dict[str, Any]:
    try:
        raw = json.loads((Path(__file__).with_name("skills") / "analysis-intake.json").read_text(encoding="utf-8"))
        questions = [IntakeQuestion.model_validate(item).model_dump() for item in raw["questions"]]
        if raw.get("version") != SKILL_VERSION or len(questions) > 8:
            raise ValueError("invalid analysis-intake skill")
        return {"version": raw["version"], "triggers": list(raw.get("triggers") or []), "questions": questions}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return DEFAULT_SKILL


def objective_fingerprint(message: str, profile: dict[str, Any]) -> str:
    normalized = re.sub(r"\s+", " ", message.strip().casefold())
    fields = sorted(str(item.get("name", "")) for item in profile.get("columns", []) if isinstance(item, dict))
    return hashlib.sha256(f"{normalized}|{'|'.join(fields)}".encode("utf-8")).hexdigest()


def evaluate_intake(
    message: str,
    profile: dict[str, Any],
    brief: AnalysisBrief,
    mode: ClarificationMode,
) -> IntakeDecision:
    skill = load_intake_skill()
    fingerprint = objective_fingerprint(message, profile)
    if mode == "off":
        return IntakeDecision(mode=mode, should_pause=False, status="disabled", objective_fingerprint=fingerprint)
    triggered = mode == "always" or any(term.casefold() in message.casefold() for term in skill["triggers"])
    if not triggered:
        return IntakeDecision(mode=mode, should_pause=False, status="not_needed", objective_fingerprint=fingerprint)
    resolved = {key for key, value in brief.answers.items() if str(value).strip()}
    questions = [IntakeQuestion.model_validate(item) for item in skill["questions"] if item["question_key"] not in resolved][:8]
    return IntakeDecision(
        mode=mode, should_pause=bool(questions), status="pending" if questions else "completed",
        questions=questions, defaults={item.question_key: item.recommended_default for item in questions},
        objective_fingerprint=fingerprint, skill_version=skill["version"],
    )


def apply_brief_update(
    brief: AnalysisBrief,
    update: AnalysisBriefUpdate,
    decision: IntakeDecision,
) -> AnalysisBrief:
    answers = dict(brief.answers)
    confirmed = set(brief.confirmed_keys)
    defaulted = set(brief.defaulted_keys)
    allowed = {item["question_key"] for item in load_intake_skill()["questions"]}
    for key, value in update.answers.items():
        if key not in allowed:
            continue
        cleaned = str(value).strip()
        if cleaned:
            answers[key] = cleaned
            confirmed.add(key)
            defaulted.discard(key)
    if update.use_recommended_defaults:
        for question in decision.questions:
            if question.question_key not in answers:
                answers[question.question_key] = question.recommended_default
                defaulted.add(question.question_key)
    asked = set(brief.asked_keys) | {item.question_key for item in decision.questions}
    return AnalysisBrief(
        answers=answers, confirmed_keys=sorted(confirmed), defaulted_keys=sorted(defaulted),
        asked_keys=sorted(asked), skill_version=decision.skill_version,
        objective_fingerprint=decision.objective_fingerprint,
        request_summary=update.objective.strip().replace("\n", " ")[:240],
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def apply_brief_to_report(document: ReportDocument, brief: AnalysisBrief) -> ReportDocument:
    document.metadata["analysis_brief"] = {
        "answers": brief.answers,
        "confirmed_keys": brief.confirmed_keys,
        "defaulted_keys": brief.defaulted_keys,
        "skill_version": brief.skill_version,
    }
    assumptions = [f"{key}：{brief.answers[key]}" for key in brief.defaulted_keys if brief.answers.get(key)]
    document.metadata["unconfirmed_assumptions"] = assumptions
    document.blocks = [block for block in document.blocks if block.id != "unconfirmed-assumptions"]
    if assumptions:
        document.blocks.insert(1, ReportBlock(
            id="unconfirmed-assumptions", kind="callout",
            content="未经确认的业务假设：" + "；".join(assumptions) + "。这些假设可在分析简报中修改后重新生成。",
            style={"tone": "warning"},
        ))
    return document
