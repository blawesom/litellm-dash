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
    # Use unreachable port to test mock validation trigger when offline
    client = LiteLLMClient(base_url="http://127.0.0.1:59999", allow_mock=True)
    res = await client.validate_user_and_key("alice", "sk-valid-test-key")
    assert res["valid"] is True
    assert res["user_id"] == "alice"

@pytest.mark.asyncio
async def test_litellm_client_aggregation():
    client = LiteLLMClient(base_url="http://127.0.0.1:59999", allow_mock=True)
    metrics = await client.get_dashboard_metrics("alice", "sk-valid-key")
    assert "summary" in metrics
    assert "daily_trend" in metrics
    assert "model_breakdown" in metrics
    assert metrics["summary"]["total_tokens"] >= 0

@pytest.mark.asyncio
async def test_litellm_client_get_served_models():
    client = LiteLLMClient(base_url="http://127.0.0.1:59999", allow_mock=True)
    models = await client.get_served_models()
    assert isinstance(models, list)

@pytest.mark.asyncio
async def test_production_mode_errors_when_proxy_unreachable():
    client = LiteLLMClient(base_url="http://127.0.0.1:59999", allow_mock=False)
    res = await client.validate_user_and_key("alice", "sk-valid-test-key")
    assert res["valid"] is False
    assert "error" in res
    assert "Could not connect to LiteLLM Proxy" in res["error"]

    with pytest.raises(RuntimeError) as exc_info:
        await client.get_dashboard_metrics("alice", "sk-valid-key")
    assert "Could not connect to LiteLLM Proxy" in str(exc_info.value)

def test_api_stats_returns_502_on_proxy_failure(monkeypatch):
    # Monkeypatch global litellm_client in app.main to point to an unreachable proxy
    from app.main import litellm_client as main_client
    monkeypatch.setattr(main_client, "base_url", "http://127.0.0.1:59999")
    monkeypatch.setattr(main_client, "allow_mock", False)

    token = create_session_token("alice", "sk-test-key")
    client.cookies.set("litellm_dash_session", token)
    response = client.get("/api/dashboard/stats")
    # In production default mode (allow_mock=False), unreachable proxy returns 502
    assert response.status_code == 502
    data = response.json()
    assert data["error"] is True
    assert "Could not connect to LiteLLM Proxy" in data["detail"]

def test_clean_model_name_extraction():
    c = LiteLLMClient(allow_mock=True)
    raw_logs = [
        {"model": "hosted_vllm/Qwen/Qwen3.5-27B-FP8", "prompt_tokens": 100, "completion_tokens": 50, "spend": 0.01},
        {"model": "openai/gpt-4o", "prompt_tokens": 200, "completion_tokens": 100, "spend": 0.02}
    ]
    res = c._aggregate_metrics(raw_logs, "2026-07-01", "2026-07-24")
    model_names = [m["model"] for m in res["model_breakdown"]]
    assert "Qwen3.5-27B-FP8" in model_names
    assert "gpt-4o" in model_names
    assert "hosted_vllm/Qwen/Qwen3.5-27B-FP8" not in model_names

@pytest.mark.asyncio
async def test_litellm_client_metrics_caching():
    client = LiteLLMClient(allow_mock=True)
    res1 = await client.get_dashboard_metrics("alice", "sk-valid-key", "2026-07-01", "2026-07-24")
    res2 = await client.get_dashboard_metrics("alice", "sk-valid-key", "2026-07-01", "2026-07-24")
    assert res1 is res2  # Returned exact cached dict instance within TTL

    await client.aclose()
    assert client._client is None

@pytest.mark.asyncio
async def test_summarized_logs_aggregation():
    client = LiteLLMClient(allow_mock=True)
    summarized_logs = [
        {
            "startTime": "2026-07-24T10:00:00Z",
            "spend": 0.15,
            "models": {
                "hosted_vllm/Qwen/Qwen3.5-27B-FP8": 0.10,
                "openai/gpt-4o": 0.05
            }
        }
    ]
    res = client._aggregate_metrics(summarized_logs, "2026-07-24", "2026-07-24")
    assert res["summary"]["total_spend"] == 0.15
    model_breakdown = res["model_breakdown"]
    models = [m["model"] for m in model_breakdown]
    assert "Qwen3.5-27B-FP8" in models
    assert "gpt-4o" in models
    await client.aclose()
