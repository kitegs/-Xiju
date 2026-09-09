"""Trusted built-in extension registry, not a third-party code loader.

Caller must enforce tool policy before entry and persist through normal report
versioning afterwards. A manifest is descriptive, never a security sandbox.
"""
from dataclasses import asdict, dataclass
from typing import Callable

from .schemas import ReportDocument


@dataclass(frozen=True)
class ExtensionManifest:
    id: str
    version: str
    tool: str
    capability: str
    contract_version: str = '1'
    trust: str = 'builtin'
    network: bool = False
    effect: str = 'modify-new-report-draft'


def _layout(document):
    from .capabilities import optimize_layout
    return optimize_layout(document)


_REGISTRY: dict[str, tuple[ExtensionManifest, Callable]] = {
    'report.layout': (ExtensionManifest('builtin.report-layout', '1.0.0', 'report.layout', 'chart_layout'), _layout),
}


def manifests() -> list[dict]:
    return [asdict(manifest) for manifest, _ in _REGISTRY.values()]


def execute_builtin(tool: str, document: ReportDocument, *, enabled: bool) -> dict:
    if tool not in _REGISTRY:
        raise KeyError(f'未注册的内置扩展：{tool}')
    if not enabled:
        raise PermissionError(f'分析能力未启用：{tool}')
    if not isinstance(document, ReportDocument):
        raise TypeError('扩展只接受经过验证的 ReportDocument')
    manifest, handler = _REGISTRY[tool]
    # Work on a copy so a failing handler cannot partially change the draft.
    candidate = document.model_copy(deep=True)
    details = handler(candidate)
    validated = ReportDocument.model_validate(candidate.model_dump(mode='json'))
    for field in type(document).model_fields:
        setattr(document, field, getattr(validated, field))
    return {**details, 'extension': asdict(manifest)}
