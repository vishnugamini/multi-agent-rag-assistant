from mcp.server.fastmcp import FastMCP
from app.corpus import Corpus

server = FastMCP('agentic-corpus')
corpus = Corpus()


@server.tool()
def search_corpus(query: str, top_k: int = 5, topic_filter: str | None = None) -> list[dict]:
    """Search official AI engineering documentation. Returns evidence with citation IDs."""
    # Manifest records are excluded through a metadata filter in Corpus.search.
    return corpus.search(query, top_k, topic_filter)


@server.tool()
def read_chunks(chunk_ids: list[str]) -> list[dict]:
    """Read up to 20 exact corpus chunks by citation ID."""
    return corpus.read_chunks(chunk_ids)


@server.tool()
def read_document(document_id: str) -> list[dict]:
    """Read the first 20 ordered chunks of a corpus document."""
    return corpus.read_document(document_id)


if __name__ == '__main__':
    server.run(transport='stdio')
