import gzip
import sqlite3
import time

from crawler.parser import ParsedPage


SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url          TEXT PRIMARY KEY,
    final_url    TEXT,
    title        TEXT,
    text_gz      BLOB,
    links_gz     BLOB,
    content_hash BLOB,
    depth        INTEGER,
    fetched_at   REAL
);
"""


class PageStore:
    def __init__(self, path, batch_size: int = 100):
        self._db = sqlite3.connect(path)

        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")

        self._db.executescript(SCHEMA)

        self._batch: list[tuple] = []
        self._batch_size = batch_size

        self.raw_bytes = 0
        self.stored_bytes = 0

    def add(
        self,
        url: str,
        final_url: str,
        depth: int,
        page: ParsedPage,
        links: list[str],
        digest: bytes,
    ) -> None:
        text = page.text.encode("utf-8")

        link_blob = "\n".join(links).encode("utf-8")

        text_gz = gzip.compress(
            text,
            compresslevel=6,
        )

        links_gz = gzip.compress(
            link_blob,
            compresslevel=6,
        )

        self.raw_bytes += len(text) + len(link_blob)
        self.stored_bytes += len(text_gz) + len(links_gz)

        self._batch.append(
            (
                url,
                final_url,
                page.title,
                text_gz,
                links_gz,
                digest,
                depth,
                time.time(),
            )
        )

        if len(self._batch) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._batch:
            return

        self._db.executemany(
            """
            INSERT OR IGNORE INTO pages
            VALUES (?,?,?,?,?,?,?,?)
            """,
            self._batch,
        )

        self._db.commit()
        self._batch.clear()

    def count(self) -> int:
        self.flush()

        return self._db.execute(
            "SELECT COUNT(*) FROM pages"
        ).fetchone()[0]

    def get(self, url: str) -> dict | None:
        self.flush()

        row = self._db.execute(
            """
            SELECT
                url,
                final_url,
                title,
                text_gz,
                links_gz,
                depth
            FROM pages
            WHERE url = ?
            """,
            (url,),
        ).fetchone()

        if row is None:
            return None

        text = gzip.decompress(row[3]).decode("utf-8")
        links_text = gzip.decompress(row[4]).decode("utf-8")

        return {
            "url": row[0],
            "final_url": row[1],
            "title": row[2],
            "text": text,
            "links": links_text.split("\n") if links_text else [],
            "depth": row[5],
        }

    def close(self) -> None:
        self.flush()
        self._db.close()