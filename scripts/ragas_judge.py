"""RAGAS adapter for Responses: never forwards unsupported temperature/n parameters."""
import asyncio
from openai import AsyncOpenAI, OpenAI
from ragas.llms import BaseRagasLLM
from langchain_core.outputs import Generation, LLMResult


class ResponsesJudge(BaseRagasLLM):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def kwargs(self, prompt):
        return dict(model=self.config.openai_model, input=prompt.to_string(),
                    reasoning={'effort': self.config.openai_reasoning_effort},
                    max_output_tokens=8192, store=False)

    def is_finished(self, response):
        return all(g.generation_info.get('finished', False) for group in response.generations for g in group)

    def generate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        with OpenAI(api_key=self.config.openai_api_key, timeout=90, max_retries=1) as client:
            outputs = [client.responses.create(**self.kwargs(prompt)) for _ in range(n)]
        return LLMResult(generations=[[Generation(text=r.output_text, generation_info={'finished':r.status=='completed'}) for r in outputs]])

    async def agenerate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        async with AsyncOpenAI(api_key=self.config.openai_api_key, timeout=90, max_retries=1) as client:
            outputs = await asyncio.gather(*(client.responses.create(**self.kwargs(prompt)) for _ in range(n)))
        return LLMResult(generations=[[Generation(text=r.output_text, generation_info={'finished':r.status=='completed'}) for r in outputs]])
