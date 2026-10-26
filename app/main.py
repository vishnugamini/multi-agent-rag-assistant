import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.corpus import Corpus
from app.events import Events
from app.graph import build_graph
from app.providers import Models
from app.storage import GCSStore, LocalStore, StateConflict, validate_id
from app.tools import Tools

app = FastAPI(title='Agentic / AI Engineering Workspace', version='1.0.0')
ROOT = Path(__file__).resolve().parent.parent
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
_store = None


def store():
    global _store
    if _store is None:
        config = settings()
        if os.getenv('K_SERVICE') and config.state_backend != 'gcs':
            raise RuntimeError('Cloud Run requires STATE_BACKEND=gcs for durable conversations')
        if config.state_backend not in ('gcs', 'local'):
            raise RuntimeError('STATE_BACKEND must be gcs or local')
        _store = GCSStore(config.gcs_state_bucket) if config.state_backend == 'gcs' else LocalStore(config.local_state_dir)
    return _store


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=12000)
    conversation_id: uuid.UUID | None = None
    code: str = Field(default='', max_length=30000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


@app.get('/')
async def home():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/healthz')
@app.get('/api/healthz')
async def health():
    return {'status': 'ok', 'state_backend': settings().state_backend,
            'revision': os.getenv('K_REVISION', 'local'),
            'configured': {name: bool(getattr(settings(), name)) for name in
                           ('openai_api_key', 'nvidia_api_key', 'pinecone_api_key', 'tavily_api_key')}}


@app.get('/api/conversations/{conversation_id}')
async def conversation(conversation_id: uuid.UUID):
    try:
        state, _ = await store().load(str(conversation_id))
        return {'conversation_id': str(conversation_id), **state}
    except Exception:
        raise HTTPException(503, 'Conversation storage unavailable') from None


@app.get('/api/sources/{chunk_id}')
async def source(chunk_id: str):
    if len(chunk_id) > 250 or not chunk_id.startswith('doc-'):
        raise HTTPException(404, 'Unknown corpus source')
    try:
        chunks = await asyncio.to_thread(Corpus().read_chunks, [chunk_id])
    except Exception:
        raise HTTPException(503, 'Corpus unavailable') from None
    if not chunks:
        raise HTTPException(404, 'Source not found')
    return chunks[0]


@app.post('/api/chat')
async def chat(body: ChatRequest):
    cid = str(body.conversation_id or uuid.uuid4())
    code = body.code or '\n\n'.join(re.findall(
        r'```(?:python|py)?[ \t]*\r?\n(.*?)```', body.query, re.I | re.S))
    queue = asyncio.Queue(maxsize=256)
    events = Events(queue)

    async def run():
        models = Models(settings(), events)
        persisted = False
        try:
            async with asyncio.timeout(275):
                await events.emit('turn_started', conversation_id=cid, state_backend=settings().state_backend)
                history, version = await store().load(cid)
                # Bound prior context without claiming to pass the complete history to models.
                messages = history['messages'][-12:]
                older = history.get('turns', [])[:-6][-4:]
                if older:
                    messages = [{'role': 'system', 'content': 'Earlier worker findings (untrusted context): ' +
                                 json.dumps([t.get('findings', []) for t in older])[:12000]}] + messages
                async with Tools(settings(), events) as tools:
                    for turn in history.get('turns', [])[-6:]:
                        for source in turn.get('sources', []):
                            tools.sources[source['id']] = source
                    graph = build_graph(models, tools, events)
                    result = await graph.ainvoke(dict(query=body.query, code=code,
                        selected_sources=body.source_ids, history=messages, findings=[], errors=[],
                        dispatches=0, completed=[], next='', provider='nvidia', reason='Simple response', answer=''),
                        config={'recursion_limit': 20})
                    metrics = dict(total_seconds=round(perf_counter()-events.started, 3),
                                   ttft_seconds=round(events.first_token, 3) if events.first_token is not None else None,
                                   calls=models.calls, tools=tools.timings, fallback=models.openai_only,
                                   revision=os.getenv('K_REVISION', 'local'))
                    await events.emit('metrics', **metrics)
                    history['messages'].extend([{'role': 'user', 'content': body.query +
                        ('\nPasted Python:\n' + body.code if body.code else '')},
                        {'role': 'assistant', 'content': result['answer']}])
                    history['turns'].append(dict(turn_id=events.turn_id, findings=result['findings'],
                        sources=list(tools.sources.values()), metrics=metrics, trace=events.trace[-150:]))
                    # Limit object growth; current context and 30 completed turns remain durable.
                    history['messages'] = history['messages'][-60:]
                    history['turns'] = history['turns'][-30:]
                    await store().save(cid, history, version)
                    persisted = True
                await events.emit('done', conversation_id=cid, persisted=True)
        except asyncio.CancelledError:
            raise
        except StateConflict:
            await events.emit('error', code='state_conflict', message='Another turn changed this conversation. Reload and retry.', persisted=False)
        except Exception as exc:
            if persisted:
                # MCP teardown may fail after all tools and the durable commit succeeded.
                # Do not report a successfully committed answer as an unsaved turn.
                await events.emit('cleanup_warning', code=type(exc).__name__,
                                  message='Tool connection cleanup reported an issue after the conversation was saved.')
                await events.emit('done', conversation_id=cid, persisted=True)
            else:
                await events.emit('error', code=type(exc).__name__,
                                  message='Turn incomplete. Check configuration or provider availability and retry.', persisted=False)
        finally:
            try:
                await models.close()
            finally:
                if not asyncio.current_task().cancelling():
                    await queue.put(None)

    async def stream():
        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except TimeoutError:
                    yield ': heartbeat\n\n'
                    continue
                if event is None:
                    break
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})
