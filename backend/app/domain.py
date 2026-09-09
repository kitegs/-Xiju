"""Small framework-independent contracts shared by local execution modules."""
from typing import Protocol

TERMINAL_RUN_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})
RUN_TRANSITIONS = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled", "interrupted"}),
}


class StatefulRun(Protocol):
    status: str


def transition_run(run: StatefulRun, target: str) -> None:
    if target not in RUN_TRANSITIONS.get(run.status, frozenset()):
        raise ValueError(f"非法 Run 状态转换：{run.status} → {target}；重试必须创建新 Run")
    run.status = target


def reserved_capabilities() -> list[dict]:
    """Discovery metadata only: not an executable tool or a permission grant."""
    return [{"id": "python.visualize", "label": "Python 专业绘图", "available": False,
             "default_enabled": False, "reason": "预留组件，尚未实现或开放",
             "contract_version": "capability-v1", "required_tool": "python.run"}]


def validate_execution_snapshot(saved_spec: dict, current_spec: dict, pinned_versions: list[str], current_version: str | None) -> None:
    """Reject silent plan/data drift; an explicit new plan is safer than rebinding a queued run."""
    saved = {key: value for key, value in saved_spec.items() if key != "status"}
    current = {key: value for key, value in current_spec.items() if key != "status"}
    # Compatibility for plans queued before requirements became an explicit field.
    if saved and 'report_requirements' not in saved and 'report_requirements' in current:
        from .schemas import ReportRequirements
        saved['report_requirements'] = ReportRequirements().model_dump(mode='json')
    if saved and saved != current:
        raise ValueError("排队后的分析计划已变化，请重新生成并确认计划")
    if current_version and pinned_versions and current_version != pinned_versions[0]:
        raise ValueError("排队后的数据版本或口径已变化，请重新生成并确认计划")
