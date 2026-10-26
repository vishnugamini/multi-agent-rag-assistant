"""Inspect the submission ZIP without printing secret values."""
from pathlib import Path
from zipfile import ZipFile
import json
import re
from dotenv import dotenv_values


def main():
    path=Path('output/assignment2-source.zip')
    secrets=[str(v).encode() for k,v in dotenv_values('.env').items() if k.endswith('_API_KEY') and v]
    problems=[]
    with ZipFile(path) as archive:
        for name in archive.namelist():
            parts=Path(name).parts
            if any(p in ('.env','.venv','.local','.git','node_modules') for p in parts):
                problems.append('Excluded path: '+name)
            data=archive.read(name)
            if any(secret in data for secret in secrets):problems.append('Working credential detected in '+name)
            if re.search(rb'(?:sk-proj-|nvapi-|tvly-|pcsk_)[A-Za-z0-9_-]{40,}',data):
                problems.append('Credential-shaped value detected in '+name)
        report={'passed':not problems,'file_count':len(archive.namelist()),'bytes':path.stat().st_size,
                'working_credentials_checked':len(secrets),'problems':problems}
    Path('output/package-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if problems:raise SystemExit(1)


if __name__=='__main__':main()
