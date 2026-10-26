"""Behavioral contracts for rubric requirements, without external API calls."""
import asyncio
import json
import pytest
from app.events import Events, clean
from app.graph import build_graph, validate_plan, validate_action, required_workers
from app.providers import InvalidOutput
from tests.test_graph import FakeTools


def state(query='What is memory?', **changes):
    return dict(query=query, code='', selected_sources=[], history=[], findings=[], errors=[],
                dispatches=0, completed=[], next='', provider='nvidia', reason='', answer='', **changes)


class ScriptedModels:
    def __init__(self, events, plans, failing=None):
        self.events, self.plans, self.failing = events, iter(plans), failing
        self.requests = []
    async def generate(self, messages, provider, agent, reason, validator=None, stream=False):
        self.requests.append((agent, provider, messages))
        if agent == self.failing:
            raise RuntimeError('injected worker outage')
        if agent == 'Supervisor':
            text = json.dumps(dict(next=next(self.plans, 'finish'), provider='nvidia', reason='inspect current state'))
        elif agent == 'Answer':
            text = 'Evidence [doc-test::0000].'
            await self.events.emit('answer_delta', text=text)
        elif agent == 'Research' and not any(m['content'].startswith('Tool result') for m in messages):
            text = json.dumps(dict(tool='search_corpus', arguments={'query':'memory'}))
        else:
            text = json.dumps(dict(finding='Existing evidence [doc-test::0000].'))
        return validator(text) if validator else text


@pytest.mark.asyncio
@pytest.mark.parametrize('query,plans,expected', [
    ('Research memory, then summarize the findings.', ['Research','finish','finish'], ['Research','Summary']),
    ('Research memory, then summarize the findings.', ['Summary','Research','Research'], ['Research','Summary']),
    ('Summarize the research findings.', ['finish','finish'], ['Summary']),
    ('Summarize your previous findings.', ['Summary','finish'], ['Summary']),
    ('What is a checkpoint?', ['Research','finish'], ['Research']),
    ('Hello', ['finish'], []),
])
async def test_requested_work_is_completed_without_duplicates(query, plans, expected):
    events=Events(asyncio.Queue()); models=ScriptedModels(events, plans)
    result=await build_graph(models, FakeTools(), events).ainvoke(state(query))
    assert result['completed'] == expected
    assert result['answer']
    assert all(provider == 'openai' for agent,provider,_ in models.requests if agent == 'Supervisor')


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', ['Research','Summary'])
async def test_failed_worker_returns_to_supervisor_and_answer(failed):
    events=Events(asyncio.Queue()); models=ScriptedModels(events,[failed,'finish'],failed)
    result=await build_graph(models,FakeTools(),events).ainvoke(state())
    assert result['errors'] == [failed+' failed']
    assert result['answer']
    assert [a for a,_,_ in models.requests][-2:] == ['Supervisor','Answer']


@pytest.mark.asyncio
async def test_worker_receives_findings_but_not_other_worker_tool_transcript():
    events=Events(asyncio.Queue()); models=ScriptedModels(events,['Research','Summary','finish'])
    result=await build_graph(models,FakeTools(),events).ainvoke(state('Research memory then summarize it.'))
    summary=next(messages for agent,_,messages in models.requests if agent == 'Summary')
    payload=json.loads(summary[1]['content'])
    assert payload['findings'][0]['agent']=='Research'
    assert not any(m['role']=='user' and m['content'].startswith('Tool result') for m in summary)
    assert result['completed']==['Research','Summary']


@pytest.mark.parametrize('plan', [
    {}, {'next':'Other','provider':'openai','reason':'why'},
    {'next':'finish','provider':'other','reason':'why'},
    {'next':'finish','provider':'openai','reason':''},
    {'next':'finish','provider':'openai','reason':None},
])
def test_invalid_supervisor_plans_rejected(plan):
    with pytest.raises(InvalidOutput): validate_plan(json.dumps(plan))


