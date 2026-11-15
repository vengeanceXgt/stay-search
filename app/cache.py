"""Search-result cache with a pluggable backend.

Default: in-process TTL + LRU cache. If REDIS_URL is set (and the redis package is installed),
results are stored in Redis instead so multiple API workers share one cache.
Invalidation: keys embed a per-city version number; a booking bumps that city's version, so
every cached search for the city becomes unreachable immediately (no key scanning needed).
"""
import json
import os
import threading
import time
from collections import OrderedDict


class MemoryCache:
    def __init__(self, max_items: int = 5000):
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()
        self.max_items = max_items
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        with self._lock:
            item = self._data.get(key)
            if item is None or item[0] < time.monotonic():
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return json.loads(item[1])

    def set(self, key: str, value, ttl: float = 60.0):
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, json.dumps(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def version(self, scope: str) -> int:
        with self._lock:
            return self._versions.get(scope, 0)

    def bump(self, scope: str):
        with self._lock:
            self._versions[scope] = self._versions.get(scope, 0) + 1

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "items": len(self._data), "backend": "memory"}


class RedisCache:  # optional backend; not exercised by the unit tests
    def __init__(self, url: str):
        import redis

        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        raw = self.r.get(key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(raw)

    def set(self, key: str, value, ttl: float = 60.0):
        self.r.set(key, json.dumps(value), ex=int(ttl))

    def version(self, scope: str) -> int:
        return int(self.r.get(f"ver:{scope}") or 0)

    def bump(self, scope: str):
        self.r.incr(f"ver:{scope}")

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "backend": "redis"}


def make_cache():
    if os.getenv("CACHE_DISABLED") == "1":
        return None
    url = os.getenv("REDIS_URL")
    return RedisCache(url) if url else MemoryCache()
