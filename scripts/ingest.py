"""Reproducible source snapshots and Pinecone ingestion. No ingestion at app startup."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

from app.config import settings


def normalize(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else 'Documentation'
    root = soup.find('main') or soup.find('article') or soup.body or soup
    for node in root.select('script,style,nav,footer,header,aside,button,svg'):
        node.decompose()
    for node in root.find_all('pre'):
        node.replace_with('\n```\n' + node.get_text() + '\n```\n')
    for level in range(1, 7):
        for node in root.find_all(f'h{level}'):
            node.replace_with('\n' + '#' * level + ' ' + node.get_text(' ', strip=True).replace('\u200b', '') + '\n')
    text = re.sub(r'\n{3,}', '\n\n', root.get_text('\n', strip=True))
    return title, text


def chunk_text(text):
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name='cl100k_base', chunk_size=750, chunk_overlap=100,
        separators=['\n## ', '\n### ', '\n\n', '\n', ' ', ''])
    # Keep ordinary code blocks intact. Oversize blocks must still be bounded.
    sections = re.split(r'(```[\s\S]*?```)', text)
    chunks, pending = [], ''
    for section in sections:
        if section.startswith('```') and len(section) < 5000:
            if pending.strip():
                chunks.extend(splitter.split_text(pending))
                pending = ''
            chunks.append(section)
        else:
            pending += '\n' + section
    if pending.strip():
        chunks.extend(splitter.split_text(pending))
    return chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch-only', action='store_true')
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    config = settings()
    root = Path('corpus')
    snapshots = root / 'snapshots'
    snapshots.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / 'manifest.json').read_text())
    records, report = [], []
    seen = set()
    with httpx.Client(timeout=40, follow_redirects=True, headers={'User-Agent': 'CSCI599-DocumentationStudy/1.0'}) as client:
        for source in manifest:
            doc_id = 'doc-' + hashlib.sha256(source['url'].encode()).hexdigest()[:12]
            try:
                response = client.get(source['url'])
                response.raise_for_status()
                title, text = normalize(response.text)
                digest = hashlib.sha256(text.encode()).hexdigest()
                if len(text) < 500:
                    raise ValueError('Insufficient source content')
                if digest in seen:
                    raise ValueError('Duplicate source content')
                seen.add(digest)
                chunks = chunk_text(text)
                stamp = datetime.now(timezone.utc).isoformat()
                for i, chunk in enumerate(chunks):
                    headings = re.findall(r'^#{1,6}\s+(.+)$', chunk, re.M)
                    records.append(dict(id=f'{doc_id}::{i:04d}', metadata=dict(text=chunk,
                        document_id=doc_id, title=title, url=source['url'], heading=headings[0] if headings else title,
                        chunk_order=i, topic=source['topic'], snapshot_date=stamp,
                        content_hash=digest, corpus_version=config.pinecone_namespace, kind='chunk')))
                (snapshots / f'{doc_id}.md').write_text(text)
                report.append(dict(**source, document_id=doc_id, title=title, hash=digest,
                                   snapshot_date=stamp, chunks=len(chunks), status='ok'))
                print(f'Fetched {doc_id}: {len(chunks)} chunks')
            except Exception as exc:
                report.append(dict(**source, status='failed', error=type(exc).__name__))
                print('Source failed:', source['url'], type(exc).__name__)
    (root / 'ingestion-report.json').write_text(json.dumps(report, indent=2))
    (root / 'chunks.jsonl').write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    successful = sum(r['status'] == 'ok' for r in report)
    if successful < 40 and not args.allow_partial:
        raise SystemExit(f'Only {successful} substantive pages fetched. Repair manifest before indexing, or use --allow-partial for development.')
    if args.fetch_only:
        print(f'Snapshot complete: {successful} pages, {len(records)} chunks. No embeddings or upserts performed.')
        return
    pc = Pinecone(api_key=config.pinecone_api_key)
    if config.pinecone_index not in pc.list_indexes().names():
        pc.create_index(name=config.pinecone_index, dimension=1536, metric='cosine',
                        spec=ServerlessSpec(cloud='aws', region='us-east-1'))
    for _ in range(60):
        if pc.describe_index(config.pinecone_index).status['ready']:
            break
        time.sleep(2)
    else:
        raise SystemExit('Pinecone index did not become ready')
    description = pc.describe_index(config.pinecone_index)
    if description.dimension != 1536:
        raise SystemExit('Existing index dimension does not match embedding model')
    index = pc.Index(config.pinecone_index)
    embeddings = OpenAI(api_key=config.openai_api_key, timeout=60, max_retries=1)
    tokens = 0
    try:
        for start in range(0, len(records), 64):
            batch = records[start:start+64]
            response = embeddings.embeddings.create(model=config.openai_embedding_model,
                                                    input=[r['metadata']['text'] for r in batch])
            tokens += response.usage.total_tokens
            index.upsert(vectors=[dict(**r, values=e.embedding) for r, e in zip(batch, response.data)],
                         namespace=config.pinecone_namespace)
    finally:
        embeddings.close()
    # Manifest vectors are non-searchable records for deterministic document reconstruction.
    docs = {}
    for record in records:
        docs.setdefault(record['metadata']['document_id'], []).append(record['id'])
    for doc_id, ids in docs.items():
        index.upsert(vectors=[dict(id=f'manifest:{doc_id}', values=[1.0]+[0.0]*1535,
                                  metadata={'kind': 'manifest', 'chunk_ids': ids})], namespace=config.pinecone_namespace)
    summary = dict(pages=successful, chunks=len(records), embedding_tokens=tokens,
                   index=config.pinecone_index, namespace=config.pinecone_namespace,
                   date=datetime.now(timezone.utc).isoformat())
    Path('output').mkdir(exist_ok=True)
    Path('output/ingestion.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
