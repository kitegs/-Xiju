import pandas as pd
import pytest
from app.services import build_report, profile_dataframe, assess_report_quality
from app.report_claims import growth_rate, period_growth, convert_unit, descending_rank


def sample():
    frame = pd.DataFrame({'Region':['West','East','West'], 'Sales':[100.,200.,300.], 'Profit':[10.,20.,30.]})
    return build_report(frame, profile_dataframe(frame), '测试报告', '分析经营')


def test_changed_number_and_wrong_evidence_are_not_certified():
    report = sample()
    assert assess_report_quality(report).passed
    report.findings[0].statement = report.findings[0].statement.replace('600.00','900.00')
    check = assess_report_quality(report)
    assert not check.passed
    assert any(c['target_id']==report.findings[0].id and c['status']=='unverified' for c in check.claim_checks)
    report = sample()
    report.findings[0].evidence_ids = ['dataset-shape']
    assert not assess_report_quality(report).passed


def test_correct_factual_rewrite_keeps_structured_claim_verified():
    report = sample()
    finding = next(item for item in report.findings if item.id == "finding-overall")
    finding.statement = "总体利润率为 10.00%；总利润为 60.00；总销售额为 600.00。"
    checked = assess_report_quality(report)
    row = next(item for item in checked.claim_checks if item["target_kind"] == "finding" and item["target_id"] == finding.id)
    assert row["status"] == "verified"
    assert "文字已改写" in row["reason"]
    assert checked.passed


def test_chart_data_period_rank_and_unit_are_part_of_delivery_gate():
    frame = pd.DataFrame({"Order Date": ["2024-01-01", "2025-01-01"], "Region": ["West", "East"], "Sales": [100., 200.], "Profit": [10., 20.]})
    report = build_report(frame, profile_dataframe(frame), "图文核对", "检查")
    chart = next(item for item in report.charts if item.id == "primary-trend")
    chart.data[-1]["Sales"] = 999
    checked = assess_report_quality(report)
    assert not checked.passed
    assert any(item["target_kind"] == "chart" and item["target_id"] == chart.id and item["status"] == "unverified" for item in checked.claim_checks)


def test_modified_evidence_and_new_assertion_cannot_pass():
    report = sample()
    report.evidence[1].value='999.00'
    assert not assess_report_quality(report).passed
    report = sample()
    report.blocks.append(type(report.blocks[0])(id='invented',kind='paragraph',content='销售额同比增长 10%。',evidence_ids=['metric-sales']))
    assert not assess_report_quality(report).passed


def test_rates_units_and_tied_rank_have_explicit_semantics():
    assert growth_rate(120,100) == pytest.approx(.2)
    for baseline in [0,-100]:
        with pytest.raises(ValueError): growth_rate(120,baseline)
    assert convert_unit(.2,'ratio','percent') == 20
    assert convert_unit(2,'万元','元') == 20000
    with pytest.raises(ValueError): convert_unit(10,'percent','percentage_point')
    assert descending_rank([100,200,200],200)==1
    assert descending_rank([100,200,200],100)==3
    assert period_growth(120,100,'2025-01','2024-01','yoy')==pytest.approx(.2)
    assert period_growth(120,100,'2025-01','2024-12','mom')==pytest.approx(.2)
    with pytest.raises(ValueError): period_growth(120,100,'2025-02','2024-01','yoy')


def test_calculation_mismatch_and_false_period_label_block_delivery():
    report=sample()
    margin=next(e for e in report.evidence if e.id=='metric-margin')
    margin.calculation['result']=.8
    assert any(c['target_kind']=='calculation' and c['status']=='unverified' for c in assess_report_quality(report).claim_checks)
    frame=pd.DataFrame({'Order Date':['2024-01-01','2024-02-01'],'Sales':[100.,120.],'Region':['A','A']})
    report=build_report(frame,profile_dataframe(frame),'趋势','趋势')
    trend=next(e for e in report.evidence if e.id=='trend-primary')
    trend.calculation['period_kind']='yoy'
    assert not assess_report_quality(report).passed


def test_fixed_retail_report_golden_answers_are_repeatable():
    # Small synthetic fixture, not the original Global Superstore dataset.
    frame=pd.DataFrame({'Order Date':['2024-01-01','2024-02-01','2025-01-01','2025-02-01'],
        'Region':['West','East','West','East'],'Sales':[100.,200.,150.,300.],'Profit':[10.,20.,15.,30.]})
    documents=[build_report(frame,profile_dataframe(frame),'固定基准','比较经营规模、区域和趋势') for _ in range(2)]
    for doc in documents:
        evidence={e.id:e for e in doc.evidence}
        assert evidence['metric-sales'].value=='750.00'
        assert evidence['metric-profit'].value=='75.00'
        assert evidence['metric-margin'].value=='10.00%'
        assert evidence['group-primary'].data==[{'Region':'East','Sales':500.0},{'Region':'West','Sales':250.0}]
        assert evidence['trend-primary'].calculation['result']==2.0
        assert evidence['trend-primary'].calculation['period_kind']=='interval'
        assert doc.quality.passed
    assert documents[0].metadata['claim_baseline']==documents[1].metadata['claim_baseline']


def test_client_cannot_replace_server_certificate_or_evidence():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        wid=client.post('/api/v1/workspaces/bootstrap').json()['id']
        dataset=client.post('/api/v1/samples/retail-sales-2026/import',params={'workspace_id':wid}).json()
        generated=client.post('/api/v1/analysis/run',json={'workspace_id':wid,'dataset_id':dataset['id'],'prompt':'经营报告'})
        assert generated.status_code==200,generated.text
        rid=generated.json()['report_id']
        doc=client.get(f'/api/v1/reports/{rid}').json()['document']
        original=doc['evidence'][0]['value']
        doc['findings'][0]['statement']='销售额为 999999999 元。'
        doc['metadata']['claim_baseline']['subjects'][f"finding:{doc['findings'][0]['id']}"]['text']=doc['findings'][0]['statement']
        doc['evidence'][0]['value']='伪造'
        result=client.put(f'/api/v1/reports/{rid}',json={'title':'编辑稿','document':doc})
        assert result.status_code==200,result.text
        saved=result.json()['document']
        assert saved['evidence'][0]['value']==original
        assert not saved['quality']['passed']
        assert client.get(f'/api/v1/reports/{rid}/export.docx').status_code==422
