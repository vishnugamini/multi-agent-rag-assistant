import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.tools import Tools
from app.config import Settings
from app.events import Events


@pytest.mark.asyncio
@pytest.mark.parametrize('agent,name',[('Research','analyze_python'),('Summary','search_corpus'),('Code','tavily_search')])
async def test_disallowed_tools_cannot_execute(agent,name):
    tools=Tools(Settings(_env_file=None),Events(asyncio.Queue()))
    with pytest.raises(ValueError,match='not allowed'):await tools.call(agent,name,{})
    assert not tools.timings


@pytest.mark.asyncio
async def test_mcp_error_returns_limited_evidence_without_crashing(monkeypatch):
    events=Events(asyncio.Queue());tools=Tools(Settings(_env_file=None),events)
    session=SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(isError=True)))
    monkeypatch.setattr(tools,'connect',AsyncMock(return_value=session))
    tools.schemas['search_corpus']={'actual':'search_corpus'}
    result=await tools.call('Research','search_corpus',{'query':'memory'})
    assert 'error' in result and not tools.sources
    assert tools.timings[-1]['success'] is False
    assert events.trace[-1]['type']=='tool_finished' and 'error' in events.trace[-1]


@pytest.mark.asyncio
async def test_discovery_outage_leaves_local_code_analysis_available(monkeypatch):
    events=Events(asyncio.Queue());tools=Tools(Settings(_env_file=None),events)
    monkeypatch.setattr(tools,'connect',AsyncMock(side_effect=RuntimeError('offline')))
    assert set(await tools.catalog('Code'))=={'analyze_python'}
    assert any(e['type']=='tool_unavailable' for e in events.trace)
