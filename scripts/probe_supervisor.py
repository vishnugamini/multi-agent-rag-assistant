"""Repeat one routing request to measure format reliability without running workers."""
import argparse
import asyncio
import json
from pathlib import Path
from app.config import settings
from app.events import Events
from app.graph import build_graph
from app.providers import Models


class Planned(Exception):pass


async def probe(index,semaphore):
    async with semaphore:
        raw=[];plan=None;error=None
        class ProbeModels(Models):
            async def generate(self,messages,provider,agent,reason,validator=None,stream=False):
                def capture(text):
                    raw.append(text);return validator(text)
                nonlocal plan
                plan=await super().generate(messages,provider,agent,reason,capture,stream)
                raise Planned()
        events=Events(asyncio.Queue());models=ProbeModels(settings(),events)
        try:
            await build_graph(models,None,events).ainvoke(dict(
                query='Compare GCS object generation checks and a transactional database for concurrent conversation updates. Explain failure recovery and design tradeoffs.',
                code='',selected_sources=[],history=[],findings=[],errors=[],dispatches=0,completed=[],next='',provider='nvidia',reason='',answer=''))
        except Planned:pass
        except Exception as exc:error=type(exc).__name__
        finally:await models.close()
        return dict(index=index,passed=plan is not None,plan=plan,error=error,raw=raw,calls=models.calls,trace=events.trace)


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,default=20);args=parser.parse_args()
    semaphore=asyncio.Semaphore(4)
    rows=await asyncio.gather(*(probe(i,semaphore) for i in range(args.count)))
    Path('output/supervisor-reliability.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps({'passed':sum(r['passed'] for r in rows),'total':len(rows),
        'internal_retries':sum(len(r['calls'])>1 for r in rows)}))
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
