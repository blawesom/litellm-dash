import logging
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.auth import create_session_token, verify_session_token, get_current_user_from_request
from app.litellm_client import LiteLLMClient

# Setup logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger("litellm_dash.main")

# Initialize LiteLLM Client
litellm_client = LiteLLMClient()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await litellm_client.aclose()

app = FastAPI(
    title="LiteLLM Analytics Dashboard",
    description="Python web service hosted alongside LiteLLM Proxy for key/user verification and daily token/spend dashboard.",
    version="1.0.0",
    lifespan=lifespan
)

BASE_DIR = Path(__file__).resolve().parent

# Mount static files & templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    Root route: redirects to /dashboard if logged in, otherwise /login.
    """
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    payload = verify_session_token(cookie_token)
    if payload:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    Render login page.
    """
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if verify_session_token(cookie_token):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "username": ""})

@app.post("/login", response_class=HTMLResponse)
async def handle_login(
    request: Request,
    username: str = Form(...),
    api_key: str = Form(...)
):
    """
    Process login form submission, validate username & API key against LiteLLM Proxy.
    """
    validation_res = await litellm_client.validate_user_and_key(username, api_key)

    if not validation_res.get("valid"):
        error_msg = validation_res.get("error", "Authentication failed. Invalid username or LiteLLM key.")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": error_msg, "username": username},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Issue signed session token
    user_id = validation_res["user_id"]
    token = create_session_token(user_id=user_id, api_key=api_key)

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_MAX_AGE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=False  # Set to True if enforcing HTTPS in production via HAProxy
    )
    logger.info(f"User '{user_id}' authenticated successfully.")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """
    Render main dashboard interface if authenticated.
    """
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    payload = verify_session_token(cookie_token)
    if not payload:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "user": payload
    })

@app.get("/api/dashboard/stats")
async def get_dashboard_stats(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_payload: dict = Depends(get_current_user_from_request)
):
    """
    API endpoint returning JSON aggregated metrics for daily consumption and model breakdown.
    """
    user_id = user_payload["user_id"]
    api_key = user_payload["api_key"]

    try:
        metrics = await litellm_client.get_dashboard_metrics(
            user_id=user_id,
            api_key=api_key,
            start_date=start_date,
            end_date=end_date
        )
        return JSONResponse(content=metrics)
    except Exception as e:
        logger.error(f"Error fetching dashboard metrics: {e}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": True, "detail": str(e)}
        )

@app.post("/api/auth/logout")
@app.get("/logout")
async def logout():
    """
    Clears session cookie and redirects to login page.
    """
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME)
    return response
