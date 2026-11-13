import hashlib
import logging
import uuid
from pathlib import Path
from bs4 import BeautifulSoup
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import FieldCondition, Filter, MatchValue
from app.config import UPLOAD_DIR, MODEL, PIPELINE_VERSION, COLLECTION
from app.catalog import connection, get_filing, set_status
from app.vector import client, store

log = logging.getLogger(__name__)


def extract(path):
    suffix = path.suffix.lower()
    if suffix in {'.html', '.htm'}:
        soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'lxml')
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        return soup.get_text('\n', strip=True)
    if suffix == '.pdf':
        reader = PdfReader(str(path))
        return '\n\n'.join(page.extract_text() or '' for page in reader.pages)
    if suffix == '.txt':
        return path.read_text(encoding='utf-8', errors='replace')
    raise ValueError('Unsupported document type')


def source_filter(source):
    return Filter(must=[FieldCondition(key='metadata.source', match=MatchValue(value=source))])


def process_upload(source, company, year):
    # Only the server creates source names; never accept client-provided paths here.
    path = (Path(UPLOAD_DIR) / source).resolve()
    if path.parent != Path(UPLOAD_DIR).resolve() or not path.is_file():
        raise ValueError('Uploaded file not found')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    c = client()
    with connection() as conn:
        prior = get_filing(conn, source)
        try:
            text = extract(path)
            if not text.strip():
                raise ValueError('No extractable text in document')
            splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
            parts = splitter.split_text(text)
            docs = [Document(page_content=part, metadata={
                'company': company, 'year': year, 'source': source, 'chunk_id': i,
            }) for i, part in enumerate(parts)]
            ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f'{source}:{i}'))
                   for i in range(len(docs))]
            current = prior and all((
                prior['status'] == 'INDEXED',
                prior['content_hash'] == digest,
                prior['embedding_model'] == MODEL,
                prior['pipeline_version'] == PIPELINE_VERSION,
                prior['chunk_count'] == len(docs),
            ))
            if current and c.collection_exists(COLLECTION):
                n = c.count(collection_name=COLLECTION,
                            count_filter=source_filter(source), exact=True).count
                if n == len(docs):
                    return {'source': source, 'status': 'SKIPPED', 'chunks': n}
            set_status(conn, source, company, year, 0, MODEL, 'INDEXING', digest, PIPELINE_VERSION)
            vector_store = store(create=True)
            # Development design: remove old vectors before replacement.
            c.delete(collection_name=COLLECTION,
                     points_selector=source_filter(source), wait=True)
            for start in range(0, len(docs), 32):
                vector_store.add_documents(docs[start:start+32], ids=ids[start:start+32])
            actual = c.count(collection_name=COLLECTION,
                             count_filter=source_filter(source), exact=True).count
            if actual != len(docs):
                raise RuntimeError(f'Indexed {actual} instead of {len(docs)} vectors')
            set_status(conn, source, company, year, actual, MODEL,
                       'INDEXED', digest, PIPELINE_VERSION)
            return {'source': source, 'status': 'INDEXED', 'chunks': actual}
        except Exception as exc:
            set_status(conn, source, company, year, 0, MODEL,
                       'FAILED', digest, PIPELINE_VERSION, str(exc)[:4000])
            log.exception('Indexing failed for %s', source)
            raise

