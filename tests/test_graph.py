import asyncio
import json
import pytest
from app.events import Events, clean
from app.graph import build_graph, validate_plan, routing_signals
from app.tools import analyze_python, ALLOW


class FakeModels:
    def __init__(self, events):
        self.events=events
        self.plans=0
    async def generate(self, messages, provider, agent, reason, validator=None, stream=False):
        if agent == 'Supervisor':
            self.plans+=1
            answer=json.dumps({'next':'Research' if self.plans==1 else 'finish','provider':'nvidia','reason':'simple lookup'})
        elif agent == 'Research':
            if not any(m['role'] == 'user' and m['content'].startswith('Tool result') for m in messages):
                answer=json.dumps({'tool':'search_corpus','arguments':{'query':'memory'}})
            else:
                answer=json.dumps({'finding':'Checkpoints store state [doc-test::0000].'})
        else:
            answer='Checkpoints store state [doc-test::0000].'
            await self.events.emit('answer_delta',text=answer)
        return validator(answer) if validator else answer


class FakeTools:
    sources={}
    async def catalog(self, agent):
        return {'search_corpus':{'input_schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}}
    async def call(self, agent, name, args):
        self.sources={'doc-test::0000':{'id':'doc-test::0000','text':'Checkpoints store state','url':'https://example.com'}}
        return list(self.sources.values())


@pytest.mark.asyncio
async def test_graph_delegates_and_preserves_sources():
    events=Events(asyncio.Queue())
    tools=FakeTools()
    graph=build_graph(FakeModels(events),tools,events)
    result=await graph.ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
    assert result['completed']==['Research']
    assert '[doc-test::0000]' in result['answer']
    assert any(e['type']=='citations' for e in events.trace)


@pytest.mark.asyncio
async def test_citation_group_normalization_uses_only_retrieved_sources():
    class GroupedModels(FakeModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Answer':
                return 'Grounded [doc-test::0, doc-unknown::99].'
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());tools=FakeTools()
    result=await build_graph(GroupedModels(events),tools,events).ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
    assert '[doc-test::0000]' in result['answer']
    assert '[doc-unknown::99]' not in result['answer']
    assert '(source unavailable)' in result['answer']


@pytest.mark.asyncio
async def test_duplicate_worker_is_not_dispatched_again():
    class RepeatingModels(FakeModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Supervisor':
                return validator(json.dumps({'next':'Research','provider':'nvidia','reason':'retrieve evidence'}))
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());tools=FakeTools()
    result=await build_graph(RepeatingModels(events),tools,events).ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
    assert result['completed']==['Research']


def test_analysis_and_tool_boundaries():
    assert analyze_python('def broken(')['valid_syntax'] is False
    assert analyze_python('async def main():\n    return 1')['functions'][0]['async'] is True
    assert 'analyze_python' not in ALLOW['Research']
    assert 'tavily_search' not in ALLOW['Code']
    assert {'search_corpus'} <= ALLOW['Code'] & ALLOW['Research']
    assert clean({'url':'https://example.com/?tavilyApiKey=secret','api_key':'secret'}) == {'url':'https://example.com/?tavilyApiKey=[redacted]','api_key':'[redacted]'}


def test_capability_routing_keeps_simple_followups_cheap():
    assert routing_signals('Compare GCS and Firestore for concurrency and design tradeoffs')
    assert routing_signals('Given our earlier solution, explain failure recovery')
    assert not routing_signals('Make your previous answer shorter')
    assert not routing_signals('What is a checkpoint?')


@pytest.mark.asyncio
@pytest.mark.parametrize('citation',['source: doc-test::0','Source: doc-test::0000','sources: doc-test::0, doc-unknown::99','doc-test::0000'])
async def test_source_prefixed_citations_become_verified_links(citation):
    class CitationModels(FakeModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Answer':return f'Grounded [{citation}].'
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());tools=FakeTools()
    result=await build_graph(CitationModels(events),tools,events).ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
    assert '[doc-test::0000]' in result['answer']
    cited=next(e['sources'] for e in events.trace if e['type']=='citations')
    assert [c['id'] for c in cited]==['doc-test::0000']
    assert 'doc-unknown' not in result['answer']


@pytest.mark.asyncio
async def test_parent_document_citation_links_only_actual_retrieved_chunks():
    class ParentModels(FakeModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Answer':return 'Grounded [source: doc-test]. Missing [doc-unknown].'
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());tools=FakeTools()
    result=await build_graph(ParentModels(events),tools,events).ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
    assert '[doc-test::0000]' in result['answer'] and '[doc-unknown]' not in result['answer']
    assert [s['id'] for e in events.trace if e['type']=='citations' for s in e['sources']]==['doc-test::0000']


def test_numeric_chunk_alias_is_resolved_only_when_unambiguous():
    from app.graph import normalize_citations
    sources={'doc-one::0001':{},'doc-two::0002':{}}
    assert normalize_citations('Fact [0001].',sources)=='Fact [doc-one::0001].'
    sources['doc-two::0001']={}
    assert normalize_citations('Fact [0001].',sources)=='Fact (source unavailable).'
    assert normalize_citations('Fact [0099].',sources)=='Fact (source unavailable).'


@pytest.mark.asyncio
async def test_retrieved_answer_without_citations_is_rejected():
    from app.providers import InvalidOutput
    class UncitedModels(FakeModels):
        async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
            if agent=='Answer':return validator('Here is an uncited answer.')
            return await super().generate(messages,provider,agent,reason,validator,stream)
    events=Events(asyncio.Queue());tools=FakeTools()
    with pytest.raises(InvalidOutput):
        await build_graph(UncitedModels(events),tools,events).ainvoke(dict(query='memory?',code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))


def test_placeholder_sources_are_removed_without_removing_real_citations():
    from app.graph import normalize_citations
    text='[exact-source-id; general knowledge]\nHello! (General knowledge response—no source evidence was supplied for this session.)'
    assert normalize_citations(text,{})=='Hello!'
    assert normalize_citations('Evidence [doc-test::0000].',{'doc-test::0000':{}})=='Evidence [doc-test::0000].'
