"""Bounded report composition; no generated calculations or permission decisions."""
import re
import pandas as pd


def resolve_requirements(message, explicit=None):
    from .schemas import ReportRequirements
    value=ReportRequirements.model_validate(explicit or {}).model_dump()
    if value['depth']=='auto': value['depth']='brief' if re.search('简要|简报|简短|三条结论',message) else 'detailed' if re.search('详细|方法说明|完整分析过程',message) else 'standard'
    if value['focus']=='auto': value['focus']='loss' if re.search('只.*亏损|重点.*亏损|亏损分析',message) else 'hourly' if re.search('小时需求|工作日.*需求',message) else 'general'
    if value['audience']=='auto': value['audience']='manager' if re.search('老板|管理层|负责人',message) else 'analyst'
    if value['focus'] in {'general','auto'} and re.search('多表核对|小时表与日表|两表.*核对',message): value['focus']='reconciliation'
    value['exclude_trend'] |= bool(re.search('(不要|不生成|不做|不包含).{0,5}趋势',message))
    value['exclude_forecast'] |= bool(re.search('(不要|不生成|不做|不包含).{0,5}预测|仅描述现状',message))
    return value


def constrain_steps(steps, requirements, columns=()):
    # Semantic report constraints never increase permissions.
    steps=[s for s in steps if not (requirements['exclude_forecast'] and s.tool=='timeseries.forecast')]
    if requirements['focus']=='loss' and columns:
        # Explicit server-owned topic calculations, shown in the approval plan.
        # This is not a fallback after a failed model query.
        from .schemas import AnalysisPlanStep
        by_name={str(c).casefold():str(c) for c in columns}
        profit=next((by_name[n] for n in ('profit','利润','毛利') if n in by_name),None)
        if profit:
            quote=lambda name:'"'+name.replace('"','""')+'"'
            p=quote(profit)
            queries=[('loss-summary','亏损记录与全表分母核对',f'SELECT COUNT(*) AS loss_record_count, -SUM({p}) AS loss_amount, COUNT(*) * 1.0 / NULLIF((SELECT COUNT(*) FROM dataset),0) AS loss_record_ratio FROM dataset WHERE {p} < 0')]
            for name in ('region','category'):
                if name in by_name:
                    c=quote(by_name[name])
                    queries.append(('loss-'+name,by_name[name]+'亏损集中项',f'SELECT {c}, COUNT(*) AS loss_record_count, -SUM({p}) AS loss_amount FROM dataset WHERE {p} < 0 GROUP BY {c} ORDER BY loss_amount DESC LIMIT 10'))
            if 'discount' in by_name:
                d=quote(by_name['discount'])
                queries.append(('loss-discount','亏损与非亏损参照组的记录平均折扣（非因果）',f"SELECT CASE WHEN {p} < 0 THEN 'loss' ELSE 'non_loss' END AS profit_group, AVG({d}) AS mean_discount, COUNT(*) AS record_count FROM dataset WHERE {p} IS NOT NULL GROUP BY 1"))
            steps=[s for s in steps if s.tool!='sql.query']
            index=next((i for i,s in enumerate(steps) if s.tool in {'analysis.deepen','report.build','assistant.synthesize'}),len(steps))
            steps[index:index]=[AnalysisPlanStep(id=i,tool='sql.query',title=t,description='专题固定口径：正式值由只读查询计算；负利润范围和参照组分母在 SQL 中显式展示。',arguments={'sql':q}) for i,t,q in queries]
    if requirements['focus']=='reconciliation':
        from .schemas import AnalysisPlanStep
        steps=[s for s in steps if s.tool not in {'sql.query','analysis.deepen','data.reconcile','research.inferential','action.recommend'}]
        index=next((i for i,s in enumerate(steps) if s.tool in {'report.build','assistant.synthesize'}),len(steps))
        steps.insert(index,AnalysisPlanStep(id='reconcile-keys',tool='data.reconcile',title='原表逐键核对与覆盖检查',description='读取关系绑定的原表版本；按关联键核对差额、两侧未匹配项及右表键唯一性，不在展开行聚合右表指标。'))
    return steps


