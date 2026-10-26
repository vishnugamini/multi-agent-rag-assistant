from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', env_ignore_empty=True)
    openai_api_key: str = ''
    openai_model: str = 'gpt-6.1-sol'
    supervisor_model: str = 'gpt-6-luna'
    supervisor_reasoning_effort: str = 'none'
    supervisor_input_per_million: float | None = None
    supervisor_output_per_million: float | None = None
    openai_reasoning_effort: str = 'low'
    openai_embedding_model: str = 'text-embedding-3-small'
    nvidia_api_key: str = ''
    nvidia_model: str = 'nvidia/nemotron-3.5-lightning-30b-a3b'
    nvidia_base_url: str = 'https://integrate.api.nvidia.com/v1'
    tavily_api_key: str = ''
    pinecone_api_key: str = ''
    pinecone_index: str = 'agentic-ai-docs'
    pinecone_namespace: str = 'docs-v1'
    gcs_state_bucket: str = ''
    state_backend: str = 'local'
    local_state_dir: str = '.local/conversations'
    model_timeout: float = 30
    openai_input_per_million: float = 2
    openai_output_per_million: float = 10
    nvidia_input_per_million: float | None = None
    nvidia_output_per_million: float | None = None


@lru_cache
def settings():
    return Settings()
