import os
from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from app.config import COLLECTION, MODEL

@lru_cache(maxsize=1)
def embedding_model():
    return HuggingFaceEmbeddings(
        model_name=MODEL,
        encode_kwargs={'normalize_embeddings': True},
    )

@lru_cache(maxsize=1)
def client():
    return QdrantClient(url=os.getenv('QDRANT_URL', 'http://qdrant:6333'))


def store(create=False):
    c = client()
    if not c.collection_exists(COLLECTION):
        if not create:
            raise RuntimeError('Vector collection missing: index a document first')
        dimensions = len(embedding_model().embed_query('dimension test'))
        c.create_collection(collection_name=COLLECTION, vectors_config=VectorParams(
            size=dimensions, distance=Distance.COSINE))
    return QdrantVectorStore(client=c, collection_name=COLLECTION, embedding=embedding_model())
