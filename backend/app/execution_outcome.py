"""Completion describes lifecycle, not successful delivery of every requested step."""


def assess_outcome(tool_runs, synthesis=None):
    problems = [{'step_id': row.get('step_id'), 'tool': row.get('tool'),
                 'reason': row.get('output_summary', '')[:500]}
                for row in tool_runs if row.get('status') in {'failed', 'blocked'}]
    if (synthesis or {}).get('status') in {'partial', 'degraded'}:
        problems.append({'tool': 'assistant.synthesize', 'reason': (synthesis or {}).get('error') or '部分总结未通过核验'})
    return {'status': 'degraded' if problems else 'completed', 'problems': problems,
            'note': '运行结束不等于语义验收通过；规则只覆盖已实现的检查。'}
