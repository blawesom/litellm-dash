# LiteLLM User Analytics & Consumption Dashboard

A lightweight, high-performance Python web service designed to run alongside a **LiteLLM Proxy** deployment behind **HAProxy**. It authenticates users via their LiteLLM Virtual Keys and usernames, validates credentials against LiteLLM Proxy management APIs, and displays an interactive dashboard of daily token consumption, costs, and model usage breakdown.

---

## Features

- 🔑 **LiteLLM Key & User Authentication**: Validates `user_id` and `sk-...` API key directly against LiteLLM Proxy management endpoints (`/key/info` & `/user/info`).
- 🔒 **Secure Session Management**: Signed HTTP-only session cookies holding verified identity payload.
- 📊 **KPI Overview Cards**: Total Spend ($), Total Tokens (Prompt + Completion), Active Models Count.
- 📈 **Daily Consumption Charts**: Interactive stacked bar & line charts for daily prompt vs. completion tokens and daily cost ($) using Chart.js.
- 🍩 **Model Token Share**: Donut chart visualizing token allocation across models (e.g. `gpt-4o`, `claude-3-5-sonnet`, `llama-3.1-70b`).
- 📋 **Aggregated Data Table**: Daily breakdown of prompt/completion tokens and spend.
- 🔀 **HAProxy Ready**: Designed for non-Docker native deployment routed behind HAProxy with Systemd process supervision.

---

## Required LiteLLM Proxy Configuration

To allow the dashboard to fetch user key and spend log information, LiteLLM Proxy must be configured with a **Master Key** and a **Database URL** in its `config.yaml`:

```yaml
general_settings:
  # 1. Master Key (Required for administrative endpoints /key/info & /spend/logs)
  master_key: "sk-litellm-master-secret-key"

  # 2. Database Connection (Required for LiteLLM to persist spend logs)
  database_url: "postgresql://litellm_user:password@127.0.0.1:5432/litellm_db"

  # 3. Optional Settings
  store_prompts_in_spend_logs: false
```

---

## Quick Start (Native Host Setup)

### 1. Clone & Set Up Virtual Environment

```bash
cd /home/outscale/litellm-dash

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Edit `.env` to set your LiteLLM Master Key and settings:

```ini
LITELLM_BASE_URL=http://127.0.0.1:4000
LITELLM_MASTER_KEY=sk-litellm-master-secret-key
SECRET_KEY=generate-a-secure-random-key-here
SESSION_COOKIE_NAME=litellm_dash_session
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=info
```

### 3. Run Application

```bash
python run.py
```

Access the dashboard locally at `http://127.0.0.1:8000`.

---

## Production Deployment (HAProxy + Systemd)

### 1. Systemd Service Configuration

Copy the unit file to `/etc/systemd/system/litellm-dash.service`:

```bash
sudo cp config/litellm-dash.service /etc/systemd/system/litellm-dash.service
sudo systemctl daemon-reload
sudo systemctl enable --now litellm-dash
```

Verify service status:

```bash
sudo systemctl status litellm-dash
```

### 2. HAProxy Reverse Proxy Setup

Add the routing configuration from `config/haproxy.cfg.example` to your `/etc/haproxy/haproxy.cfg`:

```haproxy
frontend http_in
    bind *:80
    option forwardfor
    http-request set-header X-Forwarded-Proto http

    # Route dashboard paths to Python FastAPI (Port 8000)
    acl is_dashboard path_beg /dash /static /login /dashboard /api/auth /api/dashboard /logout
    use_backend dashboard_backend if is_dashboard

    # Route default LLM requests to LiteLLM Proxy (Port 4000)
    default_backend litellm_backend

backend dashboard_backend
    mode http
    server dash_app1 127.0.0.1:8000 check

backend litellm_backend
    mode http
    server litellm_proxy1 127.0.0.1:4000 check
```

Reload HAProxy to apply:

```bash
sudo systemctl reload haproxy
```

---

## Testing

Run unit & integration test suite:

```bash
./venv/bin/pytest -v
```