def _loss_evidence(document, frame):
    from .schemas import Evidence, ReportFinding, ReportBlock, ChartSpec
    profit=next((str(c) for c in frame if str(c).casefold() in {'profit','利润','毛利'}),None)
    semantics=document.metadata.get('semantics') or {}
    if profit in set(semantics.get('non_additive_columns') or []): return False
    if not profit: return False
    dimension=next((str(c) for name in ('region','区域','category','品类') for c in frame if str(c).casefold()==name),None)
    values=pd.to_numeric(frame[profit],errors='coerce')
    loss=frame.loc[values<0].copy()
    amount=float(-values[values<0].sum()); count=len(loss)
    for key,result,unit,text in [('loss-amount',amount,'number','亏损记录的亏损额（绝对值）'),('loss-count',count,'count','亏损记录数')]:
        e=Evidence(id=key,statement=text,value=f'{result:,.2f}' if unit=='number' else f'{result:,}',method='筛选利润小于零的记录，再计算；不是净利润',source_columns=[profit],
            calculation={'operation':'sum' if key=='loss-amount' else 'count','operands':(-values[values<0]).tolist() if key=='loss-amount' else [count],'result':result,'unit':unit,'metric':profit},code=f'values = pd.to_numeric(frame[{profit!r}], errors="coerce")\nloss = frame.loc[values < 0]\nresult = ' + ('float(-values[values < 0].sum())' if key=='loss-amount' else 'len(loss)'))
        document.evidence.append(e)
        document.findings.append(ReportFinding(id=f'finding-{key}',headline=text,statement=f'{text}：{e.value}',business_impact='亏损额与净利润是不同口径；此处定位需复核的亏损记录，不代表折扣导致亏损。',recommendation='核对亏损集中分组的订单、折扣及成本口径，再验证调整方案。',caveats=['未确认币种时不做跨币种比较。'],evidence_ids=[key]))
        document.blocks.append(ReportBlock(id=f'block-{key}',kind='insight',content=f'{text}：{e.value}。\n解释：这是亏损记录口径，不是净利润。\n行动：复核原订单和成本后再决定调整。',evidence_ids=[key]))
    if dimension and count:
        work=pd.DataFrame({dimension:loss[dimension].astype(str),'loss_amount':-values.loc[loss.index]})
        rows=work.groupby(dimension,as_index=False).loss_amount.sum().sort_values('loss_amount',ascending=False).head(10).to_dict('records')
        rows=[{dimension: row[dimension], 'value': row['loss_amount']} for row in rows]
        e=Evidence(id='loss-groups',statement=f'按{dimension}定位亏损集中项',method='仅利润为负的记录，按维度汇总亏损绝对值；输出 value 为亏损额',value=f'最高组为 {rows[0][dimension]}，亏损额 {rows[0]["value"]:,.2f}',source_columns=[dimension,profit],data=rows,code=f'loss.groupby({dimension!r})[{profit!r}].sum().mul(-1).sort_values(ascending=False).head(10).rename("value").reset_index()')
        document.evidence.append(e)
        document.charts.append(ChartSpec(id='loss-comparison',title=f'{dimension}亏损额分布',chart_type='bar',x={'column':dimension},y={'column':'value','aggregate':None},series=[{'column':'value','aggregate':None}],data=rows,evidence_ids=[e.id],description='仅展示亏损记录，亏损额以绝对值展示；不是区域净利润。'))
        document.blocks.append(ReportBlock(id='loss-chart',kind='chart',chart_id='loss-comparison',evidence_ids=[e.id]))
    return True


def synchronize_action_blocks(document):
    for block in document.blocks:
        if block.id=='actions':
            block.content='\n'.join(f'{i+1}. {a.action} 验证指标：{a.validation_metric}' for i,a in enumerate(document.actions))
            block.evidence_ids=list(dict.fromkeys(e for a in document.actions for e in a.evidence_ids))
    document.blocks=[b for b in document.blocks if b.id!='actions' or document.actions]


