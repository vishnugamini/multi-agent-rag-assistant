"""One-way NVIDIA failover, shared by planning, workers, and answer streaming."""
import asyncio
import json
from time import perf_counter

import httpx
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, APIStatusError


class InvalidOutput(ValueError):
    pass


def json_object(text):
    text = text.strip().lstrip('\ufeff').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Some compatible endpoints wrap a valid object in explanatory text
        # despite the requested format. Accept one object, never two plans.
        start = text.find('{')
        if start < 0:
            raise
        result, end = json.JSONDecoder().raw_decode(text[start:])
        if '{' in text[start + end:]:
            raise InvalidOutput('Ambiguous structured output')
    if not isinstance(result, dict):
        raise InvalidOutput('Expected a JSON object')
    return result


class Models:
    def __init__(self, config, events):
        self.config, self.events = config, events
        self.openai_only = False
        self.calls = []
        timeout = httpx.Timeout(config.model_timeout, connect=10, write=30, pool=10)
        self.clients = {
            'openai': AsyncOpenAI(api_key=config.openai_api_key or 'unconfigured', timeout=timeout, max_retries=0),
            'nvidia': AsyncOpenAI(api_key=config.nvidia_api_key or 'unconfigured',
                                  base_url=config.nvidia_base_url, timeout=timeout, max_retries=0),
        }

    def model(self, provider, agent=None):
        if provider == 'openai' and agent == 'Supervisor':
            return self.config.supervisor_model
        return self.config.openai_model if provider == 'openai' else self.config.nvidia_model

    def has_key(self, provider):
        return bool(getattr(self.config, f'{provider}_api_key'))

    @staticmethod
    def transient(exc):
        return isinstance(exc, (APIConnectionError, APITimeoutError, httpx.TimeoutException,
                                InvalidOutput, json.JSONDecodeError)) or (
            isinstance(exc, APIStatusError) and (exc.status_code in (408, 429) or exc.status_code >= 500))

    @staticmethod
    def failure_label(exc):
        if isinstance(exc, APIStatusError):
            return f'HTTP {exc.status_code}'
        return type(exc).__name__  # Never expose URLs, headers, or provider error bodies.

    async def close(self):
        for client in self.clients.values():
            await client.close()

    def record(self, provider, agent, started, usage, success):
        counts = usage or {}
        if hasattr(counts, 'model_dump'):
            counts = counts.model_dump()
        inp = counts.get('input_tokens', counts.get('prompt_tokens', 0))
        out = counts.get('output_tokens', counts.get('completion_tokens', 0))
        price_role = 'supervisor' if provider == 'openai' and agent == 'Supervisor' else provider
        price_in = getattr(self.config, f'{price_role}_input_per_million')
        price_out = getattr(self.config, f'{price_role}_output_per_million')
        estimate = (inp * price_in + out * price_out) / 1e6 if price_in is not None and price_out is not None and counts else None
        record = dict(provider=provider, model=self.model(provider, agent), agent=agent,
                      seconds=round(perf_counter() - started, 3), input_tokens=inp,
                      output_tokens=out, usage_available=bool(counts), estimated_usd=estimate, success=success)
        self.calls.append(record)
        return record

    async def generate(self, messages, provider, agent, reason, validator=None, stream=False):
        selected = provider
        provider = 'openai' if self.openai_only else provider
        await self.events.emit('routing_decision', agent=agent, selected_provider=selected,
                               provider=provider, model=self.model(provider, agent),
                               reason='OpenAI retained after NVIDIA failure in this turn' if selected != provider else reason)
        while True:
            for attempt in range(2):
                started, visible, usage = perf_counter(), False, None
                try:
                    if not self.has_key(provider):
                        raise RuntimeError(f'{provider} credential missing')
                    result = ''
                    if provider == 'openai':
                        effort = self.config.supervisor_reasoning_effort if agent == 'Supervisor' else self.config.openai_reasoning_effort
                        kwargs = dict(model=self.model(provider, agent), input=messages,
                                      reasoning={'effort': effort},
                                      max_output_tokens=4096, store=False)
                        if agent == 'Supervisor':
                            kwargs['text'] = {'format': {'type': 'json_schema', 'name': 'supervisor_plan',
                                'strict': True, 'schema': {'type': 'object', 'additionalProperties': False,
                                    'properties': {
                                        'next': {'type': 'string', 'enum': ['Research', 'Code', 'Summary', 'finish']},
                                        'provider': {'type': 'string', 'enum': ['nvidia', 'openai']},
                                        'reason': {'type': 'string'}},
                                    'required': ['next', 'provider', 'reason']}}}
                        if stream:
                            async with self.clients[provider].responses.stream(**kwargs) as response:
                                async for event in response:
                                    if event.type == 'response.output_text.delta':
                                        result += event.delta
                                        visible = True
                                        await self.events.emit('answer_delta', text=event.delta)
                                final = await response.get_final_response()
                                usage = final.usage
                                if final.status != 'completed':
                                    raise InvalidOutput('Incomplete OpenAI response')
                        else:
                            response = await self.clients[provider].responses.create(**kwargs)
                            result, usage = response.output_text, response.usage
                            if response.status != 'completed':
                                raise InvalidOutput('Incomplete OpenAI response')
                    else:
                        kwargs = dict(model=self.model(provider), messages=messages, max_tokens=4096,
                                      extra_body={'chat_template_kwargs': {'enable_thinking': False}})
                        if stream:
                            finished = False
                            response = await self.clients[provider].chat.completions.create(
                                **kwargs, stream=True, stream_options={'include_usage': True})
                            try:
                                async for event in response:
                                    if event.usage:
                                        usage = event.usage
                                    if event.choices:
                                        delta = event.choices[0].delta.content or ''
                                        if delta:
                                            result += delta
                                            visible = True
                                            await self.events.emit('answer_delta', text=delta)
                                        if event.choices[0].finish_reason not in (None, 'stop'):
                                            raise InvalidOutput('Incomplete NVIDIA response')
                                        if event.choices[0].finish_reason == 'stop':
                                            finished = True
                            finally:
                                await response.close()
                            if not finished:
                                raise InvalidOutput('NVIDIA stream ended before completion')
                        else:
                            response = await self.clients[provider].chat.completions.create(**kwargs)
                            result = response.choices[0].message.content or ''
                            usage = response.usage
                            if response.choices[0].finish_reason != 'stop':
                                raise InvalidOutput('Incomplete NVIDIA response')
                    if not result.strip():
                        raise InvalidOutput('Empty model response')
                    value = validator(result) if validator else result
                    record = self.record(provider, agent, started, usage, True)
                    await self.events.emit('model_finished', **record)
                    return value
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.record(provider, agent, started, usage, False)
                    if visible:
                        await self.events.emit('answer_reset', reason='Provider stream interrupted; regenerating answer')
                    retry = attempt == 0 and self.transient(exc)
                    delay = 1
                    if isinstance(exc, APIStatusError):
                        try:
                            requested = float(exc.response.headers.get('retry-after', 1))
                            if requested > 5:
                                retry = False
                            delay = max(0, min(5, requested))
                        except ValueError:
                            retry = False
                    await self.events.emit('model_error', agent=agent, provider=provider,
                                           error=self.failure_label(exc), retry=retry,
                                           **({'output_characters': len(result), 'output_prefix': result[:200]}
                                              if agent == 'Supervisor' and isinstance(exc, json.JSONDecodeError) else {}))
                    if retry:
                        if validator and isinstance(exc, (InvalidOutput, ValueError)):
                            messages = messages + [{'role': 'user', 'content': getattr(validator, 'repair_prompt', 'Return valid JSON matching the required schema exactly.')}]
                        await asyncio.sleep(delay)
                        continue
                    if provider == 'openai':
                        raise RuntimeError('OpenAI request failed; no reverse fallback is configured') from None
                    break
            self.openai_only = True
            await self.events.emit('provider_fallback', agent=agent, from_provider='nvidia', to_provider='openai',
                                   reason='NVIDIA request failed; remaining calls use OpenAI for this turn')
            provider = 'openai'
