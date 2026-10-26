"""Small real failure/persistence probes; normal ADC or explicit gcloud-token option."""
import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from app.config import settings
from app.events import Events
from app.providers import Models
from app.storage import GCSStore, StateConflict


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--use-gcloud-token',action='store_true')
    args=parser.parse_args()
    config=settings().model_copy(update={'nvidia_model':'invalid-model-for-fallback-test'})
    events=Events(asyncio.Queue());models=Models(config,events)
    report={}
    try:
        result=await models.generate([{'role':'user','content':'Reply with OK only.'}], 'nvidia','Research','Injected invalid NIM model to verify one-way recovery')
        report['fallback']={'passed':result.strip()=='OK' and models.openai_only,
            'calls':models.calls.copy(),'trace':events.trace.copy()}
        await models.generate([{'role':'user','content':'Reply with OK only.'}], 'openai','Supervisor','Verify independent Supervisor after fallback')
        report['supervisor_after_fallback']={'passed':models.calls[-1]['model']==config.supervisor_model,'call':models.calls[-1]}
    finally: await models.close()
    from google.cloud import storage
    credentials=None
    if args.use_gcloud_token:
        from google.oauth2.credentials import Credentials
        token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True).strip()
        credentials=Credentials(token=token)
    cid=str(uuid4());first=object.__new__(GCSStore);second=object.__new__(GCSStore)
    first.bucket=storage.Client(project=args.project,credentials=credentials).bucket(args.bucket)
    second.bucket=storage.Client(project=args.project,credentials=credentials).bucket(args.bucket)
    state,version=await first.load(cid)
    await first.save(cid,{'messages':[{'role':'user','content':'integration test'}],'turns':[]},version)
    restored,newversion=await second.load(cid)
    conflict=False
    try: await second.save(cid,{'messages':[],'turns':[]},version)
    except StateConflict: conflict=True
    report['gcs']={'passed':conflict and bool(restored['messages']) and newversion>0,
                   'conversation_id':cid,'independent_clients':True,'stale_write_rejected':conflict}
    path=Path('output/integrations-rubric.json');path.write_text(json.dumps(report,indent=2))
    print(json.dumps({name:value['passed'] for name,value in report.items()}))
    if not all(v['passed'] for v in report.values()): raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
