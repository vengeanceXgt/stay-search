# Stay Search: High-Throughput Hotel Search & Atomic Inventory Booking Engine

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00.svg?style=flat&logo=sqlalchemy)](https://www.sqlalchemy.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=flat&logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-11%20Passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)]()

> **Target Role:** Agoda (Full-Stack / Distributed & Scalable Systems / Backend Engineering)  
> **Key Capabilities Demonstrated:** High-volume paginated search over 100,000+ inventory items, race-free atomic per-night bookings, versioned cache invalidation without keyspace scans, token-bucket rate limiting, and an interactive front-end.

---

## 📌 Executive Summary

Modern travel platforms like Agoda handle high-volume search traffic alongside strict transactional booking constraints. A customer booking a 5-night stay must reserve each night atomically—if even a single night is sold out, the entire booking must cleanly abort without leaving orphan reservations. Concurrently, millions of search queries must return sub-100ms responses across 100,000+ properties without serving stale availability.

This project implements a complete, production-grade hotel search and booking backend:
1. **Per-Night Atomic Inventory Model:** Eliminates race conditions and overbooking using deterministic locking and all-or-nothing transactional updates.
2. **Scalable Search with SQL `NOT EXISTS` Subqueries:** Fast, indexed filtering and sorting over 100,000 properties across arbitrary check-in/check-out date ranges.
3. **Zero-Scan Cache Invalidation:** Uses monotonic per-city versioning (`city_version`). A confirmed booking bumps that city's version in $O(1)$, instantly invalidating stale searches without scanning cache keys.
4. **Token-Bucket Rate Limiter:** Protects booking endpoints from scalpers and automated bots.
5. **Full Observability & Benchmarks:** Real-time headers (`X-Cache: HIT|MISS`, `X-Response-Time-ms`), `/api/stats` monitoring, and an interactive web interface.

---

## 🏛 Architecture & Data Flow

```mermaid
flowchart TD
    Client([Web Client / API Consumer])

    subgraph API Gateway / Middleware
        RL[Token Bucket Rate Limiter]
        Timer[Timing Middleware (X-Response-Time-ms)]
    end

    subgraph Service Layer
        SearchSvc[Search Service]
        BookingSvc[Atomic Booking Service]
        CacheSvc[(Cache: LRU / Redis)]
    end

    subgraph Persistence Layer
        DB[(SQLAlchemy Engine: SQLite / PostgreSQL)]
        PropTable[properties table: city, price, rating]
        InvTable[inventory table: property_id, night, booked]
        BookTable[bookings table: guest, dates, total_price]
    end

    Client -->|GET /api/search| Timer
    Client -->|POST /api/bookings| RL
    RL -->|Allowed| BookingSvc
    RL -->|Exceeded| Error429[429 Rate Limit Exceeded]

    Timer --> SearchSvc
    SearchSvc -->|Check city_version key| CacheSvc
    CacheSvc -->|Cache Hit| FastResponse[Return Cached JSON + X-Cache: HIT]
    CacheSvc -->|Cache Miss| DB
    DB --> PropTable
    DB --> InvTable

    BookingSvc -->|Acquire Lock & Verify Inventory| InvTable
    BookingSvc -->|All Nights Free| BookTable
    BookingSvc -->|Bump city_version| CacheSvc
```

---

## 💡 Core Engineering Highlights

### 1. Atomic Per-Night Inventory Reservation
A property defines `total_rooms`. Instead of an aggregate count, an `inventory(property_id, night, booked)` table records rooms consumed per night.

* **Transaction Boundary:** When booking from night $D_{in}$ to $D_{out}$:
  $$\text{Nights} = [D_{in}, D_{in} + 1, \dots, D_{out} - 1]$$
  *(Check-out day is not a night; back-to-back stays are natively supported).*
* **Atomicity:** The service checks every requested night against `total_rooms`. If all nights have capacity, it increments all records atomically and persists the booking. If any single night is sold out, the entire transaction rolls back (`409 Conflict`), leaving zero partial reservations.
* **Concurrency Safety:** On SQLite, a synchronized transaction lock prevents write contention. On PostgreSQL, `SELECT ... FOR UPDATE` row-level locks protect concurrent bookings on the same property.

### 2. Single-Query Search Availability
Filtering properties with available rooms over an arbitrary multi-night stay is executed via a clean SQL `NOT EXISTS` clause:
```sql
SELECT p.* FROM properties p
WHERE p.city = :city
  AND NOT EXISTS (
      SELECT 1 FROM inventory i
      WHERE i.property_id = p.id
        AND i.night >= :checkin AND i.night < :checkout
        AND i.booked >= p.total_rooms
  )
ORDER BY p.price_per_night ASC
LIMIT :limit OFFSET :offset;
```
Composite database indexes on `(city, price_per_night)` and `(city, rating)` ensure queries remain efficient even as the catalog grows past 100,000 properties.

### 3. Zero-Scan Cache Invalidation
Traditional cache invalidation uses wildcard key scanning (`KEYS search:city:*`), which blocks Redis or consumes significant memory. This system uses **versioned cache keys**:
$$\text{Key} = \text{hash}(\text{city}, \text{city\_version}, \text{checkin}, \text{checkout}, \text{filters}, \text{page})$$
- When a booking occurs for any property in `Bangkok`, `cache.bump("Bangkok")` increments Bangkok's version integer.
- Old search results for Bangkok are instantly invalidated as cache misses because subsequent requests query with the new version.
- Other cities remain hot in cache with zero disruption and zero keyspace scanning.

### 4. Resilient Rate Limiting
The booking endpoint is gated by a token-bucket rate limiter (`app/ratelimit.py`):
- Configurable fill rate (`WRITE_RATE`, default 5 req/sec) and burst tolerance (`WRITE_BURST`, default 20 tokens).
- Prevents DDoS bursts and high-frequency booking attempts per client IP.

---

## 🛠 Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| **Framework** | FastAPI | High-performance asynchronous Python framework with auto-generated OpenAPI docs |
| **ORM / Data Access** | SQLAlchemy 2.0 | Modern declarative syntax with explicit transaction lifecycle control |
| **Database** | SQLite / PostgreSQL | Zero-config SQLite for local dev/testing; native PostgreSQL connection support |
| **Caching** | In-Process LRU / Redis | In-memory thread-safe LRU with TTL default; pluggable Redis adapter via `REDIS_URL` |
| **Frontend** | HTML5 / Vanilla JS / CSS3 | Fast, dependency-free interactive UI served directly via FastAPI static files |
| **Testing** | Pytest, TestClient | Automated concurrency and unit test coverage |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.11)
- `pip` package manager

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/vengeanceXgt/agoda-stay-search.git
cd agoda-stay-search
pip install -r requirements.txt
```

### 2. Seed the Database
Populate the database with properties (e.g., 10,000 or 100,000 properties across 20 international destinations):
```bash
python seed.py 100000
```
*Output: `seeded 100000 properties in ~15s`*

### 3. Run the Application
Start the ASGI server:
```bash
uvicorn app.main:app --reload --port 8000
```
- **Web UI:** Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.
- **Interactive Swagger Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 📖 API Reference

### 1. List Available Cities
```http
GET /api/cities
```
**Response (200 OK):**
```json
["Bali", "Bangkok", "Colombo", "Da Nang", "Dubai", "Hanoi", "Kuala Lumpur", "Kyoto", "London", "Maldives", "Paris", "Phuket", "Rome", "Seoul", "Singapore", "Sydney", "Taipei", "Tokyo", "Vancouver", "Zurich"]
```

### 2. Search Properties
```http
GET /api/search?city=Bangkok&checkin=2026-12-01&checkout=2026-12-05&max_price=250&min_rating=4.0&sort=price_asc&page=1&page_size=10
```
**Response (200 OK):**
```json
{
  "total": 482,
  "page": 1,
  "page_size": 10,
  "results": [
    {
      "id": 1420,
      "name": "Bangkok Riverside Sanctuary",
      "city": "Bangkok",
      "price_per_night": 115,
      "rating": 4.6,
      "total_rooms": 12,
      "max_guests": 3
    }
  ]
}
```
*Headers:* `X-Cache: HIT | MISS`, `X-Response-Time-ms: 4.12`

### 3. Book a Stay
```http
POST /api/bookings
Content-Type: application/json

