# Rubric verification

Tested 2026-10-26T18:32:07.527757+00:00. Full-rubric test revision: `agentic-ai-00014-zx8`.

87 deterministic checks passed. Live scenarios: 18/18 passed (18 defined). Frontend SSE framing: 244 packet-split cases plus byte-split UTF-8 passed.
Mapped to Assignment_2_Description.pdf sections 2-5 and 7 (rubric pages 14-16).
First full run: 17/18. The live-web case had one failed immediate reload assertion; its later saved answer matched exactly, ten concurrent reads all returned HTTP 200 and matching content, and an explicit rerun passed. The original failure is retained in previous_attempts. Its immediate cause was not captured, so it remains an unreproduced observation rather than a claimed repair.
Direct HTTP tests exercised the public deployment. Browser checks separately confirmed chat submission, visible model routing, and opening a source excerpt.

## Grading criteria coverage

| Criterion | Weight | Evidence |
|---|---:|---|
| Multi-agent orchestration | 25% | Compiled graph; three worker prompts/allowlists; research → summary and research + code scenarios; worker-outage, duplicate-dispatch and execution-limit tests. |
| RAG quality | 20% | 51 source pages / 2,462 chunks; LangChain PineconeVectorStore and LCEL retrieval/augmentation/generation; verified citations; all four RAGAS metrics over 24 fixed questions. |
| LLM routing | 15% | Luna Supervisor with strict structured output; NVIDIA and Sol both succeed in ordinary workloads; reasons, actual models, usage and failures recorded. |
| Frontend | 15% | FastAPI/static vanilla JS; real incremental SSE; routing/trace views; source dialog; packet-framing and served-asset checks. |
| Deployment/scalability | 15% | Public Cloud Run; fresh Linux dependency build; external GCS, cross-revision memory, concurrent-session isolation and stale-write rejection. Cold-start result below. |
| Shared MCP | 10% | Research and Code both successfully call corpus search in the shared-MCP scenario; actual Tavily Remote MCP search/extract for live evidence. |

These checks establish observed rubric coverage, not a guaranteed grade or correctness on every possible prompt.

## Live cases

| Case | Passed | Workers observed | Successful tools |
|---|---|---|---|
| simple | True | Research | Research:search_corpus |
| complex | True | Research, Summary | Research:search_corpus, Research:tavily_extract, Research:tavily_search |
| code | True | Code, Summary | Code:analyze_python, Code:search_corpus |
| live | True | Research, Summary | Research:search_corpus, Research:tavily_extract, Research:tavily_search |
| summary | True | Summary | none |
| simple-followup | True | Summary | none |
| complex-followup | True | Research, Summary | Research:search_corpus |
| shared-mcp | True | Research, Code | Code:analyze_python, Code:search_corpus, Research:search_corpus |
| research-summary | True | Research, Summary | Research:search_corpus |
| summary-followup | True | Summary | none |
| memory-set | True | direct answer | none |
| memory-recall | True | direct answer | none |
| unrehearsed | True | Research, Summary | Research:search_corpus |
| syntax-error | True | Code | Code:analyze_python, Code:search_corpus |
| missing-sources | True | Summary | Summary:read_document |
| greeting | True | direct answer | none |
| selected-chunk | True | Summary | Summary:read_chunks |
| selected-document | True | Summary | Summary:read_document |

Each scenario checks exactly one final `done`, no turn error, a nonempty streamed answer, an increasing event sequence, OpenAI/Luna supervision, routing rationale, and a saved answer matching the final stream. Task-specific assertions check worker order, successful tools, verified citations, provider success or remembered content. The runner exits nonzero on failure.

## Failures found and repaired

