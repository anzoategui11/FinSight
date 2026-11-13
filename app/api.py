import os
import re
import secrets
import uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from rq.job import Job
from app.config import UPLOAD_DIR
from app.catalog import connection, get_filing, company_document_counts
from app.rag import chain

app = FastAPI(title='FinSight RAG', version='0.1.0')
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED = {'.html', '.htm', '.txt', '.pdf'}


def authorize(x_api_key: str | None = Header(default=None)):
    expected = os.getenv('FINSIGHT_API_KEY')
    if not expected or not secrets.compare_digest(x_api_key or '', expected):
        raise HTTPException(401, 'Invalid API key')


def queue():
    return Queue('indexing', connection=Redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0')))


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get(
    "/companies",
    dependencies=[Depends(authorize)]
)
def list_companies():
    with connection() as conn:
        return {
            "companies": company_document_counts(conn)
        }

@app.post('/documents', status_code=202, dependencies=[Depends(authorize)])
def upload_document(file: UploadFile = File(...), company: str = Form(...), year: int = Form(...)):
    company = company.upper().strip()
    if not re.fullmatch(r'[A-Z0-9.-]{1,20}', company):
        raise HTTPException(422, 'Company must be a ticker-like identifier')
    if year < 1900 or year > 2100:
        raise HTTPException(422, 'Invalid year')
    supplied_name = Path((file.filename or '').replace('\\', '/')).name
    ext = Path(supplied_name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(415, 'Only PDF, HTML, or TXT accepted')
    safe_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(supplied_name).stem)[:50]
    name = f'{company}_{year}_{safe_stem}_{uuid.uuid4().hex[:12]}{ext}'
    destination = Path(UPLOAD_DIR) / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open('wb') as out:
            while block := file.file.read(1024 * 1024):
                total += len(block)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'File exceeds 20 MB')
                out.write(block)
        if total == 0:
            raise HTTPException(422, 'File is empty')
        job = queue().enqueue('app.ingest.process_upload', name, company, year,
                              job_timeout='30m', result_ttl=86400, failure_ttl=604800)
        return {'job_id': job.id, 'source_file': name, 'status': 'QUEUED'}
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@app.get('/jobs/{job_id}', dependencies=[Depends(authorize)])
def job_status(job_id: str):
    try:
        job = Job.fetch(job_id, connection=queue().connection)
    except Exception:
        raise HTTPException(404, 'Job not found')
    status = job.get_status(refresh=True)
    return {'job_id': job.id, 'status': str(status),
            'result': job.return_value() if getattr(status, 'value', str(status)) == 'finished' else None}


@app.get('/documents/{source_file}', dependencies=[Depends(authorize)])
def document_status(source_file: str):
    if Path(source_file).name != source_file:
        raise HTTPException(400, 'Invalid filename')
    with connection() as conn:
        row = get_filing(conn, source_file)
    if not row:
        raise HTTPException(404, 'No catalog entry; job may still be queued')
    return row


@app.post('/ask', dependencies=[Depends(authorize)])
def ask(payload: Question):
    try:
        return chain().invoke({'question': payload.question})
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
