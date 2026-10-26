# Evaluation report

Measured 2026-10-26T18:05:23.316959+00:00; fixed set: 24 questions. OpenAI answers scored: 24.

## Method

Pinecone namespace `docs-v1` contains 51 substantive pages and 2462 chunks. Each fixed-set question retrieves five chunks through the LangChain PineconeVectorStore/LCEL path.
Both generation providers receive identical retrieved context. This paired benchmark isolates retrieval and generation; it bypasses the Supervisor and workers. The live scenarios separately test the complete graph.
RAGAS judges the OpenAI answers with GPT-6.1 Sol at low reasoning effort and OpenAI small embeddings. References were defined before scoring; q06 source attribution was corrected to the indexed persistence page without changing its question/reference. Automated scores do not replace human review.

## RAGAS

| Metric | Mean | Questions scored |
|---|---:|---:|
| faithfulness | 0.9467 | 24/24 |
| answer_relevancy | 0.7406 | 24/24 |
| context_precision | 0.8788 | 24/24 |
| context_recall | 0.9583 | 24/24 |

All individual scores and reference/context/answer records are included in `docs/evidence`. No low-scoring case was removed.

## Paired provider timing (local)

| Provider requested | Answers | Mean generation TTFT | Mean retrieval | Mean model time | Mean total | Fallbacks | Known generation estimate |
|---|---:|---:|---:|---:|---:|---:|---:|
| nvidia | 24 | 0.388s | 0.563s | 3.986s | 4.552s | 0 | Unknown |
| openai | 24 | 1.492s | 0.563s | 4.714s | 5.279s | 0 | $0.11599 |

Generation TTFT starts when generation begins; paired total includes retrieval. These figures are not browser/end-to-end Cloud Run latency.

## Cloud Run and state

Live URL: https://agentic-ai-118532811016.us-west1.run.app. Verified revision: `agentic-ai-00014-zx8`. Conversation backend: GCS.
The nickname conversation created on `agentic-ai-00008-dwf` was successfully recalled on `agentic-ai-00014-zx8`. Independent concurrent sessions did not share messages. Actual GCS stale-generation writes were rejected by a separate-client integration probe.

### Active-service end-to-end scenarios

Client measurements begin before the HTTP request and include network, orchestration, tools, model calls and saving. Retrieval below sums successful and failed retrieval-tool durations; MCP startup and other overhead remain in total. Model time sums every recorded attempt. Raw per-call breakdowns are included.

| Case | Assertions pass | Client TTFT | Retrieval | Model time | Client completion | Known estimate |
|---|---|---:|---:|---:|---:|---:|
| simple | True | 9.619s | 1.313s | 8.101s | 9.656s | $0.00012 |
| complex | True | 40.866s | 3.809s | 60.157s | 55.008s | $0.09623 |
| code | True | 28.523s | 1.347s | 24.988s | 32.912s | $0.01951 |
| live | True | 26.031s | 2.024s | 19.763s | 28.92s | $0.00024 |
| summary | True | 13.452s | 0.000s | 12.090s | 18.219s | $0.00021 |
| simple-followup | True | 22.79s | 0.000s | 18.310s | 26.258s | $0.00026 |
| complex-followup | True | 35.205s | 1.498s | 34.962s | 43.323s | $0.06276 |
| shared-mcp | True | 39.304s | 1.526s | 38.229s | 47.532s | $0.02378 |
| research-summary | True | 25.176s | 1.226s | 18.509s | 27.237s | $0.00022 |
| summary-followup | True | 11.2s | 0.000s | 6.390s | 13.521s | $0.00017 |
| memory-set | True | 1.79s | 0.000s | 1.634s | 1.853s | $0.00006 |
| memory-recall | True | 1.475s | 0.000s | 1.428s | 1.674s | $0.00006 |
| unrehearsed | True | 19.436s | 0.941s | 12.453s | 21.381s | $0.00021 |
| syntax-error | True | 12.752s | 0.956s | 14.779s | 22.216s | $0.00249 |
| missing-sources | True | 13.03s | 0.545s | 5.557s | 14.008s | $0.00012 |
| greeting | True | 1.69s | 0.000s | 2.095s | 2.324s | $0.00006 |
| selected-chunk | True | 12.577s | 0.709s | 6.094s | 14.435s | $0.00013 |
| selected-document | True | 18.276s | 0.890s | 15.069s | 24.109s | $0.00015 |

These scenarios run against an active service, including two independent conversation groups concurrently. They are not idle cold-start samples. First-request effects and task complexity make an aggregate latency unsuitable as a provider-only comparison.

### Idle cold start

Isolated tagged revision `agentic-ai-00009-mx7` was left idle for 900 seconds. A new-instance AUTOSCALING system log appeared after the request began; cold-start proof: True. The turn completed successfully: True.
Client TTFT: **35.156s**. Client completion: **36.693s**. App-only TTFT: 19.793s; app-only total: 20.594s. App-only values exclude container startup and must not be presented as the complete cold latency.
The cold sample uses the rebuilt dependencies and retrieval path. Later revisions harden worker completion, citations and structured-output parsing; their exact idle cold latency was not separately measured. The temporary tag was removed after measurement.

## Cost limits

Known estimates use recorded tokens and configured Standard rates: Luna $0.10 input/$0.50 output per million, Sol $2 input/$10 output per million. NVIDIA cost remains unknown under the account terms. Live estimates include known Luna/Sol charges and exclude NVIDIA, embeddings, Tavily, Pinecone, GCP, cache discounts and attempts with unavailable usage. These are partial estimates, not actual bills.
A $10 monthly GCP budget alert is configured for usage before credits; it is not a spending cap. GCP credits do not pay separately billed third-party APIs.

## Reproduce

Run `python -m scripts.evaluate` for paired generation and RAGAS. Run `python -m scripts.scenarios --base-url LIVE_URL --concurrency 2 --output output/scenarios-rubric-final.json` for behavioral evidence. `docs/testing.md` maps observed results and remaining limits to every rubric category.
