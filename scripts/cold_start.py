"""Measure a deliberately idle tagged revision; require a new-instance log for proof."""
import argparse
import asyncio
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import subprocess
from time import perf_counter
import httpx
from scripts.scenarios import check


async def main():
    p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--revision',required=True)
    p.add_argument('--project',required=True);p.add_argument('--idle-seconds',type=int,default=960)
    args=p.parse_args();idle_started=datetime.now(timezone.utc)
    print('Idle measurement started',idle_started.isoformat(),flush=True)
    remaining=args.idle_seconds
    while remaining:
        step=min(30,remaining);await asyncio.sleep(step);remaining-=step
    started=datetime.now(timezone.utc);clock=perf_counter();events=[];arrivals=[]
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream('POST',args.url+'/api/chat',json={
            'query':'Search the LangGraph documentation and explain checkpoints in two sentences.'}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith('data: '):
                    events.append(json.loads(line[6:]));arrivals.append(perf_counter()-clock)
    failures,answer=check({},events)
    # System logs may arrive after the SSE request finishes.
    await asyncio.sleep(20)
    since=(started-timedelta(seconds=5)).isoformat()
    query=(f'resource.type="cloud_run_revision" AND resource.labels.revision_name="{args.revision}" '
           f'AND logName="projects/{args.project}/logs/run.googleapis.com%2Fvarlog%2Fsystem" '
           f'AND timestamp>="{since}"')
    logs=json.loads(subprocess.check_output(['gcloud','logging','read',query,
        '--project='+args.project,'--limit=30','--format=json'],text=True))
    cold_proven=any('Starting new instance' in entry.get('textPayload','') for entry in logs)
    report={'idle_started':idle_started.isoformat(),'request_started':started.isoformat(),
        'idle_wait_seconds':args.idle_seconds,'revision':args.revision,'url':args.url,
        'cold_start_proven_by_system_log':cold_proven,'turn_passed':not failures,
        'failures':failures,'events':events,'arrivals_seconds':arrivals,'system_logs':logs,'answer':answer}
    first=next((i for i,e in enumerate(events) if e['type']=='answer_delta'),None)
    report['client_ttft_seconds']=arrivals[first] if first is not None else None
    report['client_total_seconds']=arrivals[-1] if arrivals else None
    Path('output/cold-start.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'cold_start_proven':cold_proven,'passed':not failures,
        'metrics':next((e for e in events if e['type']=='metrics'),{})}),flush=True)
    if failures or not cold_proven:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
