import re
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4


def clean(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if any(s in k.lower() for s in ('api_key', 'authorization', 'apikey')) else clean(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?:sk-proj-|sk-|nvapi-|tvly-|pcsk_)[\w-]+', '[redacted]', value)
        return re.sub(r'''(tavilyApiKey=)(?!\[redacted\])[^&\s`"'<>]+''', r'\1[redacted]', value)
    return value


class Events:
    def __init__(self, queue):
        self.queue = queue
        self.turn_id = uuid4().hex
        self.seq = 0
        self.started = perf_counter()
        self.first_token = None
        self.trace = []

    async def emit(self, kind, **data):
        self.seq += 1
        if kind == 'answer_delta' and self.first_token is None:
            self.first_token = perf_counter() - self.started
        event = dict(type=kind, turn_id=self.turn_id, sequence=self.seq,
                     timestamp=datetime.now(timezone.utc).isoformat(), **clean(data))
        if kind != 'answer_delta':
            self.trace.append(event)
        await self.queue.put(event)
