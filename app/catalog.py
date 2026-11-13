import os
from contextlib import contextmanager
import snowflake.connector

@contextmanager
def connection():
    kwargs = dict(
        account=os.environ['SNOWFLAKE_ACCOUNT'],
        user=os.environ['SNOWFLAKE_USER'],
        warehouse=os.environ['SNOWFLAKE_WAREHOUSE'],
        database=os.getenv('SNOWFLAKE_DATABASE', 'FINSIGHT'),
        schema=os.getenv('SNOWFLAKE_SCHEMA', 'RAG'),
        role=os.environ['SNOWFLAKE_ROLE'],
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        token=os.environ["SNOWFLAKE_TOKEN"],        
        session_parameters={'QUERY_TAG': 'FINSIGHT_INGESTION'},
    )
    if os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSWORD'):
        kwargs['private_key_password'] = os.environ['SNOWFLAKE_PRIVATE_KEY_PASSWORD']
    conn = snowflake.connector.connect(**kwargs)
    try:
        yield conn
    finally:
        conn.close()


def get_filing(conn, source):
    with conn.cursor() as cur:
        cur.execute('''SELECT SOURCE_FILE, COMPANY, FILING_YEAR, CHUNK_COUNT,
            EMBEDDING_MODEL, INDEXING_STATUS, CONTENT_HASH, PIPELINE_VERSION,
            ERROR_MESSAGE, UPDATED_AT
            FROM DOCUMENT_CATALOG WHERE SOURCE_FILE = %s''', (source,))
        row = cur.fetchone()
        return dict(zip(['source_file', 'company', 'year', 'chunk_count',
                         'embedding_model', 'status', 'content_hash',
                         'pipeline_version', 'error', 'updated_at'], row)) if row else None


def set_status(conn, source, company, year, count, model, status, digest, version, error=None):
    with conn.cursor() as cur:
        cur.execute('''MERGE INTO DOCUMENT_CATALOG AS t
            USING (SELECT %s AS source_file, %s AS company, %s AS filing_year,
              %s AS chunk_count, %s AS embedding_model, %s AS indexing_status,
              %s AS content_hash, %s AS pipeline_version, %s AS error_message) AS s
            ON t.SOURCE_FILE = s.source_file
            WHEN MATCHED THEN UPDATE SET
              COMPANY=s.company, FILING_YEAR=s.filing_year, CHUNK_COUNT=s.chunk_count,
              EMBEDDING_MODEL=s.embedding_model, INDEXING_STATUS=s.indexing_status,
              CONTENT_HASH=s.content_hash, PIPELINE_VERSION=s.pipeline_version,
              ERROR_MESSAGE=s.error_message, UPDATED_AT=CURRENT_TIMESTAMP(),
              INDEXED_AT=IFF(s.indexing_status='INDEXED', CURRENT_TIMESTAMP(),t.INDEXED_AT)
            WHEN NOT MATCHED THEN INSERT
              (SOURCE_FILE, COMPANY, FILING_YEAR, CHUNK_COUNT, EMBEDDING_MODEL,
               INDEXING_STATUS, CONTENT_HASH, PIPELINE_VERSION, ERROR_MESSAGE, INDEXED_AT)
              VALUES (s.source_file, s.company, s.filing_year, s.chunk_count,
                s.embedding_model, s.indexing_status, s.content_hash,
                s.pipeline_version, s.error_message,
                IFF(s.indexing_status='INDEXED', CURRENT_TIMESTAMP(),NULL))''',
            (source, company, year, count, model, status, digest, version, error))
    conn.commit()
