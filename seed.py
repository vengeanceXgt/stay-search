"""Populate the database with synthetic properties:  python seed.py 100000"""
import random
import sys

from app.db import Base, SessionLocal, engine
from app.models import Property

CITIES = ["Bangkok", "Mumbai", "Singapore", "Bali", "Tokyo", "Dubai", "Delhi", "Goa", "Phuket", "Seoul",
          "Kuala Lumpur", "Hanoi", "Manila", "Jaipur", "Colombo", "Kyoto", "Osaka", "Hong Kong", "Taipei", "Pune"]
KINDS = ["Grand", "Boutique", "Riverside", "Garden", "Skyline", "Heritage", "Harbour", "Palm", "Central", "Urban"]
TYPES = ["Hotel", "Suites", "Resort", "Inn", "Residence", "Lodge"]


def seed(n: int = 100_000, rng_seed: int = 1):
    rng = random.Random(rng_seed)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if s.query(Property).count():
            print("already seeded")
            return
        batch = []
        for i in range(n):
            batch.append(Property(
                name=f"{rng.choice(KINDS)} {rng.choice(TYPES)} {i}",
                city=rng.choice(CITIES),
                price_per_night=rng.randint(25, 400),
                rating=round(rng.uniform(2.5, 5.0), 1),
                total_rooms=rng.randint(1, 30),
                max_guests=rng.choice([2, 2, 3, 4, 6]),
            ))
            if len(batch) == 5000:
                s.bulk_save_objects(batch)
                batch = []
        if batch:
            s.bulk_save_objects(batch)
        s.commit()
        print(f"seeded {n} properties")


if __name__ == "__main__":
    seed(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000)
