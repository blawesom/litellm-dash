import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import httpx
from app.config import settings

logger = logging.getLogger("litellm_dash.client")

class LiteLLMClient:
    def __init__(
        self,
        base_url: str = settings.LITELLM_BASE_URL,
        master_key: str = settings.LITELLM_MASTER_KEY,
        allow_mock: Optional[bool] = None
    ):
        self.base_url = base_url.rstrip("/")
        self.master_key = master_key
        self.allow_mock = settings.ALLOW_MOCK_FALLBACK if allow_mock is None else allow_mock
        self._client: Optional[httpx.AsyncClient] = None
        self._metrics_cache: Dict[str, Any] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
            )
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json"
        }

    async def get_served_models(self, api_key: Optional[str] = None) -> List[str]:
        """
        Fetches the active list of models served by LiteLLM Proxy via /models or /v1/models endpoints.
        """
        client = self._get_client()
        endpoints = ["/models", "/v1/models", "/model/info"]
        for path in endpoints:
            try:
                url = f"{self.base_url}{path}"
                headers = self._headers()
                if api_key and not self.master_key:
                    headers = {"Authorization": f"Bearer {api_key}"}

                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    model_list = []
                    if isinstance(data, list):
                        raw_list = data
                    elif isinstance(data, dict):
                        raw_list = data.get("data", data.get("models", []))
                    else:
                        raw_list = []

                    for item in raw_list:
                        if isinstance(item, dict):
                            m_id = item.get("id") or item.get("model_name") or item.get("model")
                            if m_id:
                                model_list.append(str(m_id))
                        elif isinstance(item, str):
                            model_list.append(item)

                    if model_list:
                        logger.info(f"Retrieved {len(model_list)} served models from LiteLLM Proxy ({path})")
                        return sorted(list(set(model_list)))
            except Exception as e:
                logger.debug(f"Could not fetch served models from {path}: {e}")

        return []

    async def validate_user_and_key(self, username: str, api_key: str) -> Dict[str, Any]:
        """
        Validates the provided API key and username against LiteLLM Proxy.
        Returns dict with status, user_id, and key_info metadata.
        """
        if not api_key:
            return {"valid": False, "error": "API Key is required."}
        if not username:
            return {"valid": False, "error": "Username / User ID is required."}

        # Clean inputs
        clean_user = username.strip()
        clean_key = api_key.strip()

        logger.info(f"Validating key for user '{clean_user}' against LiteLLM Proxy at {self.base_url}")

        client = self._get_client()
        try:
            # 1. Query /key/info endpoint using Master Key
            from urllib.parse import quote
            url = f"{self.base_url}/key/info?key={quote(clean_key)}"
            response = await client.get(url, headers=self._headers())

            if response.status_code == 200:
                data = response.json()
                key_info = data.get("info", data)
                assigned_user = key_info.get("user_id") or key_info.get("metadata", {}).get("user_id")
                key_alias = key_info.get("key_alias", "")

                # Verify username match
                if assigned_user:
                    if assigned_user.lower() != clean_user.lower():
                        logger.warning(f"Key belongs to user '{assigned_user}', but username '{clean_user}' was provided")
                        return {
                            "valid": False,
                            "error": f"API Key belongs to user '{assigned_user}', not '{clean_user}'."
                        }
                else:
                    logger.info(f"Key has no explicit assigned user_id. Assigning/binding session to '{clean_user}'.")

                return {
                    "valid": True,
                    "user_id": clean_user,
                    "key_alias": key_alias,
                    "models": key_info.get("models", []),
                    "max_budget": key_info.get("max_budget"),
                    "spend": key_info.get("spend", 0.0)
                }

            elif response.status_code in (401, 403, 404):
                logger.warning(f"Key validation failed with HTTP status {response.status_code}")
                return {"valid": False, "error": "Invalid LiteLLM API Key or Key not found."}

            else:
                logger.error(f"LiteLLM key/info error status {response.status_code}: {response.text}")
                return await self._validate_fallback_user_info(client, clean_user, clean_key)

        except httpx.ConnectError:
            logger.error(f"Could not connect to LiteLLM Proxy at {self.base_url}")
            if self.allow_mock:
                return self._dev_mock_validation(clean_user, clean_key)
            return {"valid": False, "error": f"Could not connect to LiteLLM Proxy at {self.base_url}. Please verify LiteLLM Proxy is running."}

        except Exception as e:
            logger.error(f"Exception during key validation: {e}")
            if self.allow_mock:
                return self._dev_mock_validation(clean_user, clean_key)
            return {"valid": False, "error": f"Error connecting to LiteLLM Proxy: {str(e)}"}

    async def _validate_fallback_user_info(self, client: httpx.AsyncClient, username: str, api_key: str) -> Dict[str, Any]:
        """
        Secondary validation fallback via /user/info endpoint.
        """
        try:
            from urllib.parse import quote
            url = f"{self.base_url}/user/info?user_id={quote(username)}"
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                user_info = data.get("user_info", data)
                user_keys = user_info.get("keys", [])
                if api_key in user_keys or any(k.get("token") == api_key for k in user_keys if isinstance(k, dict)):
                    return {"valid": True, "user_id": username, "models": []}
            return {"valid": False, "error": "Invalid API key or username mismatch."}
        except Exception as e:
            return {"valid": False, "error": f"Validation failed: {str(e)}"}

    def _dev_mock_validation(self, username: str, api_key: str) -> Dict[str, Any]:
        """
        Development mock validation when LiteLLM is not running locally.
        """
        logger.info(f"Using development mock validation for user '{username}'")
        if api_key.startswith("sk-"):
            return {
                "valid": True,
                "user_id": username,
                "key_alias": "dev-key",
                "models": ["gpt-4o", "claude-3-5-sonnet", "llama-3.1-70b"],
                "spend": 12.45
            }
        return {"valid": False, "error": "Invalid API key format. Key should start with 'sk-'."}

    async def get_dashboard_metrics(
        self,
        user_id: str,
        api_key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_models: Optional[List[str]] = None,
        ttl_seconds: int = 15
    ) -> Dict[str, Any]:
        """
        Queries LiteLLM spend logs for the user and aggregates metrics into daily trends and model breakdown,
        utilizing a TTL cache to minimize database hits.
        """
        today = datetime.now().date()
        if not end_date:
            end_date = today.strftime("%Y-%m-%d")
        if not start_date:
            start_date = (today - timedelta(days=6)).strftime("%Y-%m-%d")

        # Check TTL Cache
        cache_key = f"{user_id}:{start_date}:{end_date}"
        now = datetime.now()
        if cache_key in self._metrics_cache:
            cached_res, cached_time = self._metrics_cache[cache_key]
            if (now - cached_time).total_seconds() < ttl_seconds:
                logger.debug(f"Returning cached dashboard metrics for '{cache_key}'")
                return cached_res

        # 1. Fetch transaction logs directly from LiteLLM spend logs
        raw_logs = await self._fetch_spend_logs(user_id, api_key, start_date, end_date, user_models=user_models)

        # 2. Aggregate metrics incorporating models extracted from transaction logs
        result = self._aggregate_metrics(raw_logs, start_date, end_date, user_models=user_models)
        self._metrics_cache[cache_key] = (result, now)
        return result

    async def _fetch_spend_logs(
        self,
        user_id: str,
        api_key: str,
        start_date: str,
        end_date: str,
        user_models: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches spend and token logs from LiteLLM Proxy using optimized /user/daily/activity endpoint with fallback to /spend/logs.
        """
        from urllib.parse import quote
        client = self._get_client()
        safe_user = quote(user_id)
        safe_start = quote(start_date)
        safe_end = quote(end_date)

        try:
            # 1. Primary optimized query: /user/daily/activity (queries LiteLLM_DailyUserSpend table for tokens + spend)
            url_activity = f"{self.base_url}/user/daily/activity?user_id={safe_user}&start_date={safe_start}&end_date={safe_end}&page_size=1000"
            resp_activity = await client.get(url_activity, headers=self._headers())

            if resp_activity.status_code == 200:
                data = resp_activity.json()
                results = data.get("results")
                if isinstance(results, list) and len(results) > 0:
                    return results

            # 2. Secondary fallback: /spend/logs?summarize=true
            url_spend = f"{self.base_url}/spend/logs?user_id={safe_user}&start_date={safe_start}&end_date={safe_end}&summarize=true"
            resp = await client.get(url_spend, headers=self._headers())

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("logs", data.get("data", []))
            else:
                logger.warning(f"Spend logs returned status {resp.status_code}. Trying key spend fallback.")
                url_key = f"{self.base_url}/key/info?key={quote(api_key)}"
                resp_key = await client.get(url_key, headers=self._headers())
                if resp_key.status_code == 200:
                    key_data = resp_key.json()
                    logs = key_data.get("info", {}).get("spend_logs", [])
                    if logs:
                        return logs

                err_msg = f"LiteLLM Proxy spend logs endpoint returned HTTP status {resp.status_code}"
                try:
                    err_json = resp.json()
                    detail = err_json.get("detail") or err_json.get("message")
                    if detail:
                        err_msg += f": {detail}"
                except Exception:
                    pass

                if self.allow_mock:
                    logger.warning(f"{err_msg}. Generating sample metrics (mock allowed).")
                    return self._generate_mock_logs(user_id, start_date, end_date, user_models=user_models)

                raise RuntimeError(err_msg)

        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching spend logs for user '{user_id}' ({start_date} to {end_date}): {e}")
            if self.allow_mock:
                return self._generate_mock_logs(user_id, start_date, end_date, user_models=user_models)
            raise RuntimeError("Request to LiteLLM Proxy timed out while querying spend logs. Please select a smaller date range or contact administrator.")
        except httpx.ConnectError as e:
            logger.error(f"Could not connect to LiteLLM Proxy at {self.base_url}: {e}")
            if self.allow_mock:
                logger.warning("LiteLLM Proxy offline. Generating sample metrics (mock allowed).")
                return self._generate_mock_logs(user_id, start_date, end_date, user_models=user_models)
            raise RuntimeError(f"Could not connect to LiteLLM Proxy at {self.base_url}. Please ensure LiteLLM Proxy is running.")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Error fetching spend logs: {e}")
            if self.allow_mock:
                return self._generate_mock_logs(user_id, start_date, end_date, user_models=user_models)
            err_str = str(e).strip() or type(e).__name__
            raise RuntimeError(f"Error fetching spend logs from LiteLLM Proxy: {err_str}")

        if self.allow_mock:
            return self._generate_mock_logs(user_id, start_date, end_date, user_models=user_models)
        raise RuntimeError(f"Failed to retrieve spend logs from LiteLLM Proxy at {self.base_url}")

    def _generate_mock_logs(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
        user_models: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generates sample spend log entries based on LiteLLM model names when testing.
        """
        try:
            s_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            s_dt = datetime.now().date() - timedelta(days=6)
            e_dt = datetime.now().date()

        model_names = user_models if user_models else ["gpt-4o", "claude-3-5-sonnet", "llama-3.1-70b"]

        logs = []
        curr = s_dt
        import random
        rng = random.Random(hash(user_id) & 0xFFFFFFFF)

        while curr <= e_dt:
            date_str = curr.strftime("%Y-%m-%d")
            num_requests = rng.randint(3, 8)
            for _ in range(num_requests):
                m_name = rng.choice(model_names)
                p_tokens = rng.randint(400, 3500)
                c_tokens = rng.randint(150, 1200)
                spend = (p_tokens * 0.000003) + (c_tokens * 0.000012)
                logs.append({
                    "startTime": f"{date_str}T{rng.randint(8, 20):02d}:{rng.randint(0, 59):02d}:00Z",
                    "user": user_id,
                    "model": m_name,
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                    "total_tokens": p_tokens + c_tokens,
                    "spend": round(spend, 6)
                })
            curr += timedelta(days=1)
        return logs

    def _aggregate_metrics(
        self,
        raw_logs: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
        user_models: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Aggregates raw log items or daily activity items into daily trend time series and model breakdown stats.
        """
        total_spend = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_requests = len(raw_logs)

        daily_map: Dict[str, Dict[str, Any]] = {}
        model_map: Dict[str, Dict[str, Any]] = {}

        # 1. Build daily map for date range
        try:
            s_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            curr = s_dt
            while curr <= e_dt:
                d_str = curr.strftime("%Y-%m-%d")
                daily_map[d_str] = {
                    "date": d_str,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "spend": 0.0,
                    "requests": 0
                }
                curr += timedelta(days=1)
        except Exception:
            pass

        # 2. Process logs
        for entry in raw_logs:
            # Format 1: /user/daily/activity structure (contains "date" and "metrics")
            if "date" in entry and "metrics" in entry:
                date_str = str(entry.get("date") or "")[:10]
                metrics = entry.get("metrics") or {}
                p_tok = int(metrics.get("prompt_tokens") or 0)
                c_tok = int(metrics.get("completion_tokens") or 0)
                tot_tok = int(metrics.get("total_tokens") or (p_tok + c_tok))
                cost = float(metrics.get("spend") or 0.0)
                reqs = int(metrics.get("api_requests") or 1)

                total_spend += cost
                total_prompt_tokens += p_tok
                total_completion_tokens += c_tok

                if date_str not in daily_map:
                    daily_map[date_str] = {
                        "date": date_str,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "spend": 0.0,
                        "requests": 0
                    }
                daily_map[date_str]["prompt_tokens"] += p_tok
                daily_map[date_str]["completion_tokens"] += c_tok
                daily_map[date_str]["total_tokens"] += tot_tok
                daily_map[date_str]["spend"] += cost
                daily_map[date_str]["requests"] += reqs

                breakdown = entry.get("breakdown") or {}
                models_dict = breakdown.get("models") or breakdown.get("model_groups") or entry.get("models") or {}
                for raw_m, m_val in models_dict.items():
                    m_metrics = m_val.get("metrics") if isinstance(m_val, dict) else {}
                    m_p_tok = int(m_metrics.get("prompt_tokens") or 0)
                    m_c_tok = int(m_metrics.get("completion_tokens") or 0)
                    m_tot_tok = int(m_metrics.get("total_tokens") or (m_p_tok + m_c_tok))
                    m_cost = float(m_metrics.get("spend") or (m_val if isinstance(m_val, (int, float)) else 0.0))
                    m_reqs = int(m_metrics.get("api_requests") or 1)

                    clean_m = raw_m.split("/")[-1].strip() if "/" in raw_m else raw_m.strip()
                    if clean_m not in model_map:
                        model_map[clean_m] = {
                            "model": clean_m,
                            "tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "spend": 0.0,
                            "requests": 0
                        }
                    model_map[clean_m]["tokens"] += m_tot_tok
                    model_map[clean_m]["prompt_tokens"] += m_p_tok
                    model_map[clean_m]["completion_tokens"] += m_c_tok
                    model_map[clean_m]["spend"] += m_cost
                    model_map[clean_m]["requests"] += m_reqs
                continue

            # Format 2: /spend/logs?summarize=true structure (contains "models" dict and "spend")
            models_dict = entry.get("models")
            if isinstance(models_dict, dict) and models_dict:
                ts = entry.get("startTime") or entry.get("timestamp") or ""
                date_str = str(ts)[:10] if len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")
                cost = float(entry.get("spend") or 0.0)
                total_spend += cost

                if date_str not in daily_map:
                    daily_map[date_str] = {
                        "date": date_str,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "spend": 0.0,
                        "requests": 0
                    }
                daily_map[date_str]["spend"] += cost
                daily_map[date_str]["requests"] += 1

                for raw_m, m_spend in models_dict.items():
                    m_cost = float(m_spend or 0.0)
                    model = raw_m.split("/")[-1].strip() if "/" in raw_m else raw_m.strip()
                    if model not in model_map:
                        model_map[model] = {
                            "model": model,
                            "tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "spend": 0.0,
                            "requests": 0
                        }
                    model_map[model]["spend"] += m_cost
                    model_map[model]["requests"] += 1
                continue

            # Standard raw log item structure
            p_tok = int(entry.get("prompt_tokens") or entry.get("prompt_tok") or 0)
            c_tok = int(entry.get("completion_tokens") or entry.get("completion_tok") or 0)
            tot_tok = int(entry.get("total_tokens") or (p_tok + c_tok))
            cost = float(entry.get("spend") or entry.get("cost") or 0.0)
            raw_model = str(entry.get("model") or entry.get("model_name") or "unknown-model")
            model = raw_model.split("/")[-1].strip() if "/" in raw_model else raw_model.strip()

            ts = entry.get("startTime") or entry.get("timestamp") or entry.get("created_at") or ""
            date_str = ts[:10] if len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")

            total_spend += cost
            total_prompt_tokens += p_tok
            total_completion_tokens += c_tok

            if date_str not in daily_map:
                daily_map[date_str] = {
                    "date": date_str,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "spend": 0.0,
                    "requests": 0
                }
            daily_map[date_str]["prompt_tokens"] += p_tok
            daily_map[date_str]["completion_tokens"] += c_tok
            daily_map[date_str]["total_tokens"] += tot_tok
            daily_map[date_str]["spend"] += cost
            daily_map[date_str]["requests"] += 1

            if model not in model_map:
                model_map[model] = {
                    "model": model,
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "spend": 0.0,
                    "requests": 0
                }
            model_map[model]["tokens"] += tot_tok
            model_map[model]["prompt_tokens"] += p_tok
            model_map[model]["completion_tokens"] += c_tok
            model_map[model]["spend"] += cost
            model_map[model]["requests"] += 1

        daily_trend = sorted(list(daily_map.values()), key=lambda x: x["date"])
        for d in daily_trend:
            d["spend"] = round(d["spend"], 6)

        tot_tokens = total_prompt_tokens + total_completion_tokens
        model_breakdown = []
        for m_name, m_data in model_map.items():
            if m_data["tokens"] > 0 or m_data["spend"] > 0:
                pct = round((m_data["tokens"] / tot_tokens * 100), 2) if tot_tokens > 0 else 0.0
                model_breakdown.append({
                    "model": m_name,
                    "tokens": m_data["tokens"],
                    "prompt_tokens": m_data["prompt_tokens"],
                    "completion_tokens": m_data["completion_tokens"],
                    "spend": round(m_data["spend"], 6),
                    "requests": m_data["requests"],
                    "percentage": pct
                })

        # Sort active models by token volume descending
        model_breakdown.sort(key=lambda x: (x["tokens"], x["requests"], x["model"]), reverse=True)

        return {
            "summary": {
                "total_spend": round(total_spend, 2),
                "total_tokens": tot_tokens,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_requests": total_requests,
                "active_models_count": len(model_breakdown),
                "total_served_models_count": len(model_breakdown),
                "date_range": {"start": start_date, "end": end_date}
            },
            "daily_trend": daily_trend,
            "model_breakdown": model_breakdown,
            "detailed_logs": raw_logs[:100]
        }
