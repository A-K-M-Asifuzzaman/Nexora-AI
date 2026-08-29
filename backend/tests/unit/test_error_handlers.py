from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import install_exception_handlers


class RegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12)


def test_validation_error_never_echoes_password_input() -> None:
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/register")
    async def register(_payload: RegistrationPayload) -> dict[str, bool]:
        return {"accepted": True}

    secret = "tiny-secret"  # noqa: S105 -- test credential used to assert redaction
    response = TestClient(app).post("/register", json={"password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unhandled_exception_uses_safe_envelope() -> None:
    app = FastAPI(debug=False)
    install_exception_handlers(app)

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("sensitive internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/explode")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "sensitive internal detail" not in response.text
