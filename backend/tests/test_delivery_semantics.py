import asyncio
import pandas as pd
from app.capabilities import configure_steps, deepen, _run_diagnostic, DiagnosticChoice
from app.schemas import AnalysisCapabilities, AnalysisPlanStep


def test_queries_precede_report_and_review():
    steps=[AnalysisPlanStep(id=str(i),tool=t,title=t,description='') for i,t in enumerate(['report.build','sql.query','assistant.synthesize'])]
    tools=[s.tool for s in configure_steps(steps,AnalysisCapabilities(deep_analysis=True),True)]
    assert tools.index('sql.query') < tools.index('analysis.deepen') < tools.index('report.build') < tools.index('report.review')


def test_loss_scope_is_inherited_by_diagnostics():
    frame=pd.DataFrame({'Region':['A','A','B'], 'Profit':[1000,-10,-30]})
    async def ask(*args): return '{"tool":"analysis.dimension_breakdown","dimension":"Region","measure":"Profit","reason":"定位亏损"}'
    records,_=asyncio.run(deepen(frame,'亏损专题',[],1,[],ask,requirements={'focus':'loss'}))
    assert records[0]['data'][0]['Region']=='B'
    assert records[0]['data'][0]['Profit']==30
    assert records[0]['scope']['filter']['operator']=='lt'
    from app.services import run_sql_query
    _,rows,*_=run_sql_query(frame,records[0]['code'])
    assert rows[0]['Region']=='B' and list(rows[0].values())[1]==30


def test_discount_is_mean_not_sum():
    frame=pd.DataFrame({'Category':['A','A','B'],'Discount':[.1,.1,.15]})
    result=_run_diagnostic(frame,DiagnosticChoice(tool='analysis.dimension_breakdown',dimension='Category',measure='Discount',reason='折扣'),'test')
    assert result['data'][0]['Category']=='B'
    assert result['aggregation']=='mean'
    assert '占总体' not in result['value']
    assert 'AVG(' in result['code']


def test_report_projection_keeps_execution_scope():
    from app.result_presentation import merge_report_evidence
    original={'id':'deep-1','value':'10','data':[],'scope':{'filter':{'operator':'lt'}},'aggregation':'mean'}
    merged=merge_report_evidence([original], [{'id':'deep-1','value':'10','data':[]}])
    assert merged==[original] and merged[0]['scope']['filter']['operator']=='lt'


def test_ratio_sql_sum_is_rejected_not_silently_rewritten():
    import pytest
    from app.analysis_semantics import validate_ratio_aggregates
    with pytest.raises(ValueError): validate_ratio_aggregates('SELECT SUM("Discount") FROM dataset',['Discount'])
    validate_ratio_aggregates('SELECT AVG("Discount") FROM dataset',['Discount'])


def test_loss_plan_has_explicit_full_denominator_and_comparison_scope():
    from app.report_requirements import constrain_steps,resolve_requirements
    from app.services import run_sql_query
    frame=pd.DataFrame({'Profit':[100,-20,-5],'Region':['A','B','B'],'Discount':[.1,.2,.4]})
    steps=constrain_steps([],resolve_requirements('只分析亏损'),frame.columns.tolist())
    results={s.id:run_sql_query(frame,s.arguments['sql'])[1] for s in steps}
    assert results['loss-summary'][0]['loss_record_ratio']==2/3
    assert results['loss-summary'][0]['loss_amount']==25
    assert results['loss-region'][0]['Region']=='B'
    assert {r['profit_group'] for r in results['loss-discount']}=={'loss','non_loss'}


def test_reconciliation_and_hourly_delivery_certificates():
    from app.services import build_report,profile_dataframe,assess_report_quality
    from app.report_requirements import compose_report,resolve_requirements
    from app.report_claims import seal_claims
    from app.result_presentation import reconcile_frames
    frame=pd.DataFrame({'dteday':['2026-01-01','2026-01-01','2026-01-02','2026-01-02'],'hr':[8,17,8,17],'workingday':[0,0,1,1],'cnt':[10,20,30,40]})
    for focus in ('hourly','reconciliation'):
        doc=build_report(frame,profile_dataframe(frame),'fixture','')
        ev=reconcile_frames(frame,pd.DataFrame({'dteday':['2026-01-01','2026-01-02'],'cnt':[30,70]}),['dteday'],['dteday'],'cnt')
        compose_report(doc,frame,resolve_requirements('',{'focus':focus}),[ev])
        seal_claims(doc)
        quality=assess_report_quality(doc)
        assert not [i for i in quality.issues if i.severity=='error'], quality


def test_summary_does_not_promote_total_equality_to_daily_coverage():
    from app.fact_catalog import fact_catalog, validate_fact_summary
    evidence=[{'id':'total','statement':'总量差额','value':'0'}]
    fid=next(iter(fact_catalog(evidence)))
    raw={'protocol_version':'synthesis-v5','summary':'逐日完全一致且覆盖完整','facts':[fid],
         'interpretations':[{'text':'工作日傍晚最高，逐日完全一致','fact_ids':[fid]}]}
    result=validate_fact_summary(raw,evidence,strict=True)
    assert result.summary=='总量差额：0'
    assert len(result.claims)==1 and result.rejected_claims


def test_daily_reconciliation_detects_offsetting_differences_and_missing_keys():
    from app.result_presentation import reconcile_frames
    left=pd.DataFrame({'date':['a','b','c'],'cnt':[10,30,5]})
    right=pd.DataFrame({'date':['a','b','d'],'cnt':[20,20,5]})
    result=reconcile_frames(left,right,['date'],['date'],'cnt')['verified_scope']
    assert result['mismatches']==2 and result['left_only']==result['right_only']==1


def test_loss_report_retains_sql_values_and_prefers_region():
    from app.services import build_report,profile_dataframe
    from app.report_requirements import compose_report,resolve_requirements
    frame=pd.DataFrame({'Category':['X','Y'],'Region':['A','B'],'Profit':[-10,-20],'Sales':[40,50]})
    doc=build_report(frame,profile_dataframe(frame),'测试','亏损专题')
    compose_report(doc,frame,resolve_requirements('只分析亏损'),[{'id':'sql-a','statement':'区域亏损','method':'SQL','value':'返回2行','data':[{'Region':'B','loss_amount':20}]}])
    assert next(e for e in doc.evidence if e.id=='loss-groups').source_columns[0]=='Region'
    assert 'loss_amount=20' in next(b.content for b in doc.blocks if b.id=='result-sql-a')
    assert all('增长与稳定性' not in b.content for b in doc.blocks)
