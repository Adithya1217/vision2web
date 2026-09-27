import os
import uuid

os.environ.setdefault("MSME_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/msme_test")
os.environ.setdefault("MSME_BCRYPT_ROUNDS", "4")
os.environ.setdefault("MSME_JWT_SECRET", "test-secret-with-enough-length-for-hs256")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.ddl import install_create_all_hooks  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    install_create_all_hooks()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


class Api:
    """Thin authenticated client. Mutations get a fresh Idempotency-Key unless one is given."""

    def __init__(self, client: TestClient, token: str | None = None):
        self.client = client
        self.token = token

    def _headers(self, key=None, mutate=False):
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if mutate:
            h["Idempotency-Key"] = key or str(uuid.uuid4())
        return h

    def get(self, path, **params):
        return self.client.get(f"/api/v1{path}", params=params, headers=self._headers())

    def post(self, path, json=None, key=None, headers=None):
        return self.client.post(f"/api/v1{path}", json=json, headers={**self._headers(key, True), **(headers or {})})

    def put(self, path, json=None, key=None):
        return self.client.put(f"/api/v1{path}", json=json, headers=self._headers(key, True))

    def patch(self, path, json=None, key=None):
        return self.client.patch(f"/api/v1{path}", json=json, headers=self._headers(key, True))

    def delete(self, path, key=None):
        return self.client.delete(f"/api/v1{path}", headers=self._headers(key, True))

    def ok(self, resp, status=(200, 201)):
        statuses = status if isinstance(status, tuple) else (status,)
        assert resp.status_code in statuses, resp.text
        return resp.json()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def register_shop(client, name="Shop A", email="owner@shopa.example.com", state_code="29", timezone="Asia/Kolkata"):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "shop": {"name": name, "state_code": state_code, "timezone": timezone},
            "owner_name": f"{name} Owner",
            "email": email,
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text
    return Api(client, r.json()["access_token"])


def add_user(owner: Api, email: str, role: str) -> Api:
    owner.ok(owner.post("/users", {"email": email, "full_name": email, "password": "password123", "role": role}))
    r = owner.client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return Api(owner.client, r.json()["access_token"])


@pytest.fixture
def owner(client):
    return register_shop(client)


@pytest.fixture
def manager(owner):
    return add_user(owner, "manager@shopa.example.com", "manager")


@pytest.fixture
def staff(owner):
    return add_user(owner, "staff@shopa.example.com", "staff")


@pytest.fixture
def other_owner(client):
    return register_shop(client, name="Shop B", email="owner@shopb.example.com", state_code="27")


def make_product(api: Api, sku="SKU-1", price="100.00", gst="18", qty=10, **extra):
    body = {"name": extra.pop("name", f"Product {sku}"), "sku": sku, "sale_price": price, "gst_rate": gst,
            "opening_quantity": qty, **extra}
    return api.ok(api.post("/products", body))


def make_customer(api: Api, name="Ramesh", **extra):
    return api.ok(api.post("/customers", {"name": name, **extra}))


def sell(api: Api, items, customer_id=None, payments=None, place_of_supply=None):
    """Create and post an invoice; ``items`` is a list of (product_id, qty) or dicts."""
    lines = [i if isinstance(i, dict) else {"product_id": i[0], "quantity": i[1]} for i in items]
    body = {"items": lines, "customer_id": customer_id}
    if place_of_supply:
        body["place_of_supply"] = place_of_supply
    draft = api.ok(api.post("/invoices", body))
    return api.post(f"/invoices/{draft['id']}/post", {"payments": payments or []})
