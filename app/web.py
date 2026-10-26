"""Public authentication pages and authenticated monitoring pages."""

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

auth_router = APIRouter(tags=["authentication"])
web_router = APIRouter(tags=["web pages"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 64


def hash_password(password: str) -> str:
    """Store a salted scrypt hash, never the original password."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LENGTH,
    )
    return "$".join([
        "scrypt",
        str(SCRYPT_N),
        str(SCRYPT_R),
        str(SCRYPT_P),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    ])


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, n, r, p, salt_text, digest_text = stored_hash.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, MemoryError):
        return False


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _csrf_ok(request: Request, supplied: str) -> bool:
    expected = request.session.get("csrf_token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


async def _form(request: Request) -> dict[str, str]:
    """Read ordinary browser URL-encoded forms without requiring multipart."""
    body = await request.body()
    if len(body) > 64 * 1024:
        return {}
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


async def _user_for_request(
    request: Request, db: AsyncSession
) -> User | None:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return None
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        request.session.clear()
    return user


async def require_authenticated_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _user_for_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return user


def _auth_context(request: Request, message: str | None = None) -> dict:
    return {
        "request": request,
        "app_name": settings.APP_NAME,
        "csrf_token": _csrf_token(request),
        "message": message or request.session.pop("flash_message", None),
        "contact_email": settings.CONTACT_EMAIL.strip(),
    }


def _flash_redirect(request: Request, message: str, location: str = "/login"):
    request.session["flash_message"] = message
    return RedirectResponse(location, status_code=303)


async def _login_template(
    request: Request,
    db: AsyncSession,
    message: str | None = None,
):
    user = await _user_for_request(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=_auth_context(request, message),
    )


@auth_router.get("/", include_in_schema=False)
async def landing_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _login_template(request, db)


@auth_router.get("/login", include_in_schema=False)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _login_template(request, db)


@auth_router.post("/auth/login", include_in_schema=False)
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await _form(request)
    if not _csrf_ok(request, form.get("csrf_token", "")):
        return _flash_redirect(request, "Your form expired. Please try again.")

    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    user = await db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(password, user.password_hash):
        return _flash_redirect(request, "Email or password is incorrect.")

    request.session.clear()
    request.session["user_id"] = user.id
    _csrf_token(request)
    return RedirectResponse("/dashboard", status_code=303)


@auth_router.get("/register", include_in_schema=False)
async def register_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _user_for_request(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=_auth_context(request),
    )


@auth_router.post("/auth/register", include_in_schema=False)
async def register_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await _form(request)
    if not _csrf_ok(request, form.get("csrf_token", "")):
        return _flash_redirect(request, "Your form expired. Please try again.", "/register")

    name = " ".join(form.get("name", "").strip().split())
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    if not name or len(name) > 120:
        return _flash_redirect(request, "Enter your name (up to 120 characters).", "/register")
    if len(email) > 255 or not EMAIL_PATTERN.fullmatch(email):
        return _flash_redirect(request, "Enter a valid email address.", "/register")
    if len(password) < 10:
        return _flash_redirect(request, "Use a password with at least 10 characters.", "/register")
    if len(password) > 1024:
        return _flash_redirect(request, "That password is too long.", "/register")
    if password != confirm:
        return _flash_redirect(request, "The passwords do not match.", "/register")

    user = User(
        email=email,
        display_name=name,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        return _flash_redirect(
            request,
            "An account with this email already exists. Try signing in instead.",
            "/register",
        )

    request.session.clear()
    request.session["user_id"] = user.id
    _csrf_token(request)
    return RedirectResponse("/dashboard", status_code=303)


@auth_router.get("/auth/google", include_in_schema=False)
async def google_login(request: Request):
    client_id = settings.GOOGLE_CLIENT_ID.strip()
    if not client_id or not settings.GOOGLE_CLIENT_SECRET.strip():
        return _flash_redirect(
            request,
            "Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
            "/register" if request.query_params.get("from") == "register" else "/login",
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_nonce"] = nonce
    redirect_uri = str(request.url_for("google_callback"))
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(authorize_url, status_code=302)


@auth_router.get("/auth/google/callback", name="google_callback", include_in_schema=False)
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if request.query_params.get("error"):
        return _flash_redirect(request, "Google sign-in was cancelled or denied.")

    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    expected_state = request.session.pop("google_oauth_state", "")
    expected_nonce = request.session.pop("google_oauth_nonce", "")
    if (
        not code
        or not state
        or not expected_state
        or not hmac.compare_digest(state, expected_state)
        or not expected_nonce
    ):
        return _flash_redirect(request, "Google sign-in could not be verified. Please try again.")

    redirect_uri = str(request.url_for("google_callback"))
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID.strip(),
                    "client_secret": settings.GOOGLE_CLIENT_SECRET.strip(),
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            id_token_value = token_payload.get("id_token")
            if not id_token_value:
                raise ValueError("Google did not return an ID token.")

        # Verify the token signature and standard claims against Google's public
        # certificates instead of relying on the debugging-only tokeninfo endpoint.
        claims = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            id_token_value,
            GoogleAuthRequest(),
            settings.GOOGLE_CLIENT_ID.strip(),
        )

        if claims.get("aud") != settings.GOOGLE_CLIENT_ID.strip():
            raise ValueError("Unexpected Google token audience.")
        if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Unexpected Google token issuer.")
        if claims.get("nonce") != expected_nonce:
            raise ValueError("Google token nonce did not match.")
        if int(claims.get("exp", "0")) <= int(time.time()):
            raise ValueError("Google ID token expired.")
        if str(claims.get("email_verified", "")).lower() != "true":
            raise ValueError("Google email is not verified.")

        subject = claims.get("sub", "")
        email = claims.get("email", "").strip().lower()
        display_name = (claims.get("name") or email.split("@")[0]).strip()[:120]
        if not subject or not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("Google did not return a valid account identity.")

        user = await db.scalar(select(User).where(User.google_sub == subject))
        if user is None:
            user = await db.scalar(select(User).where(User.email == email))
            if user is not None:
                user.google_sub = subject
                if not user.display_name:
                    user.display_name = display_name
            else:
                user = User(
                    email=email,
                    display_name=display_name or email.split("@")[0],
                    google_sub=subject,
                    password_hash=None,
                )
                db.add(user)
            try:
                await db.commit()
                await db.refresh(user)
            except IntegrityError:
                await db.rollback()
                return _flash_redirect(
                    request,
                    "This Google account could not be linked. Try signing in with your email.",
                )

        request.session.clear()
        request.session["user_id"] = user.id
        _csrf_token(request)
        return RedirectResponse("/dashboard", status_code=303)

    except (httpx.HTTPError, GoogleAuthError, ValueError, TypeError, KeyError, OSError):
        return _flash_redirect(
            request,
            "Google sign-in could not be verified. Check the OAuth configuration and try again.",
        )


@auth_router.post("/auth/logout", include_in_schema=False)
async def logout(request: Request):
    form = await _form(request)
    if not _csrf_ok(request, form.get("csrf_token", "")):
        return _flash_redirect(request, "Your form expired. Please sign in again.")
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


async def _render_private_page(
    request: Request,
    db: AsyncSession,
    *,
    page_key: str,
    page_title: str,
    page_description: str,
    template_name: str,
):
    user = await _user_for_request(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "current_user": user,
            "csrf_token": _csrf_token(request),
            "page_key": page_key,
            "page_title": page_title,
            "page_description": page_description,
            "contact_email": settings.CONTACT_EMAIL.strip(),
        },
    )


@web_router.get("/dashboard", include_in_schema=False)
async def overview_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="overview", page_title="Overview",
        page_description="A clear summary of your monitored network.",
        template_name="dashboard_overview.html",
    )


@web_router.get("/dashboard/connectivity", include_in_schema=False)
async def connectivity_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="connectivity", page_title="Connectivity",
        page_description="Reachability, recent checks, and latency over time.",
        template_name="dashboard_connectivity.html",
    )


@web_router.get("/dashboard/services", include_in_schema=False)
async def services_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="services", page_title="Service monitoring",
        page_description="Track configured HTTP endpoints and their incident history.",
        template_name="dashboard_services.html",
    )


@web_router.get("/dashboard/quality", include_in_schema=False)
async def quality_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="quality", page_title="Network quality",
        page_description="Measure packet loss, latency, jitter, and sustained degradation.",
        template_name="dashboard_quality.html",
    )


@web_router.get("/dashboard/diagnosis", include_in_schema=False)
async def diagnosis_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="diagnosis", page_title="Connectivity diagnosis",
        page_description="Compare gateway, external targets, DNS, and HTTP checks.",
        template_name="dashboard_diagnosis.html",
    )


@web_router.get("/dashboard/incidents", include_in_schema=False)
async def incidents_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="incidents", page_title="Incident history",
        page_description="Review connectivity outages, service incidents, and quality degradation.",
        template_name="dashboard_incidents.html",
    )


@web_router.get("/dashboard/reports", include_in_schema=False)
async def reports_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="reports", page_title="Reliability reports",
        page_description="Review measurement coverage and export the recorded evidence.",
        template_name="dashboard_reports.html",
    )


@web_router.get("/dashboard/settings", include_in_schema=False)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    return await _render_private_page(
        request, db, page_key="settings", page_title="Settings",
        page_description="Theme, notifications, and local monitor configuration.",
        template_name="dashboard_settings.html",
    )
