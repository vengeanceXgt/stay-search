"""Schema. Availability is tracked per property per night (Inventory), the standard hotel design:
a booking succeeds only if every night in its range still has a free room."""
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    price_per_night: Mapped[int] = mapped_column(Integer)  # whole currency units
    rating: Mapped[float] = mapped_column(Float)
    total_rooms: Mapped[int] = mapped_column(Integer)
    max_guests: Mapped[int] = mapped_column(Integer, default=2)

    __table_args__ = (
        Index("ix_prop_city_price", "city", "price_per_night"),
        Index("ix_prop_city_rating", "city", "rating"),
    )


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    night: Mapped[date] = mapped_column(Date)
    booked: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("property_id", "night", name="uq_inventory_prop_night"),)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    guest_name: Mapped[str] = mapped_column(String(120))
    checkin: Mapped[date] = mapped_column(Date)
    checkout: Mapped[date] = mapped_column(Date)
    total_price: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
