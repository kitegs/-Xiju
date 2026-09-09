"""Bounded factual presentation of computed rows; no invented business baseline."""
import math
import pandas as pd


def merge_report_evidence(existing, incoming):
    """Preserve richer execution metadata when a report schema projects the same fact."""
    known={e['id']:e for e in existing}
    for item in incoming:
        prior=known.get(item['id'])
        if prior is not None and all(prior.get(k)==item.get(k) for k in ('value','calculation','data')):
            continue
        existing.append(item)
    return existing


def unique_evidence_for_summary(records):
    # Keep duplicate evidence for catalog conflict detection; prioritize specific computations.
    rows=[]
    for raw in records:
        item=dict(raw)
        if str(item.get('id','')).startswith('sql-'):
            item['value']=describe_query(item)[:1200]
        rows.append(item)
    return sorted(rows,key=lambda r:0 if str(r.get('id','')).startswith(('reconciliation-','loss-','sql-','observed-')) else 1)


def describe_query(raw):
    rows=raw.get('data') or []
    parts=[]
    for row in rows[:3]:
        cells=[]
        for key,value in list(row.items())[:8]:
            if isinstance(value,float): value=f'{value:,.4f}'.rstrip('0').rstrip('.') if math.isfinite(value) else '不可用'
            cells.append(f'{key}={value}')
        parts.append('；'.join(cells))
    scope='仅说明返回记录，不据此推断因果或总体排名。'
    if raw.get('truncated') or '截断' in str(raw.get('value','')):
        scope='结果有截断，以下仅为预览，不能据此证明完整覆盖或全量排名。'
    return '\n'.join(parts+[scope]) if rows else '查询未返回记录，不能推断不存在其他范围的数据。'


def reconcile_frames(left,right,left_keys,right_keys,metric):
    if metric not in left or metric not in right:
        raise ValueError('两侧原表缺少同口径指标')
    if left[left_keys].isna().any().any() or right[right_keys].isna().any().any():
        raise ValueError('关联键存在缺失，不能声明完整核对')
    if right.duplicated(right_keys).any():
        raise ValueError('右表原始粒度不唯一，禁止静默去重核对')
    l=left[left_keys].copy(); l['_left']=pd.to_numeric(left[metric],errors='coerce')
    r=right[right_keys].rename(columns=dict(zip(right_keys,left_keys))).copy()
    r['_right']=pd.to_numeric(right[metric],errors='coerce')
    if l['_left'].isna().any() or r['_right'].isna().any():
        raise ValueError('指标存在缺失或非法值，不能把缺失按零核对')
    joined=l.groupby(left_keys,as_index=False)['_left'].sum().merge(r,on=left_keys,how='outer',indicator=True,validate='one_to_one')
    matched=joined.loc[joined['_merge']=='both'].copy()
    matched['difference']=matched['_left']-matched['_right']
    unmatched_left=int((joined['_merge']=='left_only').sum()); unmatched_right=int((joined['_merge']=='right_only').sum())
    mismatches=int((matched['difference'].abs()>1e-8).sum())
    max_diff=float(matched['difference'].abs().max()) if len(matched) else None
    total_diff=float(matched['difference'].sum())
    value=f'原表按 {", ".join(left_keys)} 核对 {metric}：匹配 {len(matched)} 组，左侧未匹配 {unmatched_left} 组，右侧未匹配 {unmatched_right} 组；匹配组非零差额 {mismatches} 组，差额合计 {total_diff:,.2f}，最大绝对差额 {max_diff}。'
    return {'id':'reconciliation-by-key','statement':'原表逐关联键核对（非总额推断）','value':value,
        'method':'左表按关联键聚合；右表必须键唯一；全外连接核对覆盖与逐组差额；不填充缺失指标',
        'source_columns':[*left_keys,metric], 'data':matched.drop(columns='_merge').head(30).to_dict('records'),
        'code':'left.groupby(keys)[metric].sum(); outer_merge(right_unique); compare_each_key',
        'verified_scope':{'keys':left_keys,'matched':len(matched),'left_only':unmatched_left,'right_only':unmatched_right,'mismatches':mismatches,'max_abs_difference':max_diff},
        'interpretation':'仅核对指定指标、关联键和数据版本，不证明其他指标一致，也不证明数据源真实。'}


def attach_hourly_chart(document,frame):
    from .schemas import Evidence,ChartSpec,ReportBlock
    required={'dteday','hr','workingday','cnt'}
    if not required.issubset(frame.columns) or frame.duplicated(['dteday','hr']).any():return
    grouped=frame.groupby(['hr','workingday'])['cnt'].mean().unstack('workingday')
    if not {0,1}.issubset(grouped.columns):return
    rows=[{'hr':int(hour),'工作日':None if pd.isna(row[1]) else float(row[1]),'非工作日':None if pd.isna(row[0]) else float(row[0])} for hour,row in grouped.sort_index().iterrows()]
    key='hourly-workday-joint'
    document.evidence.append(Evidence(id=key,statement='小时与工作日交叉分组均值',method='日期与小时唯一；按hr、workingday联合分组；工作日=workingday为1的cnt均值，非工作日=为0的cnt均值；缺失小时不补零',value='对每个实际观测时段分别计算工作日与非工作日的平均需求，不从边际分组推断联合峰值。',source_columns=['hr','workingday','cnt','工作日','非工作日'],data=rows,code="frame.groupby(['hr','workingday'])['cnt'].mean().unstack().rename(columns={1:'工作日',0:'非工作日'})"))
    document.charts.append(ChartSpec(id=key,title='各小时工作日与非工作日平均需求',chart_type='bar',x={'column':'hr'},y={'column':'工作日','aggregate':None},series=[{'column':'工作日','aggregate':None},{'column':'非工作日','aggregate':None}],data=rows,evidence_ids=[key],description='实际观测小时的算术均值，缺失小时不补零；不证明通勤因果。',style={'unit':'次/观测小时','show_legend':True}))
    document.blocks.append(ReportBlock(id=key,kind='chart',chart_id=key,evidence_ids=[key]))
