from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExecutionMode = Literal["safe", "partial", "full"]
Decision = Literal["allow", "approval", "forbid"]


@dataclass(frozen=True)
class ToolDecision:
    tool: str
    decision: Decision
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"tool": self.tool, "decision": self.decision, "reason": self.reason}


ALWAYS_ALLOWED = {
    'data.reconcile',
    "dataset.profile", "data.quality", "statistics.describe", "research.inferential",
    "survey.profile", "survey.cross_analysis", "cleaning.recommend", "timeseries.forecast",
    "action.recommend", "report.build", "report.template.fill", "assistant.synthesize",
    "chart.context", "chart.propose", "chart.preview",
    "analysis.deepen", "report.review", "report.layout", "report.alternatives",
}
KNOWN_TOOLS = ALWAYS_ALLOWED | {"sql.query", "python.run", "data.clean.apply", "mcp.call", "superset.publish"}


def decide_tool(mode: ExecutionMode, tool: str) -> ToolDecision:
    if tool not in KNOWN_TOOLS:
        return ToolDecision(tool, "forbid", "工具未在服务端策略注册表中")
    if tool in ALWAYS_ALLOWED:
        return ToolDecision(tool, "allow", "只读或生成本地可审阅草稿")
    if tool == "sql.query":
        return ToolDecision(tool, "approval" if mode == "safe" else "allow", "仅允许数据副本上的 SELECT/WITH")
    if tool == "python.run":
        if mode == "safe":
            return ToolDecision(tool, "forbid", "安全模式禁止模型生成代码")
        return ToolDecision(tool, "approval" if mode == "partial" else "allow", "仅在无网络、只读数据挂载的沙箱执行")
    if tool == "data.clean.apply":
        if mode == "safe":
            return ToolDecision(tool, "forbid", "安全模式只允许清洗预览和建议")
        return ToolDecision(tool, "approval" if mode == "partial" else "allow", "只能生成新的数据版本")
    if tool == "mcp.call":
        if mode == "safe":
            return ToolDecision(tool, "forbid", "安全模式禁止外部 MCP 调用")
        return ToolDecision(tool, "approval" if mode == "partial" else "allow", "仍受服务端和工具白名单约束")
    if tool == "superset.publish":
        if mode == "safe":
            return ToolDecision(tool, "forbid", "安全模式禁止外部发布")
        return ToolDecision(tool, "approval", "外部发布在任何模式下都必须单独批准")
    return ToolDecision(tool, "forbid", "未匹配到允许策略")


def evaluate_tools(mode: ExecutionMode, tools: list[str]) -> list[ToolDecision]:
    return [decide_tool(mode, tool) for tool in tools]


class ToolPolicyError(PermissionError):
    pass


def enforce_tools(mode: ExecutionMode, tools: list[str], *, approved: bool) -> list[ToolDecision]:
    decisions = evaluate_tools(mode, tools)
    forbidden = [item.tool for item in decisions if item.decision == "forbid"]
    if forbidden:
        raise ToolPolicyError(f"{mode} 模式禁止执行：{', '.join(forbidden)}")
    pending = [item.tool for item in decisions if item.decision == "approval"]
    if pending and not approved:
        raise ToolPolicyError(f"以下工具需要用户批准：{', '.join(pending)}")
    return decisions