{
  "property_id": 1420,
  "guest_name": "Asha Sharma",
  "checkin": "2026-12-01",
  "checkout": "2026-12-05",
  "guests": 2
}
```
**Response (201 Created):**
```json
{
  "id": 1,
  "property_id": 1420,
  "checkin": "2026-12-01",
  "checkout": "2026-12-05",
  "total_price": 460
}
```
*Error Responses:*
- `400 Bad Request`: Validation failure (checkout before checkin, stay > 30 days, guests exceed `max_guests`, past dates).
- `409 Conflict`: Room sold out on one or more dates.
- `429 Too Many Requests`: Rate limit threshold exceeded.

### 4. Cache & Observability Stats
```http
GET /api/stats
```
**Response (200 OK):**
```json
{
  "backend": "memory",
  "hits": 3420,
  "misses": 280,
  "hit_rate": 0.924,
  "size": 182
}
```

---

## 🧪 Verification & Testing

The test suite thoroughly validates business logic, edge conditions, and concurrency invariants:
```bash
python -m pytest -v
```

### Verified Test Cases (`tests/test_stays.py`)
- `test_booking_computes_price`: Correct multiplication of price per night across duration.
- `test_cannot_overbook_a_night`: Exactly caps bookings at `total_rooms` and returns `409 Conflict`.
- `test_partial_overlap_is_blocked_and_leaves_no_partial_state`: Transactional rollback leaves remaining free nights unreserved.
- `test_back_to_back_stays_allowed`: Checkout on day $T$ permits new checkin on day $T$.
- `test_concurrent_bookings_never_exceed_rooms`: Spawns 40 concurrent threads on a 5-room property; **exactly 5 succeed (201) and exactly 35 are rejected (409)**.
- `test_search_excludes_sold_out_property`: Sold-out properties are dynamically omitted from search results during overlapping ranges.
- `test_search_filters_and_sorting`: Price filtering, rating filtering, and ascending/descending sorts.
- `test_pagination`: Boundary testing on pagination counts and offsets.
- `test_cache_hit_then_invalidated_by_booking`: First request returns `MISS`, second returns `HIT`, booking triggers invalidation, third request returns fresh `MISS`.
- `test_validation_errors`: Validates guest counts, negative dates, and zero-day stays.
- `test_token_bucket_limits_bursts`: Enforces burst limits on rapid requests.

---

## ⚡ Load & Benchmark Results

Benchmarking search throughput and latency under 32 concurrent clients across 100,000 properties:

```bash
# 1. Benchmark with caching enabled
uvicorn app.main:app --port 8000
python loadtest.py --requests 3000 --concurrency 32

