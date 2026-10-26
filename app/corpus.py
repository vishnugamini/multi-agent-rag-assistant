import asyncio
from functools import cached_property
from langchain_core.runnables import RunnableLambda
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from app.config import settings


class Corpus:
    def __init__(self, config=None):
        self.config = config or settings()

    @cached_property
    def index(self):
        if not self.config.pinecone_api_key:
            raise ValueError('PINECONE_API_KEY is not configured')
        return Pinecone(api_key=self.config.pinecone_api_key).Index(self.config.pinecone_index)

    def search(self, query, top_k=5, topic_filter=None):
        return self.retrieval_pipeline().invoke(dict(query=query, top_k=top_k, topic_filter=topic_filter))

    @cached_property
    def embeddings(self):
        return OpenAIEmbeddings(model=self.config.openai_embedding_model,
            api_key=self.config.openai_api_key, check_embedding_ctx_length=False,
            max_retries=1, request_timeout=30)

    @cached_property
    def vector_store(self):
        return PineconeVectorStore(index=self.index, embedding=self.embeddings,
            text_key='text', namespace=self.config.pinecone_namespace)

    def retrieval_pipeline(self):
        """LCEL embedding -> vector retrieval, exposed through the shared MCP tool."""
        return RunnableLambda(self._embed_query) | RunnableLambda(self._retrieve)

    def _embed_query(self, request):
        vector = self.embeddings.embed_query(request['query'])
        return {**request, 'vector': vector}

    def _retrieve(self, request):
        kwargs = dict(k=min(10, max(1, request['top_k'])),
                      namespace=self.config.pinecone_namespace)
        kwargs['filter'] = {'kind': {'$eq': 'chunk'}}
        if request['topic_filter']:
            kwargs['filter'] = {'$and': [kwargs['filter'], {'topic': {'$eq': request['topic_filter']}}]}
        matches = self.vector_store.similarity_search_by_vector_with_score(request['vector'], **kwargs)
        return [dict(id=doc.id, score=score, text=doc.page_content, **doc.metadata) for doc, score in matches]

    def read_chunks(self, chunk_ids):
        ids = list(dict.fromkeys(chunk_ids))[:20]
        if not ids:
            return []
        found = self.index.fetch(ids=ids, namespace=self.config.pinecone_namespace).vectors
        return [dict(id=i, **found[i].metadata) for i in ids if i in found]

    def read_document(self, document_id):
        # Ingestion writes a manifest record with ordered IDs, never a query-time scan.
        manifest = self.index.fetch(ids=[f'manifest:{document_id}'], namespace=self.config.pinecone_namespace).vectors
        if not manifest:
            return []
        ids = manifest[f'manifest:{document_id}'].metadata['chunk_ids'][:20]
        return self.read_chunks(ids)


def augmentation_pipeline():
    """LCEL augmentation stage, used after MCP retrieval in the graph."""
    return RunnableLambda(lambda chunks: '\n\n'.join(
        f"[{c['id']}] {c.get('title', '')} / {c.get('heading', '')}\n{c.get('text', '')}" for c in chunks))
