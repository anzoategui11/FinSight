import os

COLLECTION = os.getenv('QDRANT_COLLECTION', 'finsight_reports_minilm_v1')
MODEL = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
PIPELINE_VERSION = os.getenv('INDEX_PIPELINE_VERSION', 'v1')
UPLOAD_DIR = os.getenv('UPLOAD_DIR', '/data/uploads')
