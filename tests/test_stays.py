from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from app.ratelimit import TokenBucket

D = date.today() + timedelta(days=30)


def _book(client, pid, ci=D, co=None, name="guest", guests=2):
    co = co or ci + timedelta(days=2)
    return client.post("/api/bookings", json={"property_id": pid, "guest_name": name,
                       "checkin": ci.isoformat(), "checkout": co.isoformat(), "guests": guests})


def _search(client, city, **kw):
    p = {"city": city, **{k: (v.isoformat() if isinstance(v, date) else v) for k, v in kw.items()}}
    return client.get("/api/search", params=p)


def test_booking_computes_price(client, prop):
    p = prop(price=120)
    r = _book(client, p.id)
    assert r.status_code == 201 and r.json()["total_price"] == 240


def test_cannot_overbook_a_night(client, prop):
    p = prop(rooms=2)
    assert _book(client, p.id).status_code == 201
    assert _book(client, p.id).status_code == 201
    assert _book(client, p.id).status_code == 409


def test_partial_overlap_is_blocked_and_leaves_no_partial_state(client, prop):
    p = prop(rooms=1)
    assert _book(client, p.id, D, D + timedelta(days=2)).status_code == 201       # nights D, D+1
    assert _book(client, p.id, D + timedelta(days=1), D + timedelta(days=4)).status_code == 409
    # Nights D+2 and D+3 must still be free (the failed booking reserved nothing).
    assert _book(client, p.id, D + timedelta(days=2), D + timedelta(days=4)).status_code == 201


def test_back_to_back_stays_allowed(client, prop):
    p = prop(rooms=1)
    assert _book(client, p.id, D, D + timedelta(days=2)).status_code == 201
    assert _book(client, p.id, D + timedelta(days=2), D + timedelta(days=3)).status_code == 201  # checkout day == next checkin


def test_concurrent_bookings_never_exceed_rooms(client, prop):
    p = prop(rooms=5)
    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(lambda i: _book(client, p.id, name=f"g{i}").status_code, range(40)))
    assert codes.count(201) == 5
    assert codes.count(409) == 35


def test_search_excludes_sold_out_property(client, prop):
    city = "SoldOutCity"
    a, b = prop(rooms=1, city=city, price=50), prop(rooms=1, city=city, price=60)
    _book(client, a.id)
    ids = [x["id"] for x in _search(client, city, checkin=D, checkout=D + timedelta(days=2)).json()["results"]]
    assert ids == [b.id]
    # a different, non-overlapping date range still shows both
    later = _search(client, city, checkin=D + timedelta(days=10), checkout=D + timedelta(days=12)).json()
    assert later["total"] == 2


def test_search_filters_and_sorting(client, prop):
    city = "FilterCity"
    prop(price=300, rating=4.9, city=city); prop(price=80, rating=3.2, city=city); prop(price=150, rating=4.1, city=city)
    cheap = _search(client, city, max_price=200, sort="price_asc").json()
    assert [r["price_per_night"] for r in cheap["results"]] == [80, 150]
    good = _search(client, city, min_rating=4.0, sort="rating").json()
    assert [r["rating"] for r in good["results"]] == [4.9, 4.1]


def test_pagination(client, prop):
    city = "PageCity"
    for _ in range(5):
        prop(city=city)
    r1 = _search(client, city, page_size=2, page=1).json()
    r3 = _search(client, city, page_size=2, page=3).json()
    assert r1["total"] == 5 and len(r1["results"]) == 2 and len(r3["results"]) == 1


def test_cache_hit_then_invalidated_by_booking(client, prop):
    city = "CacheCity"
    p = prop(rooms=1, city=city)
    kw = dict(checkin=D, checkout=D + timedelta(days=1))
    first = _search(client, city, **kw)
    second = _search(client, city, **kw)
    assert first.headers["X-Cache"] == "MISS" and second.headers["X-Cache"] == "HIT"
    _book(client, p.id, D, D + timedelta(days=1))
    third = _search(client, city, **kw)
    assert third.headers["X-Cache"] == "MISS" and third.json()["total"] == 0  # stale result not served


def test_validation_errors(client, prop):
    p = prop(guests=2)
    assert _book(client, p.id, guests=5).status_code == 400
    assert _book(client, p.id, D, D).status_code == 400
    assert _book(client, p.id, date.today() - timedelta(days=1), date.today()).status_code == 400
    assert _book(client, 999_999).status_code == 404
    assert client.get("/api/search", params={"city": "x", "checkin": D.isoformat()}).status_code == 400


def test_token_bucket_limits_bursts():
    tb = TokenBucket(rate_per_sec=0.001, burst=3)
    assert [tb.allow("a") for _ in range(5)] == [True, True, True, False, False]
    assert tb.allow("b")  # separate client unaffected
