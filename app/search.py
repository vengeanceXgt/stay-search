from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from .models import Inventory, Property

SORTS = {
    "price_asc": (Property.price_per_night.asc(), Property.id.asc()),
    "price_desc": (Property.price_per_night.desc(), Property.id.asc()),
    "rating": (Property.rating.desc(), Property.id.asc()),
}


def search(session: Session, *, city: str, min_price=None, max_price=None, min_rating=None,
           checkin: date | None = None, checkout: date | None = None, guests: int = 1,
           sort: str = "price_asc", page: int = 1, page_size: int = 20) -> dict:
    conds = [Property.city == city, Property.max_guests >= guests]
    if min_price is not None:
        conds.append(Property.price_per_night >= min_price)
    if max_price is not None:
        conds.append(Property.price_per_night <= max_price)
    if min_rating is not None:
        conds.append(Property.rating >= min_rating)
    if checkin and checkout:
        # Available = no night in the range is already fully booked.
        sold_out = exists().where(and_(
            Inventory.property_id == Property.id,
            Inventory.night >= checkin, Inventory.night < checkout,
            Inventory.booked >= Property.total_rooms,
        ))
        conds.append(~sold_out)

    total = session.execute(select(func.count()).select_from(Property).where(*conds)).scalar_one()
    rows = session.execute(
        select(Property).where(*conds).order_by(*SORTS[sort]).limit(page_size).offset((page - 1) * page_size)
    ).scalars()
    return {
        "total": total, "page": page, "page_size": page_size,
        "results": [{"id": p.id, "name": p.name, "city": p.city, "price_per_night": p.price_per_night,
                     "rating": p.rating, "max_guests": p.max_guests} for p in rows],
    }
