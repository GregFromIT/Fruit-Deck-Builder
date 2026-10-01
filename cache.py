"""Disk cache. EDHREC/Scryfall responses change slowly; re-fetching on every
form submit is the main source of latency in the Flask app."""

import hashlib
import json
import os
import time

CACHE_DIR = os.environ.get("MTG_CACHE_DIR", ".cache")
TTL_SECONDS = 7 * 24 * 3600


def _path(key):
    h = hashlib.sha256(key.encode()).hexdigest()[:20]
    return os.path.join(CACHE_DIR, f"{h}.json")


def cached(key, producer, ttl=TTL_SECONDS):
    """Return cached value for key, else call producer() and store it."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _path(key)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl:
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt entry, fall through and refetch

    value = producer()
    try:
        with open(path, "w") as f:
            json.dump(value, f)
    except (TypeError, OSError):
        pass  # unserialisable or unwritable — still return the value
    return value


def clear():
    if not os.path.isdir(CACHE_DIR):
        return 0
    n = 0
    for name in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, name))
        n += 1
    return n
