import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_session_token, verify_session_token
from app.litellm_client import LiteLLMClient

client = TestClient(app)

def test_root_redirect_unauthenticated():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

def test_login_page_renders():
    response = client.get("/login")
    assert response.status_code == 200
    assert "Analytics Dashboard" in response.text
    assert "LiteLLM API Key" in response.text

def test_session_token_serialization():
    user_id = "test_user@example.com"
    api_key = "sk-litellm-test-key-12345"
    token = create_session_token(user_id, api_key)
    assert token is not None

    payload = verify_session_token(token)
    assert payload is not None
    assert payload["user_id"] == user_id
    assert payload["api_key"] == api_key

def test_invalid_session_token():
    payload = verify_session_token("invalid-garbage-token-string")
    assert payload is None

def test_dashboard_unauthorized():
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

@pytest.mark.asyncio
async def test_litellm_client_mock_validation():
    client = LiteLLMClient()
    res = await client.validate_user_and_key("alice", "sk-valid-test-key")
    assert res["valid"] is True
    assert res["user_id"] == "alice"

@pytest.mark.asyncio
async def test_litellm_client_aggregation():
    client = LiteLLMClient()
    metrics = await client.get_dashboard_metrics("alice", "sk-valid-key")
    assert "summary" in metrics
    assert "daily_trend" in metrics
    assert "model_breakdown" in metrics
    assert metrics["summary"]["total_tokens"] >= 0
