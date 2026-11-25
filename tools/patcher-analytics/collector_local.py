"""Local HTTP adapter for the production Worker and its SQLite test database."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
from typing import Final

HERE: Final = Path(__file__).resolve().parent
DEFAULT_DATABASE: Final = HERE.parent.parent / 'build' / 'patcher-analytics.sqlite'
MAX_EVENT_BYTES: Final = 8000
EVENT_PATH: Final = '/__analytics/event'


def create_schema(database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript((HERE / 'schema.sql').read_text())


@dataclass
class LocalCollector:
    """One long-lived Node process running worker.mjs; events go through it in turn."""
    database: Path
    process: subprocess.Popen[bytes]
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def open(cls, database: Path) -> LocalCollector:
        node = shutil.which('node')
        if not node:
            raise ValueError('Local analytics needs Node.js 22.13+ (node:sqlite).')
        database = database.resolve()
        create_schema(database)
        return cls(database, cls.spawn(node, database))

    @staticmethod
    def spawn(node: str, database: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen([node, str(HERE / 'collect_local.mjs'), str(database)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def ingest(self, body: bytes) -> int:
        if len(body) > MAX_EVENT_BYTES:
            return 413
        with self.lock:
            if self.process.poll() is not None:  # crashed: start a fresh one
                self.process = self.spawn(str(self.process.args[0]), self.database)
            assert self.process.stdin and self.process.stdout
            try:
                self.process.stdin.write(base64.b64encode(body) + b'\n')
                self.process.stdin.flush()
                status = int(self.process.stdout.readline())
            except (OSError, ValueError):
                return 503
        return status if status in (204, 400, 413, 503) else 503

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=10)


def configure_page(page: str) -> str:
    marker = 'name="patcher-analytics" content=""'
    if marker not in page:
        raise ValueError('The patcher page is missing its empty analytics configuration.')
    return page.replace(marker, f'name="patcher-analytics" content="{EVENT_PATH}"')
