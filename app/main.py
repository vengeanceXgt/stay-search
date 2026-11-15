import os
import time
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import booking as booking_svc
from .cache import make_cache
from .db import Base, engine, get_session
from .models import Property
from .ratelimit import TokenBucket
from .search import SORTS, search

Base.metadata.create_all(engine)
app = FastAPI(title="Stay Search", version="1.0.0")
cache = make_cache()
write_limiter = TokenBucket(rate_per_sec=float(os.getenv("WRITE_RATE", "5")), burst=int(os.getenv("WRITE_BURST", "20")))
STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


@app.exception_handler(booking_svc.BookingError)
def booking_error(_, exc: booking_svc.BookingError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.2f}"
    return response


@app.get("/api/cities")
def cities(session: Session = Depends(get_session)):
    return sorted(session.execute(select(Property.city).distinct()).scalars())


@app.get("/api/search")
def api_search(
    response: Response,
    city: str,
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    min_rating: float | None = Query(None, ge=0, le=5),
    checkin: date | None = None,
    checkout: date | None = None,
    guests: int = Query(1, ge=1, le=10),
    sort: str = Query("price_asc", pattern="^(price_asc|price_desc|rating)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
):
    if (checkin is None) != (checkout is None):
        raise HTTPException(400, "provide both checkin and checkout, or neither")
    if checkin and checkout and checkout <= checkin:
        raise HTTPException(400, "checkout must be after checkin")
    params = dict(city=city, min_price=min_price, max_price=max_price, min_rating=min_rating,
                  checkin=checkin, checkout=checkout, guests=guests, sort=sort, page=page, page_size=page_size)
    key = None
    if cache is not None:
        key = f"s:{city}:v{cache.version(city)}:" + "|".join(f"{k}={v}" for k, v in sorted(params.items()))
        hit = cache.get(key)
        if hit is not None:
            response.headers["X-Cache"] = "HIT"
            return hit
    result = search(session, **params)
    if cache is not None:
        cache.set(key, result, ttl=60)
    response.headers["X-Cache"] = "MISS"
    return result


class BookingIn(BaseModel):
    property_id: int
    guest_name: str = Field(min_length=1, max_length=120)
    checkin: date
    checkout: date
    guests: int = Field(1, ge=1, le=10)


@app.post("/api/bookings", status_code=201)
def create_booking(body: BookingIn, request: Request, session: Session = Depends(get_session)):
    client = request.client.host if request.client else "unknown"
    if not write_limiter.allow(client):
        raise HTTPException(429, "rate limit exceeded")
    b = booking_svc.book(session, body.property_id, body.guest_name, body.checkin, body.checkout, body.guests)
    prop = session.get(Property, b.property_id)
    if cache is not None and prop is not None:
        cache.bump(prop.city)  # availability changed: invalidate cached searches for this city
    return {"id": b.id, "property_id": b.property_id, "checkin": b.checkin, "checkout": b.checkout, "total_price": b.total_price}


@app.get("/api/stats")
def stats():
    return cache.stats() if cache is not None else {"backend": "disabled"}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
