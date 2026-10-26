from fastapi.testclient import TestClient
from app.main import app


def test_routes_and_input_validation():
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/healthz').json()['status']=='ok'
        assert client.get('/static/app.js').status_code==200
        assert client.post('/api/chat',json={'query':''}).status_code==422
        assert client.get('/api/conversations/not-a-uuid').status_code==422
        assert client.get('/api/sources/unknown').status_code==404


def test_post_commit_cleanup_failure_is_not_an_unsaved_turn(monkeypatch,tmp_path):
    import importlib,json
    module=importlib.import_module('app.main')
    from app.storage import LocalStore
    saved=LocalStore(tmp_path)
    monkeypatch.setattr(module,'store',lambda:saved)
    class Models:
        calls=[]
        openai_only=False
        def __init__(self,*args):pass
        async def close(self):pass
    class Tools:
        sources={}
        timings=[]
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):raise RuntimeError('teardown problem')
    class Graph:
        async def ainvoke(self,state,config):return {'answer':'Saved answer','findings':[]}
    monkeypatch.setattr(module,'Models',Models)
    monkeypatch.setattr(module,'Tools',Tools)
    monkeypatch.setattr(module,'build_graph',lambda *args:Graph())
    with TestClient(app) as client:
        response=client.post('/api/chat',json={'query':'test'})
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert sum(e['type']=='done' for e in events)==1
        assert not any(e['type']=='error' for e in events)
        assert any(e['type']=='cleanup_warning' for e in events)
        cid=next(e['conversation_id'] for e in events if e['type']=='done')
        assert client.get('/api/conversations/'+cid).json()['messages'][-1]['content']=='Saved answer'


def test_limits_reject_oversized_payloads():
    with TestClient(app) as client:
        for payload in ({'query':'x'*12001}, {'query':'valid','code':'x'*30001},
                        {'query':'valid','source_ids':['doc-a']*21},
                        {'query':'valid','conversation_id':'invalid'}):
            assert client.post('/api/chat',json=payload).status_code==422


def test_state_conflict_is_actionable_and_never_claims_saved(monkeypatch,tmp_path):
    import importlib,json
    module=importlib.import_module('app.main')
    from app.storage import StateConflict
    class Store:
        async def load(self,*args): raise StateConflict()
    monkeypatch.setattr(module,'store',lambda:Store())
    with TestClient(app) as client:
        response=client.post('/api/chat',json={'query':'test'})
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert not any(e['type']=='done' for e in events)
        error=next(e for e in events if e['type']=='error')
        assert error['code']=='state_conflict' and error['persisted'] is False
        assert 'Reload' in error['message']


def test_ui_has_functional_routing_trace_and_source_controls():
    from pathlib import Path
    html=Path('static/index.html').read_text()
    js=Path('static/app.js').read_text()
    for unwanted in ('THREE SPECIALISTS','YOUR TEAM','GCS durable memory','Backend connected'):
        assert unwanted not in html
    assert 'Activity' in html and 'Trace' in html
    assert 'routing_decision' in js and 'answer_delta' in js and 'citations' in js


def test_python_pasted_in_chat_reaches_code_state(monkeypatch,tmp_path):
    import importlib,json
    module=importlib.import_module('app.main')
    from app.storage import LocalStore
    monkeypatch.setattr(module,'store',lambda:LocalStore(tmp_path))
    class Models:
        calls=[];openai_only=False
        def __init__(self,*args):pass
        async def close(self):pass
    class Tools:
        sources={};timings=[]
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Graph:
        async def ainvoke(self,state,config):
            assert state['code']=='print(1)\n'
            return {'answer':'Inspected','findings':[]}
    monkeypatch.setattr(module,'Models',Models);monkeypatch.setattr(module,'Tools',Tools)
    monkeypatch.setattr(module,'build_graph',lambda *args:Graph())
    with TestClient(app) as client:
        result=client.post('/api/chat',json={'query':'Analyze this:\n```python\nprint(1)\n```'})
        events=[json.loads(line[6:]) for line in result.text.splitlines() if line.startswith('data: ')]
        assert any(e['type']=='done' for e in events) and not any(e['type']=='error' for e in events)
