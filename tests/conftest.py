import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["WRITE_BURST"] = "10000"  # keep the rate limiter out of the way except in its own test

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Property  # noqa: E402


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture()
def prop():
    """Create a fresh property with 2 rooms in its own city (so tests don't interfere)."""
    def _make(rooms=2, price=100, rating=4.5, city=None, guests=4):
        with SessionLocal() as s:
            p = Property(name="Test Inn", city=city or f"City{os.urandom(3).hex()}", price_per_night=price,
                         rating=rating, total_rooms=rooms, max_guests=guests)
            s.add(p)
            s.commit()
            return p
    return _make