- Research could return a plausible answer without executing retrieval. Required successful tool groups now guard worker completion; selected-source summaries also require a source read.
- The old runner accepted `done` even when a later error occurred. The new runner rejects that sequence and checks persisted content.
- Explicit research-then-summary requests could finish after Research. Current-request requirements are checked against completed state before finishing.
- Source-prefixed and parent-document citations could lose all source links. Normalization accepts those forms but links only actual retrieved excerpts; unknown IDs stay unavailable.
- Credential redaction could make the displayed answer differ from the saved answer and remove a Markdown delimiter. Redaction is now idempotent and the final saved/streamed text agrees.
- Structured-output parsing tolerates one valid JSON object wrapped in prose, Markdown or a byte-order mark; multiple plans are rejected. Cloud-only format failures are retained in earlier diagnostic evidence.
- Free-form Luna output could need a JSON repair retry. Supervisor calls now use a strict routing schema.
- Retrieval used the Pinecone SDK directly. The assignment-specific LangChain PineconeVectorStore path and LCEL sequences now execute with pinned compatible dependencies.
- Root pytest discovery picked up duplicate tests from an extracted ZIP. Collection is scoped to the source test directory.

The current-information assertion accepts successful Tavily search or extraction: reading an official live page is valid current retrieval. It does not require an unnecessary search call first.

## Failure and state checks

Live probes injected an invalid NVIDIA model and observed successful OpenAI recovery, then confirmed the Supervisor still used Luna. Independent GCS clients restored the same object and a stale writer was rejected. Deterministic tests separately cover transient retries, permanent errors, malformed JSON, interrupted streams, cancellation without fallback, no reverse fallback, unavailable tools and worker outages.
Cross-revision conversation recall passed from `agentic-ai-00008-dwf` to `agentic-ai-00014-zx8`. Two concurrent independent sessions had different IDs and did not share messages.

## RAGAS and latency

- faithfulness: 0.9467; scored 24/24 questions.
- answer_relevancy: 0.7406; scored 24/24 questions.
- context_precision: 0.8788; scored 24/24 questions.
- context_recall: 0.9583; scored 24/24 questions.

Paired-provider RAGAS generation uses identical retrieved context and bypasses orchestration to isolate provider behavior. The live scenario suite separately verifies the complete graph. Per-query retrieval/model/total timing, TTFT, token usage and known cost estimates are in `docs/evaluation.md` and the raw evidence.

Idle test: `agentic-ai-00009-mx7`, idle for 900 seconds. New-instance system log verified: True. Turn passed: True. Client TTFT 35.156s; client completion 36.693s (including startup/network). App-only TTFT 19.793s.
The isolated cold-test revision uses the same rebuilt dependencies and retrieval implementation as the final revision; subsequent changes hardened worker completion, citations and structured-output parsing. This is a measured cold-start sample, not a claim about every request or the final revision's exact cold latency.

## Limits and submission checks

RAGAS is an automated judge, not a human correctness certificate. The weakest cases included an overextended JSON-body explanation and retrieval of streaming examples without the iterator-description prose. The measured context-recall score for the streaming question was 0.0. The report preserves these outcomes rather than excluding them.
Completed GCS turns survive replacement; interrupted graph execution does not resume. Context is bounded. The public demo uses unguessable session IDs rather than account authentication. Some successful turns can report an MCP cleanup warning after durable save.
A clean ZIP extraction/dependency install passed the same tests. The archive excludes runtime state and working credentials. `PROCESS_LOG.md` has four sections and meets the 200–300-word requirement; the student must review and express the personal reflection truthfully before submission.

## Reproduce

```bash
python -m pytest -q
node tests/sse-parser.mjs
python -m scripts.scenarios --base-url LIVE_URL --output output/scenarios-rubric-final.json
python -m scripts.evaluate
python -m scripts.package
python -m scripts.check_package
```

## Interface cleanup follow-up

Revision `agentic-ai-00016-djl` removes the logo/wordmark and the Code or sources panel. Ordinary replies no longer request general-knowledge source labels, and obsolete placeholder labels are removed when displaying saved replies. Python code blocks pasted in chat reach the Code agent without a separate input panel.

Validation: 89 automated tests passed; saved-answer cleanup and JavaScript syntax/framing checks passed. Direct HTTP checks verified removed markup, a natural greeting without fake sources, and actual Code/analyze_python execution for Python pasted into chat. The earlier full-rubric results above retain their original revision/date. Raw follow-up evidence is in `docs/evidence/interface-removal-verification.json`.
