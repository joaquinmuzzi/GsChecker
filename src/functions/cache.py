import time


def _cache_get(cache: dict, key, ttl: int):
    entry = cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > ttl:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: dict, key, value):
    cache[key] = (time.time(), value)
