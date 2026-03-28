#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path


def main():
    heartbeat_path = Path(os.getenv("HEARTBEAT_FILE", "/tmp/4coinsbot.heartbeat"))
    max_age = int(os.getenv("HEARTBEAT_MAX_AGE_SEC", "120"))

    if not heartbeat_path.exists():
        print(f"heartbeat missing: {heartbeat_path}")
        sys.exit(1)

    try:
        raw = heartbeat_path.read_text().strip()
        heartbeat_ts = int(raw)
    except Exception:
        print(f"heartbeat unreadable: {heartbeat_path}")
        sys.exit(1)

    age = int(time.time()) - heartbeat_ts
    if age > max_age:
        print(f"heartbeat stale: age={age}s max={max_age}s")
        sys.exit(1)

    print(f"ok: age={age}s")


if __name__ == "__main__":
    main()
