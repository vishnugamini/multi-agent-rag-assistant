from uuid import uuid4
import pytest
from app.storage import LocalStore, StateConflict


@pytest.mark.asyncio
async def test_history_survives_new_store_and_rejects_stale_writer(tmp_path):
    cid = str(uuid4())
    first = LocalStore(tmp_path)
    state, version = await first.load(cid)
    state['messages'].append({'role': 'user', 'content': 'Remember this'})
    await first.save(cid, state, version)
    restored, generation = await LocalStore(tmp_path).load(cid)
    assert restored['messages'][0]['content'] == 'Remember this'
    assert generation == 1
    with pytest.raises(StateConflict):
        await first.save(cid, {'messages': []}, version)
    assert (await first.load(str(uuid4())))[0]['messages'] == []


@pytest.mark.asyncio
async def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        await LocalStore(tmp_path).load('../../etc/passwd')
