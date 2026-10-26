import asyncio
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
import httpx
import pytest
from openai import APIConnectionError, APIStatusError
from app.config import Settings
from app.events import Events
from app.providers import Models, InvalidOutput


def config():
    return Settings(_env_file=None, openai_api_key='test', nvidia_api_key='test')


def nvidia_result(text='OK'):
    return Obj(choices=[Obj(message=Obj(content=text), finish_reason='stop')], usage=None)


def openai_result():
    return Obj(output_text='OpenAI answer', usage=None, status='completed')


@pytest.mark.asyncio
async def test_nvidia_retry_falls_back_and_sticks_for_turn(monkeypatch):
    monkeypatch.setattr('app.providers.asyncio.sleep', AsyncMock())
    queue = asyncio.Queue()
    models = Models(config(), Events(queue))
    nvidia = models.clients['nvidia'].chat.completions
    openai = models.clients['openai'].responses
    monkeypatch.setattr(nvidia, 'create', AsyncMock(side_effect=APIConnectionError(request=httpx.Request('POST', 'https://example.com'))))
    monkeypatch.setattr(openai, 'create', AsyncMock(return_value=openai_result()))
    try:
        assert await models.generate([], 'nvidia', 'Research', 'lookup') == 'OpenAI answer'
        assert await models.generate([], 'nvidia', 'Summary', 'summary') == 'OpenAI answer'
        assert nvidia.create.await_count == 2
        assert openai.create.await_count == 2
        assert models.openai_only
        assert sum(e['type']=='provider_fallback' for e in list(queue._queue)) == 1
    finally:
        await models.close()


@pytest.mark.asyncio
async def test_no_reverse_fallback(monkeypatch):
    monkeypatch.setattr('app.providers.asyncio.sleep', AsyncMock())
    models = Models(config(), Events(asyncio.Queue()))
    monkeypatch.setattr(models.clients['openai'].responses, 'create', AsyncMock(side_effect=APIConnectionError(request=httpx.Request('POST', 'https://example.com'))))
    nv = AsyncMock(return_value=nvidia_result())
    monkeypatch.setattr(models.clients['nvidia'].chat.completions, 'create', nv)
    try:
        with pytest.raises(RuntimeError, match='no reverse fallback'):
            await models.generate([], 'openai', 'Code', 'complex')
        nv.assert_not_called()
    finally:
        await models.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404])
async def test_permanent_nvidia_error_skips_retry(monkeypatch, status):
    models = Models(config(), Events(asyncio.Queue()))
    response = httpx.Response(status, request=httpx.Request('POST','https://example.com'))
    nv=AsyncMock(side_effect=APIStatusError('failure', response=response, body=None))
    monkeypatch.setattr(models.clients['nvidia'].chat.completions, 'create', nv)
    monkeypatch.setattr(models.clients['openai'].responses, 'create', AsyncMock(return_value=openai_result()))
    try:
        await models.generate([], 'nvidia', 'Supervisor', 'plan')
        assert nv.await_count == 1
    finally:
        await models.close()


@pytest.mark.asyncio
async def test_invalid_structured_output_retries_before_fallback(monkeypatch):
    monkeypatch.setattr('app.providers.asyncio.sleep', AsyncMock())
    models = Models(config(), Events(asyncio.Queue()))
    nv=AsyncMock(return_value=nvidia_result('not valid JSON'))
    monkeypatch.setattr(models.clients['nvidia'].chat.completions, 'create', nv)
    monkeypatch.setattr(models.clients['openai'].responses, 'create', AsyncMock(return_value=openai_result()))
    def validate(text):
        if text != 'OpenAI answer':
            raise InvalidOutput('schema mismatch')
        return text
    try:
        assert await models.generate([], 'nvidia', 'Supervisor', 'plan', validate) == 'OpenAI answer'
        assert nv.await_count == 2
    finally:
        await models.close()


@pytest.mark.asyncio
async def test_cancel_does_not_fallback(monkeypatch):
    models = Models(config(), Events(asyncio.Queue()))
    monkeypatch.setattr(models.clients['nvidia'].chat.completions,'create',AsyncMock(side_effect=asyncio.CancelledError()))
    try:
        with pytest.raises(asyncio.CancelledError):
            await models.generate([], 'nvidia', 'Research', 'lookup')
        assert not models.openai_only
    finally:
        await models.close()


@pytest.mark.asyncio
async def test_supervisor_uses_luna_without_changing_worker_model(monkeypatch):
    models=Models(config(), Events(asyncio.Queue()))
    create=AsyncMock(return_value=openai_result())
    monkeypatch.setattr(models.clients['openai'].responses,'create',create)
    try:
        await models.generate([], 'openai', 'Supervisor', 'plan')
        assert create.call_args.kwargs['model']=='gpt-6-luna'
        assert create.call_args.kwargs['reasoning']=={'effort':'none'}
        assert create.call_args.kwargs['text']['format']['strict'] is True
        assert models.calls[-1]['model']=='gpt-6-luna'
        assert models.calls[-1]['estimated_usd'] is None
        await models.generate([], 'openai', 'Code', 'complex')
        assert create.call_args.kwargs['model']=='gpt-6.1-sol'
        assert models.calls[-1]['model']=='gpt-6.1-sol'
    finally:
        await models.close()


@pytest.mark.parametrize('text', ['\ufeff{"next":"finish"}', 'Here is the plan:\n{"next":"finish"}', '```json\n{"next":"finish"}\n```'])
def test_single_structured_object_tolerates_transport_wrappers(text):
    from app.providers import json_object
    assert json_object(text)=={'next':'finish'}


def test_multiple_plans_are_rejected():
    from app.providers import json_object
    with pytest.raises(InvalidOutput,match='Ambiguous'):
        json_object('{"next":"finish"}\n{"next":"Research"}')
