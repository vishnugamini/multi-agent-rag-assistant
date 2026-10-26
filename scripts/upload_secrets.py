"""Read local settings; send secret bytes via stdin, never shell arguments."""
import os
import subprocess
from app.config import settings

project = os.environ['GCP_PROJECT_ID']
subprocess.run(['gcloud', 'services', 'enable', 'secretmanager.googleapis.com', '--project', project], check=True)
for name in ('OPENAI_API_KEY', 'NVIDIA_API_KEY', 'TAVILY_API_KEY', 'PINECONE_API_KEY'):
    value = getattr(settings(), name.lower())
    if not value:
        raise SystemExit(f'{name} is missing')
    exists = subprocess.run(['gcloud', 'secrets', 'describe', name, '--project', project],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not exists:
        subprocess.run(['gcloud', 'secrets', 'create', name, '--replication-policy=automatic', '--project', project], check=True)
    subprocess.run(['gcloud', 'secrets', 'versions', 'add', name, '--data-file=-', '--project', project],
                   input=value.encode(), check=True, stdout=subprocess.DEVNULL)
    print(f'Uploaded {name}')
