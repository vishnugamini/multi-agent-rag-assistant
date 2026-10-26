from pathlib import Path
import re


def test_every_resolved_dependency_is_exactly_pinned():
    lines=[line.strip() for line in Path('requirements.txt').read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    assert all(re.fullmatch(r'[\w.-]+(?:\[[\w,.-]+\])?==[^\s]+',line) for line in lines)


def test_container_is_nonroot_and_honors_port():
    source=Path('Dockerfile').read_text()
    assert 'USER appuser' in source and 'PORT' in source and 'python:3.13-slim' in source
    assert 'node_modules' not in source


def test_architecture_documents_memory_tools_and_state():
    source=Path('docs/architecture.md').read_text()
    for term in ['mermaid','Supervisor','Research','Code','Summary','Pinecone','Tavily','if_generation_match','provider','findings']:
        assert term in source
