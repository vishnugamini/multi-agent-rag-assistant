import ast
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from time import perf_counter
from urllib.parse import quote

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


ALLOW = {
    'Research': {'search_corpus', 'read_chunks', 'tavily_search', 'tavily_extract'},
    'Code': {'search_corpus', 'read_chunks', 'analyze_python'},
    'Summary': {'read_chunks', 'read_document', 'tavily_extract'},
}


def analyze_python(code):
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {'valid_syntax': False, 'line': exc.lineno, 'message': exc.msg}
    return {'valid_syntax': True,
            'functions': [{'name': n.name, 'line': n.lineno, 'async': isinstance(n, ast.AsyncFunctionDef)}
                          for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
            'imports': [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))],
            'calls': [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)][:100],
            'note': 'Static syntax/structure inspection only; no execution or proof of correctness.'}


class Tools:
    """Sessions live and close within the owning request task (AnyIO cancel-scope safe)."""
    def __init__(self, config, events):
        self.config, self.events = config, events
        self.stack = AsyncExitStack()
        self.sessions = {}
        self.schemas = {}
        self.sources = {}
        self.timings = []

    async def __aenter__(self):
        await self.stack.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)

    async def connect(self, name):
        if name in self.sessions:
            return self.sessions[name]
        if name == 'corpus':
            # MCP's default child environment intentionally omits arbitrary API credentials.
            # Local .env loading can mask this; Cloud Run has environment secrets only.
            env = {name: getattr(self.config, name.lower()) for name in
                   ('OPENAI_API_KEY', 'OPENAI_EMBEDDING_MODEL', 'PINECONE_API_KEY', 'PINECONE_INDEX', 'PINECONE_NAMESPACE')}
            transport = stdio_client(StdioServerParameters(command=sys.executable, args=['-m', 'app.corpus_mcp'], env=env))
            read, write = await self.stack.enter_async_context(transport)
        else:
            if not self.config.tavily_api_key:
                raise ValueError('Tavily is not configured')
            url = 'https://mcp.tavily.com/mcp/?tavilyApiKey=' + quote(self.config.tavily_api_key, safe='')
            read, write, _ = await self.stack.enter_async_context(streamable_http_client(url))
        session = await self.stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            canonical = tool.name.replace('-', '_')
            self.schemas[canonical] = dict(server=name, actual=tool.name,
                                          description=tool.description, input_schema=tool.inputSchema)
        self.sessions[name] = session
        await self.events.emit('mcp_discovery', server=name, tools=[t.name for t in listed.tools])
        return session

    async def catalog(self, agent):
        for name in ('corpus', 'tavily'):
            if name == 'tavily' and agent == 'Code':
                continue
            try:
                await self.connect(name)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.events.emit('tool_unavailable', agent=agent, server=name,
                                       reason='MCP connection or discovery failed')
        catalog = {k: v for k, v in self.schemas.items() if k in ALLOW[agent]}
        if agent == 'Code':
            catalog['analyze_python'] = dict(server='local', description='Inspect pasted Python syntax and structure.',
                                             input_schema={'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']})
        return catalog

    async def call(self, agent, name, arguments):
        if name not in ALLOW[agent]:
            raise ValueError('Tool not allowed for this agent')
        started = perf_counter()
        server = 'local' if name == 'analyze_python' else ('tavily' if name.startswith('tavily_') else 'corpus')
        await self.events.emit('tool_started', agent=agent, server=server, tool=name, arguments=arguments)
        try:
            async with asyncio.timeout(45):
                if name == 'analyze_python':
                    result = analyze_python(arguments['code'])
                else:
                    session = await self.connect(server)
                    result = await session.call_tool(self.schemas[name]['actual'], arguments)
                    if result.isError:
                        raise ValueError('MCP tool returned an error')
                    if result.structuredContent:
                        result = result.structuredContent
                        if isinstance(result, dict) and set(result) == {'result'}:
                            result = result['result']
                    else:
                        text = '\n'.join(c.text for c in result.content if c.type == 'text')
                        try:
                            result = json.loads(text)
                        except json.JSONDecodeError:
                            result = {'text': text[:24000]}
            # Preserve corpus IDs and normalize web references for citation validation.
            if server == 'corpus':
                for chunk in result if isinstance(result, list) else []:
                    if 'id' in chunk:
                        self.sources[chunk['id']] = chunk
            if server == 'tavily' and isinstance(result, dict):
                for item in result.get('results', []):
                    if item.get('url'):
                        import hashlib
                        cid = 'web-' + hashlib.sha256(item['url'].encode()).hexdigest()[:12]
                        item['id'] = cid
                        self.sources[cid] = dict(id=cid, title=item.get('title', item['url']), url=item['url'],
                                                 text=(item.get('raw_content') or item.get('content') or '')[:16000])
            seconds = round(perf_counter() - started, 3)
            self.timings.append(dict(tool=name, seconds=seconds, success=True))
            await self.events.emit('tool_finished', agent=agent, server=server, tool=name, seconds=seconds,
                                   preview=json.dumps(result, ensure_ascii=False)[:1800])
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            seconds = round(perf_counter() - started, 3)
            self.timings.append(dict(tool=name, seconds=seconds, success=False))
            await self.events.emit('tool_finished', agent=agent, server=server, tool=name,
                                   seconds=seconds, error=type(exc).__name__)
            return {'error': 'Tool failed or timed out; do not claim it succeeded.'}