@pytest.mark.parametrize('action', [
    {'tool':'tavily_search','arguments':{}},
    {'tool':'read_chunks','arguments':{'ids':42}},
    {'tool':'read_chunks','arguments':{}},
    {'finding':''},
])
def test_invalid_or_unauthorized_tool_requests_rejected(action):
    schema={'read_chunks': {'input_schema':{'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'}}},'required':['ids']}}}
    with pytest.raises(InvalidOutput): validate_action(schema)(json.dumps(action))


@pytest.mark.parametrize('query,expected', [
    ('Research memory then summarize it', ['Research','Summary']),
    ('Summarize research findings', ['Summary']),
    ('Make your previous answer shorter', []),
    ('Search the web for current news', ['Research']),
])
def test_required_tasks_come_from_current_request(query,expected):
    assert required_workers(state(query)) == expected


@pytest.mark.parametrize('secret', ['sk-proj-example-secret','nvapi-example-secret','tvly-example-secret','pcsk_example-secret'])
def test_provider_credentials_never_appear_in_trace(secret):
    assert secret not in json.dumps(clean({'nested':[{'error':secret}]}))


def test_redaction_is_idempotent_and_preserves_markdown_boundaries():
    source='Use `?tavilyApiKey=example` with a key.'
    redacted=clean(source)
    assert redacted=='Use `?tavilyApiKey=[redacted]` with a key.'
    assert clean(redacted)==redacted


@pytest.mark.asyncio
async def test_saved_answer_matches_redacted_final_stream():
    class ExampleModels(ScriptedModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Answer':return 'Use `?tavilyApiKey=example`.'
            return await super().generate(messages,provider,agent,reason,validator,stream)
    queue=asyncio.Queue();events=Events(queue)
    result=await build_graph(ExampleModels(events,['finish']),FakeTools(),events).ainvoke(state())
    deltas=[e['text'] for e in list(queue._queue) if e['type']=='answer_delta']
    assert result['answer']==deltas[-1]=='Use `?tavilyApiKey=[redacted]`.'


@pytest.mark.asyncio
async def test_dispatch_limit_still_produces_answer():
    events=Events(asyncio.Queue());models=ScriptedModels(events,[])
    initial=state();initial['dispatches']=6
    result=await build_graph(models,FakeTools(),events).ainvoke(initial)
    assert result['answer'] and not result['completed']
    assert any(e['type']=='execution_limit' for e in events.trace)


@pytest.mark.asyncio
async def test_worker_outage_retains_previous_successful_findings():
    events=Events(asyncio.Queue());models=ScriptedModels(events,['Research','Summary','finish'],'Summary')
    result=await build_graph(models,FakeTools(),events).ainvoke(state('Research memory then summarize.'))
    assert result['findings'][0]['agent']=='Research'
    assert result['errors']==['Summary failed']
    assert result['completed']==['Research','Summary'] and result['answer']


@pytest.mark.asyncio
async def test_research_cannot_claim_retrieval_without_a_successful_tool():
    class PrematureModels(ScriptedModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Research':return validator(json.dumps({'finding':'I searched the documentation.'}))
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());models=PrematureModels(events,['Research','finish'])
    result=await build_graph(models,FakeTools(),events).ainvoke(state('Search the documentation.'))
    assert result['findings']==[] and result['errors']==['Research failed']
    assert result['answer']


@pytest.mark.asyncio
async def test_failed_retrieval_does_not_satisfy_research_requirement():
    class OfflineTools(FakeTools):
        async def call(self,*args):return {'error':'offline'}
    events=Events(asyncio.Queue());models=ScriptedModels(events,['Research','finish'])
    result=await build_graph(models,OfflineTools(),events).ainvoke(state('Search the documentation.'))
    assert not result['findings'] and result['errors']==['Research failed']


def test_live_research_and_selected_summary_require_appropriate_evidence_tools():
    from app.graph import required_tool_groups
    assert required_tool_groups('Research',state('Search the web for latest news'))==[{'tavily_search','tavily_extract'}]
    selected=state();selected['selected_sources']=['doc-test']
    assert required_tool_groups('Summary',selected)==[{'read_chunks','read_document'}]
