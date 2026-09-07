from api.settings import Settings


def test_bare_postgresql_scheme_is_rewritten_to_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_explicit_psycopg_driver_is_left_unchanged() -> None:
    url = "postgresql+psycopg://user:pass@host:5432/db"
    settings = Settings(database_url=url)
    assert settings.database_url == url
