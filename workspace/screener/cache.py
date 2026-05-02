from __future__ import annotations

import time
from typing import Any


class SimpleCache:
    def __init__(self, default_ttl: float = 30.0):
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        item = self._cache.get(key)
        now = time.time()
        if item is None:
            self._misses += 1
            return None

        expires_at, value = item
        if expires_at < now:
            self._cache.pop(key, None)
            self._misses += 1
            return None

        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: float | None = None):
        lifetime = self._ttl if ttl is None else ttl
        self._cache[key] = (time.time() + lifetime, value)

    def clear(self):
        self._cache.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }
