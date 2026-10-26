# Process log

## AI tools used

Codex assisted with architecture discussion, implementation, debugging, and verification. The application uses NVIDIA Nemotron 3.5 Lightning, OpenAI GPT-6 Luna supervision, and GPT-6.1 Sol. GPT-6.1 Sol also judges retrieval answers through RAGAS. OpenAI text-embedding-3-small produces corpus and evaluation embeddings. Exact dependency versions are recorded in requirements.txt.

## Development narrative

Development started from an empty workspace. The system was divided into provider adapters, an MCP corpus server, specialized workers, a supervisor graph, storage, and the streaming interface. Initial integration exposed an MCP SDK rename and missing RAGAS dependencies. Compatible versions were pinned. Pinecone rejected all-zero document-manifest vectors, so manifest records received a nonzero vector and were excluded from retrieval. Live scenarios also exposed stale conversation interpretation and repeated worker delegation; current requests were separated from history and completed-worker guards were added.

## Verification narrative

Verification included deterministic tests, real provider calls, MCP discovery and invocation, corpus ingestion, browser submission, and paired-provider evaluation over 24 fixed questions. Four RAGAS metrics were measured rather than estimated. Tests exercise NVIDIA retry/fallback, stream reset, cancellation, absence of reverse fallback, stale storage writes, and graph delegation. Deployment and persistence evidence is recorded separately in the evaluation report so local success does not stand in for cloud verification.

## What was learned

Observed implementation findings include that GCS persistence needs conditional writes, an MCP integration must execute actual protocol calls, and a configured routing policy needs behavioral verification. AI-generated integration code required corrections against installed libraries and real service responses. This section describes verified development findings; the student's personal reflection and understanding must be reviewed and expressed by the student before submission.
