from scripts.scenarios import check


def valid_events():
    return [dict(type='routing_decision',sequence=1,agent='Supervisor',provider='openai',model='gpt-6-luna',reason='task'),
            dict(type='answer_delta',sequence=2,text='hello'),dict(type='done',sequence=3,persisted=True)]


def test_runner_rejects_errors_after_done():
    events=valid_events()+[dict(type='error',sequence=4)]
    failures,_=check({},events)
    assert 'Turn emitted an error' in failures
    assert 'Done must be the final event' in failures


def test_runner_rejects_missing_requested_agent():
    failures,_=check({'agents':['Summary']},valid_events())
    assert 'Missing Summary worker' in failures


def test_runner_checks_provider_and_rationale():
    events=valid_events();events[0]['provider']='nvidia';events[0]['reason']=''
    assert len(check({},events)[0])==2


def test_runner_accepts_clean_completion():
    assert check({},valid_events()) == ([], 'hello')
