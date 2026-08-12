"""On-disk cache of raw API responses.

Imports stay reproducible and a network blip never blocks work. Responses
are stored verbatim so a parser change can be re-run against old payloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(".cache")


def cached_json(namespace: str, key: str, fetch: Callable[[], Any]) -> Any:
    """Return cached JSON for `key`, calling `fetch` only on a miss."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    path = CACHE_DIR / namespace / f"{digest}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    payload = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling temp file and swap it in with os.replace, which is
    # atomic within a filesystem. A reader then always sees either the old
    # file or the complete new one, never a partial write from a process
    # killed mid-write — a truncated file would otherwise pass path.exists()
    # forever and turn a transient interruption into a permanent block.
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return payload
