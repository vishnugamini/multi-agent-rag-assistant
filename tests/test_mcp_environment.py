import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from app.config import Settings
from app.events import Events
from app.tools import Tools


@pytest.mark.asyncio
async def test_stdio_explicitly_forwards_only_corpus_secrets(monkeypatch):
    seen={}
    @asynccontextmanager
    async def transport(params):
        seen.update(params.env)
        yield object(),object()
    class Session:
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def initialize(self):pass
        async def list_tools(self):return SimpleNamespace(tools=[])
    monkeypatch.setattr('app.tools.stdio_client',transport)
    monkeypatch.setattr('app.tools.ClientSession',Session)
    config=Settings(_env_file=None,openai_api_key='openai-test',pinecone_api_key='pinecone-test',tavily_api_key='private-tavily')
    async with Tools(config,Events(asyncio.Queue())) as tools:
        await tools.connect('corpus')
    assert seen['OPENAI_API_KEY']=='openai-test'
    assert seen['PINECONE_API_KEY']=='pinecone-test'
    assert seen['PINECONE_INDEX']==config.pinecone_index
    assert 'TAVILY_API_KEY' not in seen
    assert 'GCS_STATE_BUCKET' not in seen
