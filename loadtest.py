"""Load test against a running server.

    uvicorn app.main:app --port 8000 &          # (seed first:  python seed.py 100000)
    python loadtest.py --url http://127.0.0.1:8000 --requests 3000 --concurrency 32

Run once normally and once with CACHE_DISABLED=1 on the server to compare latency.
"""
import argparse
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--requests", type=int, default=3000)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--distinct", type=int, default=200, help="number of distinct queries (smaller = more cache reuse)")
    args = ap.parse_args()

    with httpx.Client(base_url=args.url) as c:
        cities = c.get("/api/cities").json()
    rng = random.Random(3)
    base = date.today() + timedelta(days=20)
    queries = []
    for _ in range(args.distinct):
        ci = base + timedelta(days=rng.randint(0, 40))
        queries.append({"city": rng.choice(cities), "checkin": ci.isoformat(), "checkout": (ci + timedelta(days=rng.randint(1, 4))).isoformat(),
                        "guests": rng.randint(1, 4), "max_price": rng.choice([100, 200, 300]), "sort": rng.choice(["price_asc", "rating"])})
    plan = [rng.choice(queries) for _ in range(args.requests)]
    lat, errors, hits = [], 0, 0

    client = httpx.Client(base_url=args.url, timeout=30, limits=httpx.Limits(max_connections=args.concurrency))

    def one(q):
        t0 = time.perf_counter()
        r = client.get("/api/search", params=q)
        return (time.perf_counter() - t0) * 1000, r.status_code, r.headers.get("X-Cache")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for ms, status, cache_state in pool.map(one, plan):
            lat.append(ms)
            errors += status != 200
            hits += cache_state == "HIT"
    wall = time.perf_counter() - t0
    lat.sort()
    pct = lambda p: lat[int(p * (len(lat) - 1))]
    print(f"requests={len(lat)} errors={errors} concurrency={args.concurrency}")
    print(f"throughput  : {len(lat) / wall:.0f} req/s")
    print(f"latency p50 : {pct(.5):.1f} ms | p95 : {pct(.95):.1f} ms | p99 : {pct(.99):.1f} ms | mean {statistics.mean(lat):.1f} ms")
    print(f"cache hits  : {hits}/{len(lat)} ({100 * hits / len(lat):.1f}%)")


if __name__ == "__main__":
    main()
