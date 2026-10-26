"""Allowlist-based submission archive; excludes secrets, caches, and runtime state."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent.parent
files = ['pytest.ini', 'README.md', 'PROCESS_LOG.md', 'requirements.txt', 'requirements.in', '.env.example', 'Dockerfile', 'Dockerfile.update', '.dockerignore', '.gcloudignore', '.gitignore', 'corpus/ingestion-report.json']
folders = ['app', 'static', 'scripts', 'tests', 'docs', 'evaluation', 'corpus/snapshots']
paths = [root / f for f in files] + [root / 'corpus/manifest.json']
for folder in folders:
    paths.extend(p for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
(root / 'output').mkdir(exist_ok=True)
with ZipFile(root / 'output/assignment2-source.zip', 'w', ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        if path.exists():
            archive.write(path, str(path.relative_to(root)))
print('Created output/assignment2-source.zip')
