"""Report the evidence a check produced without claiming task-level success."""
def evidence(report,kind):
    result=dict(report)
    if kind=='syntax':
        checked=report.get('checked') is True
        status='passed' if checked and report.get('ok') is True else 'failed' if checked and report.get('ok') is False else 'not_run'
        scope='File syntax only; program behavior and requirements were not tested.'
    elif kind=='project':
        checked=report.get('executed') is True
        status='inconclusive' if checked and report.get('timed_out') else 'passed' if checked and report.get('exit_code')==0 else 'failed' if checked else 'not_run'
        scope='Only the named project command was run; inspect its assertions and output before claiming requirements are met.' if checked else 'Project check discovery only; no command was executed.'
    else:
        checked=not bool(report.get('error'))
        status='inconclusive' if not checked else 'passed' if report.get('ok') is True else 'failed' if report.get('ok') is False else 'inconclusive'
        scope='Observed browser runtime only; visual correctness, interactions and task requirements are not established.'
    result['verification']={'kind':kind,'status':status,'scope':scope,'task_success':None}
    return result
