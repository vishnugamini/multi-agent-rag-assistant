"""Real, small service probes; reports status without credential values."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.events import Events
from app.providers import Models
from app.storage import GCSStore
from app.tools import Tools


async def main():
    config = settings()
    queue = asyncio.Queue()
    events = Events(queue)
    models = Models(config, events)
    report = {}
    try:
        for provider in ('nvidia', 'openai'):
            # Disable cross-provider success masking: record actual provider separately.
            models.openai_only = False
            offset = len(models.calls)
            try:
                answer = await models.generate([{'role': 'user', 'content': 'Reply with OK only.'}],
                                               provider, 'Smoke', 'Direct provider probe')
                report[provider] = {'ok': bool(answer), 'calls': models.calls[offset:]}
            except Exception as exc:
                report[provider] = {'ok': False, 'error': type(exc).__name__, 'calls': models.calls[offset:]}
        async with Tools(config, events) as tools:
            for name in ('corpus', 'tavily'):
                try:
                    await tools.connect(name)
                    report[f'{name}_mcp'] = {'ok': True, 'tools': [k for k,v in tools.schemas.items() if v['server'] == name]}
                except Exception as exc:
                    report[f'{name}_mcp'] = {'ok': False, 'error': type(exc).__name__}
            result = await tools.call('Research', 'search_corpus', {'query': 'LangGraph state persistence', 'top_k': 2})
            report['retrieval'] = {'ok': isinstance(result, list) and bool(result), 'count': len(result)}
            result = await tools.call('Research', 'tavily_search', {'query': 'LangGraph official persistence documentation', 'max_results': 2})
            report['live_search'] = {'ok': not (isinstance(result, dict) and 'error' in result)}
        if config.gcs_state_bucket:
            try:
                gcs = GCSStore(config.gcs_state_bucket)
                cid = str(uuid4())
                await gcs.save(cid, {'messages': [], 'turns': [], 'probe': True}, 0)
                state, version = await gcs.load(cid)
                report['gcs'] = {'ok': state.get('probe') is True and version > 0, 'conversation_id': cid}
            except Exception as exc:
                report['gcs'] = {'ok': False, 'error': type(exc).__name__}
        else:
            report['gcs'] = {'ok': False, 'error': 'Not configured'}
    finally:
        await models.close()
    Path('output').mkdir(exist_ok=True)
    Path('output/smoke.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
