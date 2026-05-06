import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class EstateRagChunk(models.Model):
    _name = 'estate.rag.chunk'
    _description = 'Estate RAG Chunk'
    _auto = False
    _rec_name = 'title'

    title = fields.Char(readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    chunk = fields.Text(readonly=True)
    source = fields.Char(readonly=True)
    embedding_json = fields.Text(readonly=True)
    create_date = fields.Datetime(readonly=True)
    write_date = fields.Datetime(readonly=True)

    @api.model
    def init(self):
        cr = self._cr
        vector_available = False
        cr.execute("SAVEPOINT estate_rag_chunk_init")
        try:
            cr.execute('CREATE EXTENSION IF NOT EXISTS vector')
            vector_available = True
        except Exception as exc:
            _logger.warning('pgvector extension not available, using JSON fallback: %s', exc)
            cr.execute("ROLLBACK TO SAVEPOINT estate_rag_chunk_init")
        finally:
            cr.execute("RELEASE SAVEPOINT estate_rag_chunk_init")

        if vector_available:
            # Try vector without dimension first (newer pgvector supports this).
            try:
                cr.execute("""
                    CREATE TABLE IF NOT EXISTS estate_rag_chunk (
                        id bigserial PRIMARY KEY,
                        title varchar,
                        res_model varchar NOT NULL,
                        res_id integer NOT NULL,
                        source varchar,
                        chunk text NOT NULL,
                        embedding vector,
                        embedding_json text,
                        create_date timestamp,
                        write_date timestamp
                    )
                """)
            except Exception:
                # Fallback to a fixed-dimension vector column (common install).
                cr.execute("""
                    CREATE TABLE IF NOT EXISTS estate_rag_chunk (
                        id bigserial PRIMARY KEY,
                        title varchar,
                        res_model varchar NOT NULL,
                        res_id integer NOT NULL,
                        source varchar,
                        chunk text NOT NULL,
                        embedding vector(768),
                        embedding_json text,
                        create_date timestamp,
                        write_date timestamp
                    )
                """)
        else:
            cr.execute("""
                CREATE TABLE IF NOT EXISTS estate_rag_chunk (
                    id bigserial PRIMARY KEY,
                    title varchar,
                    res_model varchar NOT NULL,
                    res_id integer NOT NULL,
                    source varchar,
                    chunk text NOT NULL,
                    embedding_json text,
                    create_date timestamp,
                    write_date timestamp
                )
            """)

        cr.execute("""
            CREATE INDEX IF NOT EXISTS estate_rag_chunk_res_idx
            ON estate_rag_chunk (res_model, res_id)
        """)
        if vector_available:
            # Optional: vector index (works only if pgvector is installed).
            try:
                cr.execute("""
                    CREATE INDEX IF NOT EXISTS estate_rag_chunk_embedding_idx
                    ON estate_rag_chunk USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 64)
                """)
            except Exception as exc:
                _logger.info('Skip ivfflat index (might require ANALYZE / ivfflat support): %s', exc)

    @api.model
    def _as_vector_literal(self, embedding):
        # pgvector accepts literals like: '[1,2,3]'
        return '[' + ','.join(str(float(x)) for x in (embedding or [])) + ']'

    @api.model
    def _vector_column_exists(self):
        self._cr.execute("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_name='estate_rag_chunk' AND column_name='embedding'
        """)
        return bool(self._cr.fetchone())

    @api.model
    def upsert_chunks(self, res_model, res_id, chunks):
        """chunks: list of dict {title, source, chunk, embedding(list[float])}"""
        if not chunks:
            return 0
        now = fields.Datetime.now()
        self._cr.execute(
            "DELETE FROM estate_rag_chunk WHERE res_model=%s AND res_id=%s",
            (res_model, int(res_id)),
        )

        has_vector = self._vector_column_exists()
        rows = []
        for item in chunks:
            embedding = item.get('embedding') or []
            rows.append((
                item.get('title'),
                res_model,
                int(res_id),
                item.get('source'),
                item.get('chunk') or '',
                json.dumps(embedding),
                now,
                now,
            ))

        if has_vector:
            rows_with_vec = []
            for row in rows:
                embedding_json = row[5]
                vec = self._as_vector_literal(json.loads(embedding_json or '[]'))
                rows_with_vec.append((row[0], row[1], row[2], row[3], row[4], vec, row[5], row[6], row[7]))
            self._cr.executemany(
                """
                INSERT INTO estate_rag_chunk
                    (title, res_model, res_id, source, chunk, embedding, embedding_json, create_date, write_date)
                VALUES
                    (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                """,
                rows_with_vec,
            )
        else:
            self._cr.executemany(
                """
                INSERT INTO estate_rag_chunk
                    (title, res_model, res_id, source, chunk, embedding_json, create_date, write_date)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)

    @api.model
    def search_similar(self, res_model, res_id, query_embedding, limit=5):
        if self._vector_column_exists():
            vector_literal = self._as_vector_literal(query_embedding)
            self._cr.execute(
                """
                SELECT id, title, source, chunk, (embedding <=> %s::vector) AS distance
                FROM estate_rag_chunk
                WHERE res_model=%s AND res_id=%s
                ORDER BY embedding <=> %s::vector ASC
                LIMIT %s
                """,
                (vector_literal, res_model, int(res_id), vector_literal, int(limit)),
            )
            rows = self._cr.fetchall()
            return [
                {
                    'id': row[0],
                    'title': row[1],
                    'source': row[2],
                    'chunk': row[3],
                    'distance': row[4],
                }
                for row in rows
            ]

        # JSON fallback (pet project scale): compute cosine distance in Python.
        def cosine_distance(a, b):
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += x * y
                na += x * x
                nb += y * y
            if na <= 0.0 or nb <= 0.0:
                return 1.0
            return 1.0 - (dot / ((na ** 0.5) * (nb ** 0.5)))

        self._cr.execute(
            """
            SELECT id, title, source, chunk, embedding_json
            FROM estate_rag_chunk
            WHERE res_model=%s AND res_id=%s
            """,
            (res_model, int(res_id)),
        )
        candidates = []
        for row in self._cr.fetchall():
            emb = []
            try:
                emb = json.loads(row[4] or '[]')
            except Exception:
                emb = []
            candidates.append({
                'id': row[0],
                'title': row[1],
                'source': row[2],
                'chunk': row[3],
                'distance': cosine_distance(query_embedding or [], emb),
            })
        candidates.sort(key=lambda x: x['distance'])
        return candidates[: int(limit)]
