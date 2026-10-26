# Agentic: AI Engineering Assistant

FastAPI + LangGraph supervisor with Research, Code, and Summary workers. Pinecone contains indexed official documentation, Tavily supplies current evidence over Remote MCP, and GCS stores completed conversation turns. The vanilla JavaScript frontend streams real execution events and answer tokens.

[Live demo](https://agentic-ai-118532811016.us-west1.run.app) · [Architecture](docs/architecture.md) · [Evaluation](docs/evaluation.md)

## Local setup

Python 3.13 is the supported runtime. All resolved dependencies are pinned exactly in `requirements.txt`. `requirements.in` records direct dependencies; MCP is kept on its compatible 1.x API and RAGAS uses the compatible LangChain community package.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill provider credentials and your selected storage configuration.
python -m scripts.ingest
uvicorn app.main:app --host 127.0.0.1 --port 8012
```

Open http://127.0.0.1:8012. `STATE_BACKEND=local` is development-only persistence in `.local/conversations`. For GCS use `STATE_BACKEND=gcs`, set `GCS_STATE_BUCKET`, and authenticate Application Default Credentials. Cloud Run rejects local conversation storage. The corpus MCP process runs inside the same container over stdio; it is a real MCP server, not a function renamed as MCP.

Credentials belong only in ignored `.env` files locally or Secret Manager in deployment. Never include working keys in the submission ZIP. No credentials are sent to the browser. The public demo uses unguessable conversation IDs as capability tokens; it does not provide accounts or identity-based authorization. Do not use it for private or production data.

## Corpus and tools

`corpus/manifest.json` defines the source URLs. Ingestion writes normalized snapshots, a source/hash report, and chunk records locally, then embeds and upserts them to a versioned Pinecone namespace. It requires at least 40 successful substantive pages by default. Use `--fetch-only` to inspect sources before spending embedding calls. `--allow-partial` is a development override, not a claim that the corpus floor is satisfied.

Use a fresh namespace for each published ingestion; only switch the application after successful ingestion. Pinecone stores text/metadata plus embeddings, with ordered document manifests for exact reads. Chunk records have `kind=chunk`; manifest records are excluded from search. `read_document` intentionally returns at most 20 chunks. The corpus tool descriptions expose that bound.

Research and Code share `search_corpus`. Summary has source reading and Tavily extract. Code also has a Python AST analyzer; it does not execute submitted code. Every worker has a distinct system prompt and allowlist. Tool requests are model-selected validated JSON actions, executed through the MCP client; they do not depend on a provider-specific native tool API.

## Routing and failover

The Supervisor uses OpenAI `gpt-6-luna` with reasoning disabled (`none`). NVIDIA handles simple questions; GPT-6.1 Sol handles complex analysis and contextual synthesis. Worker selection and provider selection are separate decisions. The Sol worker/answer calls use Responses with `reasoning.effort=low`; `none` is unsupported for Sol. Supervisor configuration is independent of worker configuration.

NVIDIA transient failures retry once, then fall back to OpenAI. Permanent NVIDIA errors skip retry. Failed structured output is validated/retried. A partial answer is cleared before regeneration. After fallback, all remaining calls in the turn use OpenAI. Completed tool results remain in the worker context and are not re-executed automatically. OpenAI transient errors retry once and never trigger reverse fallback. User cancellation does not trigger provider fallback.

## Verify

```bash
python -m pytest -q
python -m scripts.smoke
python -m scripts.scenarios --base-url http://127.0.0.1:8012
python -m scripts.evaluate
python -m scripts.package
# Optional frontend framing test (Node is used only for testing, not in the container):
node tests/sse-parser.mjs
```

Evaluation uses the fixed 24 questions in `evaluation/questions.json` and a separate 18-scenario behavioral suite with explicit pass/fail assertions. `--limit 2` is a pipeline smoke check; `--reuse-answers` reruns judging without regenerating saved answers. The RAGAS Responses adapter issues independent requests instead of forwarding unsupported `n` or temperature parameters. Results are written to `output/` and summarized in `docs/evaluation.md`. Measured outcomes and limits are distinguished there. `docs/testing.md` maps assertions, live cases, failure probes, and observed intermittent failures to the rubric.

## Deploy on a fresh GCP project

1. Install/authenticate the official Google Cloud CLI. If the local project tool installation exists, run `bash scripts/gcp-login.sh`; otherwise use your normal `gcloud auth login` and `gcloud auth application-default login`.
2. Verify the chosen project's billing account is the one holding the education credit. Export the project ID, region, and a globally unique bucket name.
3. Enable Secret Manager and upload the four local credential values using the helper. It passes secret bytes over stdin.
4. Run deployment. The script enables required APIs, creates a private uniform-access bucket, service identity and Artifact Registry repository, grants bucket object access and per-secret read access, builds the image, and deploys publicly.

```bash
export GCP_PROJECT_ID=YOUR_PROJECT_ID
export GCP_REGION=us-west1
export GCS_STATE_BUCKET=YOUR_GLOBALLY_UNIQUE_BUCKET
# For the project-local CLI installation:
export PATH="$PWD/.local/google-cloud-sdk/bin:$PATH"
export CLOUDSDK_CONFIG="$PWD/.local/gcloud-config"
export CLOUDSDK_PYTHON="$PWD/.venv/bin/python"
python -m scripts.upload_secrets
bash scripts/deploy.sh
```

The caller needs permission to enable APIs, build/deploy, manage the named service identity and its scoped permissions, create the bucket/repository, and create/access the project secrets. The Cloud Build identity needs Artifact Registry write permission under the project's build policy. The runtime has no project-wide Editor role.

Cloud Run defaults: 1 CPU, 1 GiB, min 0/max 2 instances, concurrency 5, request timeout 300 seconds, region `us-west1`. The container uses Python 3.13 slim, runs non-root, and honors injected `PORT`. GCS history uses generation preconditions; overlapping commits return a conflict rather than silently overwriting. A lost connection can leave an incomplete turn, and there is no interrupted-graph resume claim.

After deployment, run behavioral checks against the live URL, inspect both providers and shared MCP calls, and create a conversation before deploying a new revision. Restore it afterward to verify actual instance-independent persistence. Record cold-start timing separately from warm requests; do not label local startup timing as a Cloud Run cold start. Use `/api/healthz` for the deployed connection check; `/healthz` is also registered locally, but the Cloud Run Google frontend returned its own 404 for that path during verification.

For code/static-only updates, `bash scripts/redeploy-code.sh` reuses the current revision's immutable image digest as the dependency base. A fresh deployment or dependency change must use the full `scripts/deploy.sh` path.

## Cost and access

Model configuration: Supervisor `gpt-6-luna`, workers/answers `gpt-6.1-sol`, `nvidia/nemotron-3.5-lightning-30b-a3b`, `text-embedding-3-small`. API access was separately probed during development; access can change. NVIDIA price fields default to unknown rather than claiming free usage. Luna price fields are independently configurable; the verified Standard rate is $0.10 input/$0.50 output per million tokens ([model page](https://developers.openai.com/api/docs/models/gpt-6-luna), checked 2026-10-26). OpenAI generation estimates use configurable standard input/output rates; cached pricing, failed attempts with missing usage, and non-generation services are not fully accounted for.

As of the development check on 2026-10-26, the OpenAI model page listed $2 input/$10 output per million tokens. Verify current terms before submission: [OpenAI](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [NVIDIA](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b), [Pinecone](https://www.pinecone.io/pricing/), [Tavily](https://www.tavily.com/pricing), [Cloud Storage](https://cloud.google.com/storage/pricing), [Cloud Run](https://cloud.google.com/run/pricing).

Education credits cover eligible GCP charges under their terms, not separately billed third-party API services. Create a $10 GCP budget alert in Billing; an alert does not enforce a spending cap. The image includes evaluation dependencies for a single reproducible dependency set; runtime optimization can separate those later.

## Submission

`python -m scripts.package` creates `output/assignment2-source.zip` from an allowlist. It excludes `.env`, virtual environments, local credentials, runtime state, and fetched index artifacts. Include the live Cloud Run URL separately. Do not submit until deployment and final evaluation requirements in `docs/evaluation.md` are completed. Update the process log with your own actual learning and verification; it does not invent a personal reflection.
