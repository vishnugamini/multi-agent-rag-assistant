import asyncio
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
import httpx
import pytest
from app.events import Events
from app.providers import Models
from tests.test_providers import config


class BrokenStream:
    def __aiter__(self):
        return self.iterate()
    async def iterate(self):
        yield Obj(usage=None, choices=[Obj(delta=Obj(content='Partial NVIDIA'), finish_reason=None)])
        raise httpx.ReadTimeout('stream interrupted')
    async def close(self):
        pass


class OpenAIStream:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def __aiter__(self):
        return self.iterate()
    async def iterate(self):
        yield Obj(type='response.output_text.delta', delta='Complete OpenAI')
    async def get_final_response(self):
        return Obj(usage=None, status='completed')


@pytest.mark.asyncio
async def test_stream_reset_before_openai_output(monkeypatch):
    monkeypatch.setattr('app.providers.asyncio.sleep', AsyncMock())
    queue=asyncio.Queue()
    models=Models(config(), Events(queue))
    monkeypatch.setattr(models.clients['nvidia'].chat.completions,'create',AsyncMock(return_value=BrokenStream()))
    monkeypatch.setattr(models.clients['openai'].responses,'stream',lambda **kwargs: OpenAIStream())
    try:
        assert await models.generate([], 'nvidia','Answer','lookup',stream=True)=='Complete OpenAI'
        events=list(queue._queue)
        fallback=next(i for i,e in enumerate(events) if e['type']=='provider_fallback')
        final=next(i for i,e in enumerate(events) if e.get('text')=='Complete OpenAI')
        assert any(e['type']=='answer_reset' for e in events[:fallback])
        assert final>fallback
    finally:
        await models.close()
