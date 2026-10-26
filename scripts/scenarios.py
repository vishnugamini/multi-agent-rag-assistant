"""Live rubric acceptance checks. Saves raw SSE evidence and exits nonzero on failure."""
import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
import httpx


def check(scenario, events):
    failures=[]
    def require(ok, message):
        if not ok: failures.append(message)
    kinds=[e['type'] for e in events]
    require(kinds.count('done')==1, 'Expected exactly one done event')
    require(bool(kinds) and kinds[-1]=='done', 'Done must be the final event')
    require('error' not in kinds, 'Turn emitted an error')
    require(any(e['type']=='done' and e.get('persisted') for e in events), 'Answer not durably saved')
    require('answer_delta' in kinds, 'No streamed answer')
    routes=[e for e in events if e['type']=='routing_decision']
    require(bool(routes) and all(e.get('reason') for e in routes), 'Missing routing rationale')
    supervisors=[e for e in routes if e.get('agent')=='Supervisor']
    require(bool(supervisors) and all(e.get('provider')=='openai' for e in supervisors), 'Supervisor must use OpenAI')
    require(all(e.get('model')==scenario.get('supervisor_model','gpt-6-luna') for e in supervisors), 'Unexpected Supervisor model')
    workers=[e['agent'] for e in events if e['type']=='agent_started' and e.get('agent') in ('Research','Code','Summary')]
    for agent in scenario.get('agents',[]): require(agent in workers, f'Missing {agent} worker')
    if scenario.get('order'):
        require(workers==scenario['order'], 'Unexpected worker order: '+str(workers))
    require(len(workers)==len(set(workers)), 'Duplicate worker execution')
    tools=[e for e in events if e['type']=='tool_finished' and not e.get('error')]
    if scenario.get('any_tools'):
        require(any(e.get('tool') in scenario['any_tools'] for e in tools), 'No successful required live-retrieval tool')
    for expected in scenario.get('tools',[]):
        require(any(e.get('tool')==expected for e in tools), 'Missing tool '+expected)
    for agent,tool in scenario.get('shared_tools',[]):
        require(any(e.get('agent')==agent and e.get('tool')==tool for e in tools), f'{agent} did not invoke {tool}')
    if scenario.get('citations'):
        require(any(e['type']=='citations' and e.get('sources') for e in events), 'No verified source citations')
    if scenario.get('generation_provider'):
        require(any(e['type']=='model_finished' and e.get('agent')!='Supervisor' and e.get('success') and e.get('provider')==scenario['generation_provider'] for e in events), 'Expected generation provider not exercised successfully')
    answer=''
    for event in events:
        if event['type']=='answer_reset': answer=''
        if event['type']=='answer_delta': answer+=event['text']
    require(bool(answer.strip()), 'Empty final answer')
    for phrase in scenario.get('answer_contains',[]):
        require(phrase.lower() in answer.lower(), 'Answer missing '+phrase)
    sequences=[e.get('sequence') for e in events]
    require(sequences==sorted(set(sequences)), 'Event sequence is not unique and increasing')
    return failures,answer


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8012')
    parser.add_argument('--ids',default='')
    parser.add_argument('--concurrency',type=int,default=1)
    parser.add_argument('--output',default='output/scenarios.json')
    args=parser.parse_args()
    scenarios=json.loads(Path('evaluation/scenarios.json').read_text())
    conversations={}; reports=[]
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=300) as client:
        async def run_scenario(scenario):
            events=[]; arrivals=[]; started=perf_counter()
            group=scenario.get('conversation',scenario['id'])
            async with client.stream('POST',args.base_url+'/api/chat',json=dict(
                query=scenario['query'],code=scenario.get('code',''),
                source_ids=scenario.get('source_ids',[]),conversation_id=conversations.get(group))) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        event=json.loads(line[6:]); events.append(event)
                        arrivals.append(round(perf_counter()-started,3))
                        if event['type']=='turn_started': conversations[group]=event['conversation_id']
            failures,answer=check(scenario,events)
            cid=conversations.get(group)
            reload_check=None
            if cid and not failures:
                saved=await client.get(args.base_url+'/api/conversations/'+cid)
                reload_check={'status':saved.status_code, 'matches':saved.status_code==200 and saved.json().get('messages',[])[-1:]==[{'role':'assistant','content':answer}]}
                if not reload_check['matches']:
                    failures.append('Conversation reload does not match streamed answer')
            report=dict(id=scenario['id'],passed=not failures,failures=failures,
                        answer=answer,arrivals_seconds=arrivals,events=events,reload_check=reload_check)
            reports.append(report)
            reports.sort(key=lambda r:next(i for i,s in enumerate(scenarios) if s['id']==r['id']))
            target.write_text(json.dumps(reports,indent=2))
            print(scenario['id'], 'PASS' if not failures else 'FAIL', failures, flush=True)
        groups={}
        for scenario in scenarios:
            if args.ids and scenario['id'] not in args.ids.split(','):continue
            groups.setdefault(scenario.get('conversation',scenario['id']),[]).append(scenario)
        semaphore=asyncio.Semaphore(max(1,args.concurrency))
        async def run_group(group):
            async with semaphore:
                for scenario in group:await run_scenario(scenario)
        await asyncio.gather(*(run_group(group) for group in groups.values()))
    if any(not r['passed'] for r in reports): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
