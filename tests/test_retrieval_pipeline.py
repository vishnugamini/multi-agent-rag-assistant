from types import SimpleNamespace as Obj
import pytest
from app.corpus import Corpus,augmentation_pipeline
from app.config import Settings


@pytest.mark.parametrize('top_k,expected',[(0,1),(5,5),(500,10)])
def test_lcel_retrieval_embeds_then_filters_and_preserves_ids(monkeypatch,top_k,expected):
    seen={}
    class Embeddings:
        def __init__(self,**kwargs):pass
        def embed_query(self,query):
            seen['embedding']=query
            return [0.1,0.2]
    class Index:
        config=Obj(host='https://example.com',api_key='test')
        def query(self,**kwargs):
            seen['query']=kwargs
            return {'matches':[{'id':'doc-a::0000','score':.9,'metadata':{'text':'retrieved evidence','title':'A'}}]}
    monkeypatch.setattr('app.corpus.OpenAIEmbeddings',Embeddings)
    corpus=Corpus(Settings(_env_file=None,openai_api_key='test'));corpus.__dict__['index']=Index()
    result=corpus.search('memory',top_k,'langgraph')
    assert seen['embedding']=='memory'
    assert seen['query']['vector']==[0.1,0.2] and seen['query']['top_k']==expected
    assert seen['query']['filter']=={'$and':[{'kind':{'$eq':'chunk'}},{'topic':{'$eq':'langgraph'}}]}
    assert result[0]['id']=='doc-a::0000'
    assert '[doc-a::0000]' in augmentation_pipeline().invoke(result)