# 2. Benchmark without caching
CACHE_DISABLED=1 uvicorn app.main:app --port 8001
python loadtest.py --url http://127.0.0.1:8001 --requests 600 --concurrency 32
```

### Benchmark Summary (100k Properties, 32 Concurrency)
| Metric | Cache Enabled (LRU) | Cache Disabled (Direct DB) | Improvement |
|---|---|---|---|
| **p50 Latency** | **54 ms** | 230 ms | **4.2x faster** |
| **p95 Latency** | **138 ms** | 328 ms | **2.4x faster** |
| **p99 Latency** | **215 ms** | 368 ms | **1.7x faster** |
| **Throughput** | **458 req/s** | 135 req/s | **3.4x higher** |
| **Cache Hit Rate** | **93.2%** | N/A | — |

---

## 📂 Project Structure

```
agoda-stay-search/
├── app/
│   ├── __init__.py
│   ├── booking.py          # Atomic reservation logic & inventory check
│   ├── cache.py            # Thread-safe LRU & Redis cache with versioning
│   ├── db.py               # Database engine, sessionmaker & connection config
│   ├── main.py             # FastAPI routing, middleware & exception handlers
│   ├── models.py           # SQLAlchemy declarative models (Property, Inventory, Booking)
│   ├── ratelimit.py        # Token-bucket rate limiting algorithm
│   └── search.py           # Single-query search & dynamic SQL builder
├── static/
│   └── index.html          # Interactive travel booking UI
├── tests/
│   ├── conftest.py         # Pytest fixtures & isolated DB setup
│   └── test_stays.py       # 11 unit & concurrency tests
├── loadtest.py             # High-concurrency benchmark script
├── requirements.txt        # Production & test dependencies
├── seed.py                 # Synthetic property & inventory generator
└── README.md
```

---

## 🛡 License
This project is licensed under the MIT License.
