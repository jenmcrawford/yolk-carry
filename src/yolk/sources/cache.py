"""On-disk cache of raw API responses.

Imports stay reproducible and a network blip never blocks work. Responses
are stored verbatim so a parser change can be re-run against old payloads.
"""

from __future__ import annotations

import hashlib
import json
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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
