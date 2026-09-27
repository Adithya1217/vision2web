import pytest

from app.config import Settings


@pytest.mark.parametrize("raw", ["postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"])
def test_provider_database_urls_use_psycopg(raw):
    assert Settings(database_url=raw).database_url == "postgresql+psycopg://u:p@h:5432/db"


def test_explicit_driver_kept():
    url = "postgresql+psycopg://u@h/db"
    assert Settings(database_url=url).database_url == url


def test_production_rejects_weak_jwt_secret(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "get_settings", lambda: Settings(environment="production", jwt_secret="short"))
    with pytest.raises(RuntimeError):
        main.create_app()
