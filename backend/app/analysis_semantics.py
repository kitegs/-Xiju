"""Server-owned scope and aggregation rules; never derived from model SQL text."""
import pandas as pd
import re


def validate_ratio_aggregates(sql, columns):
    """Reject obvious ratio sums rather than silently changing a proposed query."""
    for column in columns:
        if aggregation_for(column)=='mean' and re.search(r'\bSUM\s*\([^)]*(?<!\w)'+re.escape(str(column))+r'(?!\w)',sql,re.I):
            raise ValueError(f'比例字段 {column} 不允许默认求和；请明确记录均值或加权分子、分母')


def aggregation_for(column):
    name=str(column).casefold()
    return 'mean' if any(t in name for t in ('discount','ratio','rate','percent','折扣','比例','率')) else 'sum'


def analysis_scope(frame, requirements):
    if (requirements or {}).get('focus') != 'loss':
        return frame, {'population':'完整当前数据版本'}
    profit=next((str(c) for c in frame if str(c).casefold() in {'profit','利润','毛利'}),None)
    if not profit:
        raise ValueError('亏损专题缺少利润字段，不能退回全表补算')
    scoped=frame.loc[pd.to_numeric(frame[profit],errors='coerce')<0].copy()
    return scoped, {'population':'仅负利润记录','filter':{'column':profit,'operator':'lt','value':0},'row_count':len(scoped)}
