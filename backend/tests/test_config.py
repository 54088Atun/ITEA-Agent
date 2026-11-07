import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.cors import configure_cors

DEFAULT_SECRET_KEY = "change-this-to-a-random-secret-key"
DEFAULT_DATABASE_URL = "mysql+pymysql://root:123456@localhost:3306/itea_agent?charset=utf8mb4"
TEST_SECRET_KEY = "test-only-production-secret-key"
TEST_DATABASE_URL = "mysql+pymysql://itea:test-only-password@db.internal:3306/itea_agent"


def production_settings(**overrides):
    values = {
        "_env_file": None,
        "ENVIRONMENT": "production",
        "SECRET_KEY": TEST_SECRET_KEY,
        "DATABASE_URL": TEST_DATABASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_non_production_defaults_remain_available(environment):
    settings = Settings(
        _env_file=None,
        ENVIRONMENT=environment,
        SECRET_KEY=DEFAULT_SECRET_KEY,
        DATABASE_URL=DEFAULT_DATABASE_URL,
    )

    assert settings.SECRET_KEY == DEFAULT_SECRET_KEY
    assert settings.DATABASE_URL == DEFAULT_DATABASE_URL


@pytest.mark.parametrize(
    ("field", "default_value"),
    [
        ("SECRET_KEY", DEFAULT_SECRET_KEY),
        ("DATABASE_URL", DEFAULT_DATABASE_URL),
    ],
)
def test_production_rejects_default_required_settings(field, default_value):
    with pytest.raises(RuntimeError) as exc_info:
        production_settings(**{field: default_value})

    assert field in str(exc_info.value)


@pytest.mark.parametrize("field", ["SECRET_KEY", "DATABASE_URL"])
def test_production_rejects_empty_required_settings(field):
    with pytest.raises(RuntimeError) as exc_info:
        production_settings(**{field: ""})

    assert field in str(exc_info.value)


def test_production_accepts_explicit_secure_settings():
    settings = production_settings()

    assert settings.ENVIRONMENT == "production"
    assert settings.SECRET_KEY == TEST_SECRET_KEY
    assert settings.DATABASE_URL == TEST_DATABASE_URL


def test_production_validation_error_does_not_expose_configuration_values():
    with pytest.raises(RuntimeError) as exc_info:
        production_settings(DATABASE_URL=DEFAULT_DATABASE_URL)

    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert TEST_SECRET_KEY not in message
    assert DEFAULT_DATABASE_URL not in message
    assert "123456" not in message


# ---------- CORS 显式来源 ----------

def test_cors_origins_are_parsed_and_never_wildcard_in_development():
    settings = Settings(_env_file=None, ENVIRONMENT="development")

    assert "*" not in settings.cors_origins
    assert all(origin.startswith("http") for origin in settings.cors_origins)


def test_production_rejects_wildcard_cors_origin():
    with pytest.raises(RuntimeError) as exc_info:
        production_settings(CORS_ALLOW_ORIGINS="https://itea.example.edu.cn,*")

    assert "CORS_ALLOW_ORIGINS" in str(exc_info.value)


def _cors_client(origins: str = "https://itea.example.edu.cn") -> TestClient:
    config = Settings(
        _env_file=None, ENVIRONMENT="test", CORS_ALLOW_ORIGINS=origins,
    )
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    configure_cors(app, config)
    return TestClient(app)


def test_allowed_origin_gets_credentials_header():
    response = _cors_client().get(
        "/ping", headers={"Origin": "https://itea.example.edu.cn"},
    )

    assert response.headers["access-control-allow-origin"] == "https://itea.example.edu.cn"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unlisted_origin_is_not_allowed():
    response = _cors_client().get(
        "/ping", headers={"Origin": "https://evil.example.com"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_preflight_only_allows_configured_origin():
    client = _cors_client()

    allowed = client.options("/ping", headers={
        "Origin": "https://itea.example.edu.cn",
        "Access-Control-Request-Method": "GET",
    })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://itea.example.edu.cn"

    denied = client.options("/ping", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-origin" not in denied.headers