def compose_report(document, frame, requirements, tool_evidence=()):
    from .schemas import ReportBlock, Evidence, ReportFinding, ReportActionItem
    req=dict(requirements); focus=req['focus']; depth=req['depth']
    document.metadata['report_requirements']=req
    # Source calculations/evidence remain retained even if omitted from this presentation.
    if focus=='loss':
        document.blocks=[b for b in document.blocks if b.id in {'shape','date-limit','limitations-title','review'} or any(e.startswith('discount-') for e in b.evidence_ids)]
        if not _loss_evidence(document,frame):
            document.blocks.append(ReportBlock(id='loss-unavailable',kind='paragraph',content='缺少可识别的利润字段，无法完成亏损分析；请先确认字段口径。'))
        document.actions=[]
        if any(e.id=='loss-amount' for e in document.evidence):
            document.actions=[ReportActionItem(id='verify-loss',action='复核亏损集中区域的原始订单、折扣和成本记录，核对后再评估调整。',rationale='负利润定位不是因果结论，不能直接认定折扣导致亏损。',validation_metric='已复核亏损记录比例、成本差异及同口径亏损额。',evidence_ids=['loss-amount','loss-count'])]
        for chart in document.charts:
            if chart.id=='loss-comparison': chart.style.orientation='horizontal'
    elif focus=='hourly':
        document.blocks=[b for b in document.blocks if b.id in {'shape','relationship-grain','relationship-reconciliation','review'} or any(e.startswith('observed-') for e in b.evidence_ids)]
        if not any(e.id.startswith('observed-') for e in document.evidence):
            document.blocks.append(ReportBlock(id='hourly-unavailable',kind='paragraph',content='当前数据没有通过小时粒度校验，无法给出可比小时需求；请确认日期、小时和指标字段。'))
        document.actions=[]
        from .result_presentation import attach_hourly_chart
        attach_hourly_chart(document,frame)
    elif focus=='reconciliation':
        document.blocks=[b for b in document.blocks if b.id in {'shape','relationship-grain','relationship-reconciliation','review'}]
        document.actions=[]
    if req['exclude_trend']:
        document.blocks=[b for b in document.blocks if 'trend' not in b.id and not any('trend' in e for e in b.evidence_ids)]
    if req['exclude_forecast']:
        document.blocks=[b for b in document.blocks if 'forecast' not in b.id and not any('forecast' in e for e in b.evidence_ids)]
    if any(e.id=='data-limit-date' for e in document.evidence):
        for b in document.blocks:
            if b.kind=='insight' and '增长、稳定性或目标完成率' in b.content:
                b.content=b.content.replace('增长、稳定性或目标完成率','同口径的利润、亏损分布；恢复日期后再比较增长')
        for a in document.actions:
            if '增长' in a.action: a.action='先恢复并核对日期，再评估分组的时间变化。'; a.validation_metric='有效日期覆盖率及恢复后的同口径对比。'
    # Keep the rendered action block aligned with the selected topic and date constraints.
    synchronize_action_blocks(document)
    # Successful SQL contributes bounded numeric prose to non-brief or focused reports.
    if depth!='brief' or focus!='general':
        from .result_presentation import describe_query
        known={e.id for e in document.evidence}
        for raw in tool_evidence:
            if str(raw.get('id','')).startswith('sql-') or raw.get('id')=='reconciliation-by-key':
                if raw['id'] not in known:
                    document.evidence.append(Evidence.model_validate(raw)); known.add(raw['id'])
                content=raw['value']+'\n'+raw.get('interpretation','') if raw['id']=='reconciliation-by-key' else describe_query(raw)
                document.blocks.append(ReportBlock(id='result-'+raw['id'],kind='insight',content=f"{raw.get('statement','')}\n{content}",evidence_ids=[raw['id']]))
                if raw['id']=='reconciliation-by-key':
                    document.findings.append(ReportFinding(id='finding-reconciliation',headline=raw['statement'],statement=raw['value'],business_impact='逐键差额与未匹配项用于判断这两个版本的指定指标能否对齐，不以总量相等替代逐键检查。',recommendation='复核非零差额和未匹配键；更换版本或指标后重新核对。',caveats=[raw.get('interpretation','')],evidence_ids=[raw['id']]))
        if focus=='reconciliation' and 'reconciliation-by-key' not in known:
            document.blocks.append(ReportBlock(id='reconciliation-unavailable',kind='callout',content='未完成原表逐键核对，当前总额相等不能证明逐日一致或完整覆盖。'))
    if depth=='brief':
        content=[b for b in document.blocks if b.kind=='insight'][:3]
        chart_types={c.id:c.chart_type for c in document.charts}
        graphs=sorted([b for b in document.blocks if b.kind=='chart'],key=lambda b:chart_types.get(b.chart_id)=='kpi')[:3]
        limits=[b for b in document.blocks if b.id in {'date-limit','review','relationship-reconciliation','loss-unavailable','hourly-unavailable'}]
        document.blocks=content+graphs+limits
        document.actions=document.actions[:2]
    elif depth=='detailed':
        document.blocks.append(ReportBlock(id='method-scope',kind='paragraph',content='方法与复核：正式数值由完整数据计算；分组结果描述观察差异，不证明因果。请结合证据中的过滤条件、分母、单位及数据版本复核。'))
    used_charts={b.chart_id for b in document.blocks if b.chart_id}
    document.charts=[c for c in document.charts if c.id in used_charts]
    used_evidence={i for b in document.blocks for i in b.evidence_ids}
    document.findings=[f for f in document.findings if set(f.evidence_ids)&used_evidence]
    document.metadata['appendix_visible']=depth!='brief'
    document.metadata['requirements_review']={'status':'bounded_presets_applied','unverified':[t for t in [req['must_include'],req['must_exclude']] if t]}
    title={'loss':'亏损分析','hourly':'小时需求分析','general':'综合分析','reconciliation':'多表核对'}[focus]
    document.title=f"{title} · {'简报' if depth=='brief' else '详细报告' if depth=='detailed' else '标准报告'}"
    document.summary=f"面向{'管理者' if req['audience']=='manager' else '分析人员'}的{title}；数值依据与计算记录保留，因果解释及行动效果需要业务验证。"
    if req['must_include'] or req['must_exclude']:
        document.blocks.insert(0,ReportBlock(id='requirements-review',kind='paragraph',content='自定义要求尚需逐项复核，不能视为已满足；原始要求保留在报告元数据中。'))
    return document
