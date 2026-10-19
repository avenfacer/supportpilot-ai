from fastapi.testclient import TestClient

from app.api.deps import get_readiness_checks
from app.core.config import Settings
from app.main import create_app


def _client(checks: dict[str, bool]) -> TestClient:
    app = create_app(Settings(app_env="test", _env_file=None))  # type: ignore[call-arg]
    app.dependency_overrides[get_readiness_checks] = lambda: {
        name: (lambda value=value: value) for name, value in checks.items()
    }
    return TestClient(app)


def test_health_returns_ok_and_request_id() -> None:
    response = _client({}).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_ready_reports_ready_when_all_checks_pass() -> None:
    response = _client({"database": True}).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": True}}


def test_ready_returns_503_when_a_check_fails() -> None:
    response = _client({"database": True, "pgvector": False}).get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_unknown_route_returns_safe_error_shape() -> None:
    response = _client({}).get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
