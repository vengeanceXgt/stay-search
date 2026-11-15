"""Booking with per-night inventory. Atomic: either every night is reserved or none are."""
import threading
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import IS_SQLITE
from .models import Booking, Inventory, Property

_sqlite_lock = threading.Lock()


class BookingError(Exception):
    status_code = 400


class SoldOut(BookingError):
    status_code = 409


class NotFound(BookingError):
    status_code = 404


def nights(checkin: date, checkout: date) -> list[date]:
    return [checkin + timedelta(days=i) for i in range((checkout - checkin).days)]


def book(session: Session, property_id: int, guest_name: str, checkin: date, checkout: date, guests: int) -> Booking:
    if checkout <= checkin:
        raise BookingError("checkout must be after checkin")
    if (checkout - checkin).days > 30:
        raise BookingError("maximum stay is 30 nights")
    if checkin < date.today():
        raise BookingError("checkin cannot be in the past")

    def _do() -> Booking:
        # Lock the property row (real row lock on PostgreSQL; no-op on SQLite, covered by _sqlite_lock).
        prop = session.execute(select(Property).where(Property.id == property_id).with_for_update()).scalar_one_or_none()
        if prop is None:
            raise NotFound("property not found")
        if guests > prop.max_guests:
            raise BookingError(f"property sleeps at most {prop.max_guests} guests")
        rows = {
            r.night: r
            for r in session.execute(
                select(Inventory).where(Inventory.property_id == property_id, Inventory.night >= checkin, Inventory.night < checkout)
            ).scalars()
        }
        wanted = nights(checkin, checkout)
        if any(rows.get(n) is not None and rows[n].booked >= prop.total_rooms for n in wanted):
            raise SoldOut("no rooms left for at least one of the selected nights")
        for n in wanted:
            row = rows.get(n)
            if row is None:
                row = Inventory(property_id=property_id, night=n, booked=0)
                session.add(row)
            row.booked += 1
        booking = Booking(property_id=property_id, guest_name=guest_name, checkin=checkin, checkout=checkout,
                          total_price=prop.price_per_night * len(wanted))
        session.add(booking)
        session.commit()
        return booking

    try:
        if IS_SQLITE:
            with _sqlite_lock:
                return _do()
        return _do()
    except BookingError:
        session.rollback()
        raise
