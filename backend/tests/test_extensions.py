import pytest
from app.schemas import ReportDocument


def test_builtin_layout_registry_is_explicit_and_disable_prevents_mutation():
    from app.extensions import execute_builtin, manifests
    doc = ReportDocument(title='扩展测试', summary='', blocks=[], charts=[], evidence=[])
    before = doc.model_dump()
    with pytest.raises(PermissionError): execute_builtin('report.layout', doc, enabled=False)
    assert doc.model_dump() == before
    with pytest.raises(KeyError): execute_builtin('third-party', doc, enabled=True)
    result = execute_builtin('report.layout', doc, enabled=True)
    assert result['extension']['id']=='builtin.report-layout'
    assert result['extension']['version']=='1.0.0'
    assert manifests()[0]['trust']=='builtin'


def test_extension_failure_does_not_mutate_draft(monkeypatch):
    from app import extensions
    manifest, _ = extensions._REGISTRY['report.layout']
    def broken(candidate):
        candidate.title = 'partial unwanted mutation'
        raise RuntimeError('injected handler failure')
    monkeypatch.setitem(extensions._REGISTRY, 'report.layout', (manifest, broken))
    doc = ReportDocument(title='保持原稿', summary='', blocks=[], charts=[], evidence=[])
    with pytest.raises(RuntimeError):
        extensions.execute_builtin('report.layout', doc, enabled=True)
    assert doc.title == '保持原稿'
