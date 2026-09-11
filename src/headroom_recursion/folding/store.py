"""Local transactional evidence store. Digests provide integrity, not authentication.

Only the trusted controller/evaluators receive this object. It is NOT an OS sandbox.
Use a separate account/process/filesystem boundary for hostile tools or workers.
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .types import FoldError, canonical, decode, digest, identity, sha, integer


class Store:
    def __init__(self, directory: str | Path, *, max_blob_bytes: int = 16_000_000):
        integer("max_blob_bytes", max_blob_bytes, 1, 1_000_000_000)
        self.directory = Path(directory).absolute()
        if self.directory.is_symlink() or any(p.is_symlink() for p in self.directory.parents):
            raise FoldError("store path may not traverse symlinks")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "fold.sqlite3"
        if self.path.is_symlink():
            raise FoldError("store database may not be a symlink")
        self.max_blob_bytes = max_blob_bytes
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS blobs(ref TEXT PRIMARY KEY,body BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS campaigns(scope TEXT PRIMARY KEY,head TEXT NOT NULL REFERENCES blobs(ref));
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,scope TEXT NOT NULL,
            previous TEXT NOT NULL,state TEXT NOT NULL REFERENCES blobs(ref),
            detail TEXT NOT NULL REFERENCES blobs(ref),chain TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS units(ref TEXT NOT NULL,scope TEXT NOT NULL,phase TEXT NOT NULL,
            PRIMARY KEY(ref,scope,phase));
        ''')
        with self.transaction():
            v = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if v is None:
                self.db.execute("INSERT INTO metadata VALUES('schema','1')")
            elif v[0] != '1':
                raise FoldError("unsupported store schema")
        self.audit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def put(self, raw: bytes) -> str:
        if type(raw) is not bytes or len(raw) > self.max_blob_bytes:
            raise FoldError("artifact must be bounded bytes")
        ref = sha(raw)
        self.db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (ref, raw))
        if self.get(ref) != raw:
            raise FoldError("artifact collision/corruption")
        return ref

    def put_json(self, obj) -> str:
        return self.put(canonical(obj))

    def get(self, ref: str) -> bytes:
        digest("artifact", ref)
        row = self.db.execute("SELECT body FROM blobs WHERE ref=?", (ref,)).fetchone()
        if row is None or sha(bytes(row[0])) != ref:
            raise FoldError("missing or corrupt artifact")
        return bytes(row[0])

    def json(self, ref: str):
        return decode(self.get(ref))

    def state(self, scope: str) -> dict:
        row = self.db.execute("SELECT head FROM campaigns WHERE scope=?", (scope,)).fetchone()
        if row is None:
            raise FoldError("unknown campaign")
        state = self.json(row[0])
        if not isinstance(state, dict) or state.get("scope") != scope or state.get("schema_version") != 1:
            raise FoldError("invalid campaign state")
        return state

    def head(self, scope: str) -> str:
        self.state(scope)
        return self.db.execute("SELECT head FROM campaigns WHERE scope=?", (scope,)).fetchone()[0]

    def _save(self, scope: str, state: dict, action: str, detail: dict):
        ref = self.put_json(state)
        last = self.db.execute("SELECT chain FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0"*64
        detail_ref = self.put_json({"action": action, **detail})
        chain = identity({"scope": scope, "previous": previous, "state": ref, "detail": detail_ref})
        self.db.execute("INSERT INTO events(scope,previous,state,detail,chain) VALUES(?,?,?,?,?)",
                        (scope, previous, ref, detail_ref, chain))
        self.db.execute("INSERT INTO campaigns VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET head=excluded.head", (scope, ref))

    def create(self, state: dict):
        with self.transaction():
            scope = state["scope"]
            if self.db.execute("SELECT 1 FROM campaigns WHERE scope=?", (scope,)).fetchone():
                raise FoldError("campaign already exists")
            for phase, refs in state["units"].items():
                for ref in refs:
                    old = self.db.execute("SELECT scope,phase FROM units WHERE ref=?", (ref,)).fetchall()
                    # Existing development material is never a fresh confirmation unit.
                    # Reuse across campaigns is allowed only development-to-development.
                    if any(phase != "screen" or old_phase != "screen" for _,old_phase in old):
                        raise FoldError("cross-campaign confirmation-unit reuse or exposure")
                    self.db.execute("INSERT INTO units VALUES(?,?,?)", (ref, scope, phase))
            self._save(scope, state, "campaign-created", {"policy": state["policy"]})

    def update(self, scope: str, action: str, change):
        """Transactionally inspect the latest state, then append an immutable revision."""
        with self.transaction():
            state = self.state(scope)
            result, detail = change(state)
            state["revision"] += 1
            self._save(scope, state, action, detail)
            return result

    def audit(self) -> dict:
        """Read a coherent transaction snapshot, including while another process writes."""
        if self.db.in_transaction:
            return self._audit()
        with self.transaction():
            return self._audit()

    def _audit(self) -> dict:
        checked = 0
        for ref, body in self.db.execute("SELECT ref,body FROM blobs"):
            if sha(bytes(body)) != ref:
                raise FoldError("corrupt evidence blob")
            checked += 1
        previous = "0"*64
        latest = {}
        count = 0
        for scope, prev, state, detail, chain in self.db.execute(
                "SELECT scope,previous,state,detail,chain FROM events ORDER BY seq"):
            if prev != previous or chain != identity({"scope":scope,"previous":prev,"state":state,"detail":detail}):
                raise FoldError("broken event chain")
            self.get(state); self.get(detail)
            latest[scope] = state
            previous = chain
            count += 1
        if dict(self.db.execute("SELECT scope,head FROM campaigns")) != latest:
            raise FoldError("campaign head disagrees with event log")
        expected = {(ref,scope,phase) for scope in latest
                    for phase,refs in self.state(scope)["units"].items() for ref in refs}
        if set(self.db.execute("SELECT ref,scope,phase FROM units")) != expected:
            raise FoldError("unit registry disagrees with campaign records")
        return {"blobs": checked,"events": count,"campaigns": len(latest),"head":previous,
                "trust": "trusted local store; hash chain is not authentication against its owner"}
