"""HTTP-only checks for deployment, persistence, citations, isolation and streaming."""
import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
import httpx
from scripts.scenarios import check


async def turn(client,url,query,cid=None):
    events=[];arrivals=[];start=perf_counter()
    async with client.stream('POST',url+'/api/chat',json={'query':query,'conversation_id':cid}) as response:
        response.raise_for_status()
        assert response.headers['content-type'].startswith('text/event-stream')
        async for line in response.aiter_lines():
            if line.startswith('data: '):
                events.append(json.loads(line[6:]));arrivals.append(perf_counter()-start)
    failures,answer=check({},events)
    assert not failures,failures
    return {'events':events,'answer':answer,'arrivals':arrivals}


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',required=True)
    args=parser.parse_args();url=args.base_url
    before=json.loads(Path('output/scenarios-rubric.json').read_text())
    memory=next(r for r in before if r['id']=='memory-set')
    cid=memory['events'][0]['conversation_id']
    old_revision=next(e['revision'] for e in memory['events'] if e['type']=='metrics')
    report={}
    async with httpx.AsyncClient(timeout=300) as client:
        health=(await client.get(url+'/api/healthz')).json()
        assert health['state_backend']=='gcs' and all(health['configured'].values())
        report['health']=health
        restored=await turn(client,url,'What project nickname did I tell you? Reply with the nickname.',cid)
        assert 'Cedar' in restored['answer']
        new_revision=next(e['revision'] for e in restored['events'] if e['type']=='metrics')
        assert new_revision!=old_revision
        report['cross_revision']={'passed':True,'from':old_revision,'to':new_revision,'conversation_id':cid,'turn':restored}
        first,second=await asyncio.gather(
            turn(client,url,'Remember my test project nickname is Ruby. Reply only Ruby.'),
            turn(client,url,'Remember my test project nickname is Cobalt. Reply only Cobalt.'))
        first_cid=first['events'][0]['conversation_id'];second_cid=second['events'][0]['conversation_id']
        assert first_cid!=second_cid
        first_state=(await client.get(url+'/api/conversations/'+first_cid)).json()
        second_state=(await client.get(url+'/api/conversations/'+second_cid)).json()
        assert 'Cobalt' not in json.dumps(first_state['messages']) and 'Ruby' not in json.dumps(second_state['messages'])
        report['parallel_session_isolation']={'passed':True,'first':first,'second':second}
        citation=next(s for r in before for e in r['events'] if e['type']=='citations' for s in e.get('sources',[]) if s['id'].startswith('doc-'))
        source=await client.get(url+'/api/sources/'+citation['id']);assert source.status_code==200
        assert source.json()['id']==citation['id'] and source.json()['text']
        report['source_endpoint']={'passed':True,'id':citation['id']}
        report['static']={}
        for path in ['/','/static/app.js','/static/style.css']:
            response=await client.get(url+path);assert response.status_code==200
            report['static'][path]=response.status_code
        for payload in [{'query':''},{'query':'x'*12001},{'query':'valid','conversation_id':'bad'}]:
            assert (await client.post(url+'/api/chat',json=payload)).status_code==422
        report['validation']={'passed':True}
    Path('output/cloud-contracts.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':True,'revision':new_revision,'checks':list(report)}))


if __name__=='__main__':asyncio.run(main())
