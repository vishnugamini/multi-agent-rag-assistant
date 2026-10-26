import pytest
from types import SimpleNamespace
from uuid import uuid4
from google.api_core.exceptions import NotFound, PreconditionFailed
from app.storage import GCSStore, StateConflict


class Blob:
    generation='71'
    def reload(self): pass
    def download_as_text(self, **kwargs):
        assert kwargs=={'if_generation_match':71}
        return '{"messages":[],"turns":[]}'
    def upload_from_string(self, data, **kwargs):
        self.write=(data,kwargs)


def store(blob):
    gcs=object.__new__(GCSStore)
    gcs.bucket=SimpleNamespace(blob=lambda name:blob)
    return gcs


@pytest.mark.asyncio
async def test_gcs_read_is_pinned_to_cas_generation():
    state,version=await store(Blob()).load(str(uuid4()))
    assert state=={'messages':[],'turns':[]} and version==71


@pytest.mark.asyncio
async def test_gcs_new_object_uses_create_only_precondition():
    blob=Blob()
    await store(blob).save(str(uuid4()),{'messages':[],'turns':[]},0)
    assert blob.write[1]=={'content_type':'application/json','if_generation_match':0}


@pytest.mark.asyncio
async def test_gcs_stale_writer_becomes_state_conflict():
    class Stale(Blob):
        def upload_from_string(self,*args,**kwargs):raise PreconditionFailed('stale')
    with pytest.raises(StateConflict):await store(Stale()).save(str(uuid4()),{},71)


@pytest.mark.asyncio
async def test_gcs_missing_conversation_is_empty():
    class Missing(Blob):
        def reload(self):raise NotFound('missing')
    assert await store(Missing()).load(str(uuid4()))==({'messages':[],'turns':[]},0)
