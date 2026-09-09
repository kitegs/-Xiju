from copy import deepcopy

import pandas as pd
import pytest

from app.fact_catalog import fact_catalog, validate_fact_summary
from app.report_requirements import compose_report, resolve_requirements
from app.services import build_report, profile_dataframe


def specimen():
    frame = pd.DataFrame({'Sales': [100, 200, 300], 'Profit': [-10, 40, -20],
                          'Region': ['East', 'West', 'East'],
                          'Order Date': ['2025-01-01', '2025-02-01', '2025-03-01']})
    return frame, build_report(frame, profile_dataframe(frame), 'Golden', '生成报告')


def test_same_data_different_depth_preserves_facts():
    frame, base = specimen()
    assert not any(c.x and c.x.column == 'Profit' for c in base.charts)
    brief = compose_report(deepcopy(base), frame, resolve_requirements('老板简报'))
    detailed = compose_report(deepcopy(base), frame, resolve_requirements('详细分析'))
    assert len(brief.blocks) < len(detailed.blocks)
    assert brief.evidence == detailed.evidence
    assert brief.metadata['appendix_visible'] is False
    assert detailed.metadata['appendix_visible'] is True
    assert brief.title != detailed.title


def test_loss_is_not_net_profit_and_exclusions_apply():
    frame, base = specimen()
    report = compose_report(base, frame, resolve_requirements('只分析亏损，不要趋势，不要预测'))
    evidence = {e.id: e for e in report.evidence}
    assert evidence['loss-amount'].calculation['result'] == 30
    assert evidence['loss-count'].calculation['result'] == 2
    assert report.charts[0].data == [{'Region': 'East', 'value': 30}]
    from app.report_claims import seal_claims
    from app.services import assess_report_quality
    seal_claims(report)
    assert assess_report_quality(report).passed
    assert all('trend' not in b.id and 'forecast' not in b.id for b in report.blocks)


def test_custom_requirements_are_not_claimed_as_verified():
    frame, base = specimen()
    report = compose_report(base, frame, resolve_requirements('报告', {'must_include': '2027目标'}))
    assert report.metadata['requirements_review']['unverified'] == ['2027目标']
    assert '尚需逐项复核' in report.blocks[0].content


def test_fact_selection_cannot_relabel_operand_or_invent_number():
    evidence = [{'id': 'sample', 'statement': '样本数', 'value': '100'}]
    fid = next(iter(fact_catalog(evidence)))
    raw = {'protocol_version': 'synthesis-v4', 'summary': '已核对样本。', 'facts': [fid],
           'interpretations': [{'text': '风险记录有100条', 'fact_ids': [fid]}]}
    result = validate_fact_summary(raw, evidence)
    assert result.claims[0].text == '样本数：100'
    assert len(result.claims) == 1 and result.rejected_claims
    with pytest.raises(ValueError):
        validate_fact_summary({**raw, 'facts': ['invented']}, evidence)
    assert not fact_catalog(evidence + [{'id': 'sample', 'value': '200'}])


def test_requirement_report_repair_retains_verified_composition():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        wid = client.post('/api/v1/workspaces/bootstrap').json()['id']
        dataset = client.post('/api/v1/samples/retail-sales-2026/import', params={'workspace_id': wid}).json()
        cid = client.post('/api/v1/conversations', json={'workspace_id': wid, 'dataset_id': dataset['id'], 'clarification_mode': 'off'}).json()['id']
        plan = client.post('/api/v1/chat/plan', json={'workspace_id': wid, 'conversation_id': cid,
            'dataset_id': dataset['id'], 'message': '生成报告'}).json()
        result = client.post('/api/v1/chat/execute', json={'workspace_id': wid, 'conversation_id': cid,
            'plan_message_id': plan['user_message']['id'], 'approved': True})
        assert result.status_code == 200, result.text
        rid = result.json()['report_id']
        report = client.get(f'/api/v1/reports/{rid}').json()
        report['document']['summary'] = '销售额为 999999999 元。'
        client.put(f'/api/v1/reports/{rid}', json={'title': report['title'], 'document': report['document']})
        proposal = client.post(f'/api/v1/reports/{rid}/repair/preview').json()
        assert proposal['quality']['passed'], [(c['target_kind'], c['target_id'], c['reason']) for c in proposal['quality']['claim_checks'] if c['status']=='unverified']
