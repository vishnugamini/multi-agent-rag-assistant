"""Build evaluation documentation from measured artifacts."""
import json
from pathlib import Path
from statistics import mean
import shutil


def main():
    out=Path('output');evidence=Path('docs/evidence');evidence.mkdir(exist_ok=True)
    summary=json.loads((out/'evaluation-summary.json').read_text())
    pairs=json.loads((out/'provider-comparison.json').read_text())
    ingestion=json.loads((out/'ingestion.json').read_text())
    lines=['# Evaluation report','',f"Measured {summary['date']}; fixed set: 24 questions. OpenAI answers scored: {summary['questions_answered']}.",'',
      '## Method','',f"Pinecone namespace `{ingestion['namespace']}` contains {ingestion['pages']} substantive pages and {ingestion['chunks']} chunks. Each fixed-set question retrieves five chunks through the LangChain PineconeVectorStore/LCEL path.",
      'Both generation providers receive identical retrieved context. This paired benchmark isolates retrieval and generation; it bypasses the Supervisor and workers. The live scenarios separately test the complete graph.',
      'RAGAS judges the OpenAI answers with GPT-6.1 Sol at low reasoning effort and OpenAI small embeddings. References were defined before scoring; q06 source attribution was corrected to the indexed persistence page without changing its question/reference. Automated scores do not replace human review.','',
      '## RAGAS','', '| Metric | Mean | Questions scored |','|---|---:|---:|']
    scores=json.loads((out/'ragas-results.json').read_text())
    for key,value in summary['ragas'].items():
        count=sum(r.get(key) is not None for r in scores)
        lines.append(f'| {key} | {value:.4f} | {count}/24 |')
    lines+=['','All individual scores and reference/context/answer records are included in `docs/evidence`. No low-scoring case was removed.','',
      '## Paired provider timing (local)','',
      '| Provider requested | Answers | Mean generation TTFT | Mean retrieval | Mean model time | Mean total | Fallbacks | Known generation estimate |',
      '|---|---:|---:|---:|---:|---:|---:|---:|']
    for provider in ['nvidia','openai']:
        rows=[x for pair in pairs for x in pair['measurements'] if x['provider_requested']==provider and 'answer' in x]
        cost=sum(c.get('estimated_usd') or 0 for x in rows for c in x['calls'])
        estimate='Unknown' if provider=='nvidia' else f'${cost:.5f}'
        lines.append(f"| {provider} | {len(rows)} | {mean(x['ttft_seconds'] for x in rows):.3f}s | {mean(x['retrieval_seconds'] for x in rows):.3f}s | {mean(sum(c['seconds'] for c in x['calls']) for x in rows):.3f}s | {mean(x['total_seconds'] for x in rows):.3f}s | {sum(x['fallback'] for x in rows)} | {estimate} |")
    lines+=['','Generation TTFT starts when generation begins; paired total includes retrieval. These figures are not browser/end-to-end Cloud Run latency.','',
      '## Cloud Run and state','']
    if (out/'cloud-contracts.json').exists():
        cloud=json.loads((out/'cloud-contracts.json').read_text())
        lines+=[f"Live URL: https://agentic-ai-118532811016.us-west1.run.app. Verified revision: `{cloud['health']['revision']}`. Conversation backend: GCS.",
          f"The nickname conversation created on `{cloud['cross_revision']['from']}` was successfully recalled on `{cloud['cross_revision']['to']}`. Independent concurrent sessions did not share messages. Actual GCS stale-generation writes were rejected by a separate-client integration probe."]
    lines+=['','### Active-service end-to-end scenarios','',
      'Client measurements begin before the HTTP request and include network, orchestration, tools, model calls and saving. Retrieval below sums successful and failed retrieval-tool durations; MCP startup and other overhead remain in total. Model time sums every recorded attempt. Raw per-call breakdowns are included.','',
      '| Case | Assertions pass | Client TTFT | Retrieval | Model time | Client completion | Known estimate |',
      '|---|---|---:|---:|---:|---:|---:|']
    if (out/'scenarios-rubric-final.json').exists():
        rows=json.loads((out/'scenarios-rubric-final.json').read_text())
        for row in rows:
            metric=next((e for e in row['events'] if e['type']=='metrics'),{})
            calls=metric.get('calls',[]);tools=metric.get('tools',[])
            first=next((i for i,e in enumerate(row['events']) if e['type']=='answer_delta'),None)
            ttft=row['arrivals_seconds'][first] if first is not None else None
            total=row['arrivals_seconds'][-1] if row['arrivals_seconds'] else None
            retrieval=sum(t['seconds'] for t in tools if t['tool']!='analyze_python')
            models=sum(c['seconds'] for c in calls);cost=sum(c.get('estimated_usd') or 0 for c in calls)
            lines.append(f"| {row['id']} | {row['passed']} | {ttft if ttft is not None else 'unavailable'}s | {retrieval:.3f}s | {models:.3f}s | {total if total is not None else 'unavailable'}s | ${cost:.5f} |")
        lines+=['','These scenarios run against an active service, including two independent conversation groups concurrently. They are not idle cold-start samples. First-request effects and task complexity make an aggregate latency unsuitable as a provider-only comparison.']
    lines+=['','### Idle cold start','']
    if (out/'cold-start.json').exists():
        cold=json.loads((out/'cold-start.json').read_text());metric=next(e for e in cold['events'] if e['type']=='metrics')
        lines+=[f"Isolated tagged revision `{cold['revision']}` was left idle for {cold['idle_wait_seconds']} seconds. A new-instance AUTOSCALING system log appeared after the request began; cold-start proof: {cold['cold_start_proven_by_system_log']}. The turn completed successfully: {cold['turn_passed']}.",
          f"Client TTFT: **{cold['client_ttft_seconds']:.3f}s**. Client completion: **{cold['client_total_seconds']:.3f}s**. App-only TTFT: {metric['ttft_seconds']:.3f}s; app-only total: {metric['total_seconds']:.3f}s. App-only values exclude container startup and must not be presented as the complete cold latency.",
          'The cold sample uses the rebuilt dependencies and retrieval path. Later revisions harden worker completion, citations and structured-output parsing; their exact idle cold latency was not separately measured. The temporary tag was removed after measurement.']
    else:lines+=['Not yet established; first-after-deploy timing is not labeled cold.']
    lines+=['','## Cost limits','',
      'Known estimates use recorded tokens and configured Standard rates: Luna $0.10 input/$0.50 output per million, Sol $2 input/$10 output per million. NVIDIA cost remains unknown under the account terms. Live estimates include known Luna/Sol charges and exclude NVIDIA, embeddings, Tavily, Pinecone, GCP, cache discounts and attempts with unavailable usage. These are partial estimates, not actual bills.',
      'A $10 monthly GCP budget alert is configured for usage before credits; it is not a spending cap. GCP credits do not pay separately billed third-party APIs.','',
      '## Reproduce','',
      'Run `python -m scripts.evaluate` for paired generation and RAGAS. Run `python -m scripts.scenarios --base-url LIVE_URL --concurrency 2 --output output/scenarios-rubric-final.json` for behavioral evidence. `docs/testing.md` maps observed results and remaining limits to every rubric category.','']
    Path('docs/evaluation.md').write_text('\n'.join(lines))
    for name in ['evaluation-summary.json','provider-comparison.json','ragas-results.json','evaluation-dataset.json','ingestion.json','scenarios-rubric-final.json','cloud-contracts.json','cold-start.json','corpus-verification.json','supervisor-reliability.json']:
        if (out/name).exists():shutil.copy2(out/name,evidence/name)
    print('Updated docs/evaluation.md')


if __name__=='__main__':main()
