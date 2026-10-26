import asyncio
import json
import os
from pathlib import Path
from uuid import UUID


class StateConflict(Exception):
    pass


def validate_id(value):
    return str(UUID(value))


class LocalStore:
    """Development only. CAS protected within one application process."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = asyncio.Lock()

    async def load(self, conversation_id):
        path = self.directory / f'{validate_id(conversation_id)}.json'
        async with self.lock:
            if not path.exists():
                return {'messages': [], 'turns': []}, 0
            data = json.loads(path.read_text())
            return data['state'], data['version']

    async def save(self, conversation_id, state, version):
        path = self.directory / f'{validate_id(conversation_id)}.json'
        async with self.lock:
            current = json.loads(path.read_text())['version'] if path.exists() else 0
            if current != version:
                raise StateConflict('Conversation changed. Reload and retry your turn.')
            self.directory.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'state': state, 'version': version + 1}))
            os.replace(temp, path)


class GCSStore:
    def __init__(self, bucket):
        if not bucket:
            raise ValueError('GCS_STATE_BUCKET is required for GCS persistence')
        from google.cloud import storage
        self.bucket = storage.Client().bucket(bucket)

    async def load(self, conversation_id):
        def read():
            from google.api_core.exceptions import NotFound
            blob = self.bucket.blob(f'conversations/{validate_id(conversation_id)}.json')
            try:
                blob.reload()
                generation = int(blob.generation)
                # Pin the read to the same version as the CAS token.
                return json.loads(blob.download_as_text(if_generation_match=generation)), generation
            except NotFound:
                return {'messages': [], 'turns': []}, 0
        return await asyncio.to_thread(read)

    async def save(self, conversation_id, state, version):
        def write():
            from google.api_core.exceptions import PreconditionFailed
            blob = self.bucket.blob(f'conversations/{validate_id(conversation_id)}.json')
            try:
                blob.upload_from_string(json.dumps(state), content_type='application/json',
                                        if_generation_match=version)
            except PreconditionFailed:
                raise StateConflict('Conversation changed. Reload and retry your turn.') from None
        await asyncio.to_thread(write)
