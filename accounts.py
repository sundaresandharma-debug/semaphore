"""
User accounts, backed by Supabase (Auth + Postgres), called only from the server.

The browser never sees a Supabase key.  It talks to /api/auth and /api/account;
this module talks to Supabase's REST endpoints with the keys from environment
variables, and keeps the user's session in two HttpOnly cookies.

Environment variables (set them in Vercel -> Project -> Settings -> Environment Variables):

    SUPABASE_URL               https://<project>.supabase.co
    SUPABASE_ANON_KEY          the project's publishable (or legacy anon) key, used server side only
    SUPABASE_SERVICE_ROLE_KEY  the secret (or legacy service_role) key, used ONLY to delete an account
    SITE_URL                   https://your-site.vercel.app  (where email links send people)

Data stored per account: the email address and password hash (inside Supabase
Auth), the date the terms were accepted, and the demonstration results the user
chooses to save.  Nothing else.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

ACCESS_COOKIE = "sl_at"
REFRESH_COOKIE = "sl_rt"
REFRESH_MAX_AGE = 30 * 24 * 3600
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
MIN_PASSWORD = 8
DEMO_IDS = {"race", "producer_consumer", "readers_writers", "dining_philosophers"}
STATUSES = {"PASS", "FAIL", "DEADLOCK", "CANCELLED"}


class AccountError(Exception):
    """An error with a status code and a message that is safe to show the user."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _cfg(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_cfg("SUPABASE_URL") and _cfg("SUPABASE_ANON_KEY"))


def _require_configured() -> None:
    if not configured():
        raise AccountError(503, "Accounts are not switched on for this website yet. "
                                "Everything else works without an account.")


# ----------------------------------------------------------------------
# Talking to Supabase
# ----------------------------------------------------------------------
def _call(method: str, path: str, body: Any = None, token: Optional[str] = None,
          service: bool = False, query: Optional[Dict[str, str]] = None,
          prefer: Optional[str] = None) -> Tuple[int, Any]:
    key = _cfg("SUPABASE_SERVICE_ROLE_KEY") if service else _cfg("SUPABASE_ANON_KEY")
    url = _cfg("SUPABASE_URL").rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"apikey": key, "Accept": "application/json"}
    bearer = token or (key if key.startswith("eyJ") else "")   # new sb_... keys are not JWTs: apikey header only
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"message": raw[:200].decode("utf-8", "replace")}
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AccountError(502, "The account service did not respond. Please try again in a minute.")


def _msg(payload: Any) -> str:
    if isinstance(payload, dict):
        for k in ("msg", "message", "error_description", "error"):
            if payload.get(k):
                return str(payload[k])
    return ""


# ----------------------------------------------------------------------
# Session cookies
# ----------------------------------------------------------------------
def _cookie(name: str, value: str, max_age: int) -> str:
    return (f"{name}={value}; Path=/api; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax")


def session_cookies(session: dict) -> List[str]:
    return [_cookie(ACCESS_COOKIE, session["access_token"], int(session.get("expires_in") or 3600)),
            _cookie(REFRESH_COOKIE, session["refresh_token"], REFRESH_MAX_AGE)]


def clear_cookies() -> List[str]:
    return [_cookie(ACCESS_COOKIE, "", 0), _cookie(REFRESH_COOKIE, "", 0)]


def current_user(cookies: Dict[str, str], out: List[str]) -> Optional[Tuple[dict, str]]:
    """Return (user, access_token) for the signed-in visitor, refreshing if needed."""
    if not configured():
        return None
    at, rt = cookies.get(ACCESS_COOKIE), cookies.get(REFRESH_COOKIE)
    if at:
        code, user = _call("GET", "/auth/v1/user", token=at)
        if code == 200 and isinstance(user, dict) and user.get("id"):
            return user, at
    if rt:
        code, session = _call("POST", "/auth/v1/token", {"refresh_token": rt},
                              query={"grant_type": "refresh_token"})
        if code == 200 and isinstance(session, dict) and session.get("access_token"):
            out += session_cookies(session)
            return session["user"], session["access_token"]
    if at or rt:
        out += clear_cookies()              # stale cookies: remove them
    return None


def public_user(user: dict) -> dict:
    return {"email": user.get("email", "")}


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def _email(body: dict) -> str:
    email = str(body.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AccountError(400, "Enter a valid email address, like name@example.com.")
    return email


def _password(body: dict, field: str = "password") -> str:
    pw = body.get(field)
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        raise AccountError(400, f"Use a password with at least {MIN_PASSWORD} characters.")
    if len(pw) > 72:
        raise AccountError(400, "Use a password with at most 72 characters.")
    return pw


def _redirect() -> Dict[str, str]:
    site = _cfg("SITE_URL")
    return {"redirect_to": site.rstrip("/") + "/"} if site else {}


# ----------------------------------------------------------------------
# /api/auth
# ----------------------------------------------------------------------
def auth_status(cookies: Dict[str, str], out: List[str]) -> dict:
    if not configured():
        return {"configured": False, "user": None}
    found = current_user(cookies, out)
    return {"configured": True, "user": public_user(found[0]) if found else None}


def auth_action(body: dict, cookies: Dict[str, str], out: List[str]) -> dict:
    _require_configured()
    action = body.get("action")

    if action == "signup":
        email, pw = _email(body), _password(body)
        if body.get("agree_terms") is not True:
            raise AccountError(400, "Please accept the Terms of service and Privacy policy to create an account.")
        if body.get("age_ok") is not True:
            raise AccountError(400, "You must be 18 or older to create an account. "
                                    "You can still use every demonstration without one.")
        code, res = _call("POST", "/auth/v1/signup",
                          {"email": email, "password": pw,
                           "data": {"terms_accepted": True, "age_confirmed_18_plus": True}},
                          query=_redirect())
        if code >= 400:
            text = _msg(res).lower()
            if "password" in text:
                raise AccountError(400, "That password is too weak. Use at least 8 characters, mixing words and numbers.")
            if code == 429 or "rate" in text:
                raise AccountError(429, "Too many sign-up attempts. Please wait a few minutes and try again.")
            raise AccountError(400, "We could not create the account. Check the email address and try again.")
        if isinstance(res, dict) and res.get("access_token"):
            out += session_cookies(res)
            return {"user": public_user(res["user"]), "needs_confirmation": False}
        return {"user": None, "needs_confirmation": True}

    if action == "login":
        email = _email(body)
        pw = body.get("password")
        if not isinstance(pw, str) or not pw:
            raise AccountError(400, "Enter your password.")
        code, res = _call("POST", "/auth/v1/token", {"email": email, "password": pw},
                          query={"grant_type": "password"})
        if code == 200 and isinstance(res, dict) and res.get("access_token"):
            out += session_cookies(res)
            return {"user": public_user(res["user"])}
        text = _msg(res).lower()
        if "confirm" in text:
            raise AccountError(403, "Please confirm your email address first. The link is in the email we sent you.")
        if code == 429:
            raise AccountError(429, "Too many sign-in attempts. Please wait a few minutes and try again.")
        raise AccountError(401, "The email or password is incorrect.")

    if action == "logout":
        at = cookies.get(ACCESS_COOKIE)
        if at:
            _call("POST", "/auth/v1/logout", token=at)
        out += clear_cookies()
        return {"user": None}

    if action == "recover":
        email = _email(body)
        code, _ = _call("POST", "/auth/v1/recover", {"email": email}, query=_redirect())
        if code == 429:
            raise AccountError(429, "Too many reset emails were requested. Please wait a few minutes and try again.")
        # Same answer whether or not the address has an account, so nobody can probe for accounts.
        return {"sent": True}

    if action in ("session", "reset"):
        at, rt = body.get("access_token"), body.get("refresh_token")
        if not isinstance(at, str) or not isinstance(rt, str) or not at or not rt:
            raise AccountError(400, "This link is incomplete. Please request a new email.")
        if action == "reset":
            pw = _password(body)
            code, res = _call("PUT", "/auth/v1/user", {"password": pw}, token=at)
            if code >= 400:
                if "different" in _msg(res).lower():
                    raise AccountError(400, "Choose a password that is different from your old one.")
                raise AccountError(400, "This reset link has expired or was already used. Please request a new one.")
        code, user = _call("GET", "/auth/v1/user", token=at)
        if code != 200 or not isinstance(user, dict):
            raise AccountError(400, "This link has expired. Please request a new email.")
        out += session_cookies({"access_token": at, "refresh_token": rt, "expires_in": body.get("expires_in") or 3600})
        return {"user": public_user(user)}

    raise AccountError(400, "Unknown action.")


# ----------------------------------------------------------------------
# /api/account : saved results and deletion
# ----------------------------------------------------------------------
def _signed_in(cookies: Dict[str, str], out: List[str]) -> Tuple[dict, str]:
    _require_configured()
    found = current_user(cookies, out)
    if not found:
        raise AccountError(401, "Your session has ended. Please sign in again.")
    return found


def account_get(cookies: Dict[str, str], out: List[str]) -> dict:
    user, at = _signed_in(cookies, out)
    code, rows = _call("GET", "/rest/v1/saved_runs", token=at,
                       query={"select": "id,demo,status,duration,params,summary,created_at",
                              "order": "created_at.desc", "limit": "200"})
    if code != 200:
        raise AccountError(502, "Your saved results could not be loaded. Please try again.")
    return {"user": public_user(user), "runs": rows or []}


def account_action(body: dict, cookies: Dict[str, str], out: List[str]) -> dict:
    user, at = _signed_in(cookies, out)
    action = body.get("action")

    if action == "save_run":
        demo, status = body.get("demo"), body.get("status")
        if demo not in DEMO_IDS or status not in STATUSES:
            raise AccountError(400, "This result cannot be saved.")
        try:
            duration = max(0.0, min(3600.0, float(body.get("duration") or 0)))
        except (TypeError, ValueError):
            duration = 0.0
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        params = {str(k)[:40]: v for k, v in list(params.items())[:12]
                  if isinstance(v, (int, float, bool))}
        summary = str(body.get("summary") or "")[:500]
        code, res = _call("POST", "/rest/v1/saved_runs",
                          {"demo": demo, "status": status, "duration": round(duration, 3),
                           "params": params, "summary": summary},
                          token=at, prefer="return=representation")
        if code >= 400:
            text = _msg(res)
            if "rate_limited" in text:
                raise AccountError(429, "You can save up to 30 results per hour. Please try again later.")
            if "quota" in text:
                raise AccountError(409, "You have 200 saved results, the maximum. Delete some to save new ones.")
            raise AccountError(502, "The result could not be saved. Please try again.")
        return {"run": res[0] if isinstance(res, list) and res else None}

    if action == "delete_run":
        try:
            run_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise AccountError(400, "Unknown result.")
        code, res = _call("DELETE", "/rest/v1/saved_runs", token=at,
                          query={"id": f"eq.{run_id}"}, prefer="return=representation")
        if code >= 400:
            raise AccountError(502, "The result could not be deleted. Please try again.")
        if not res:
            raise AccountError(404, "That result was already deleted.")
        return {"deleted": 1}

    if action == "delete_runs":
        code, res = _call("DELETE", "/rest/v1/saved_runs", token=at,
                          query={"user_id": f"eq.{user['id']}"}, prefer="return=representation")
        if code >= 400:
            raise AccountError(502, "Your results could not be deleted. Please try again.")
        return {"deleted": len(res or [])}

    if action == "delete_account":
        pw = body.get("password")
        if not isinstance(pw, str) or not pw:
            raise AccountError(400, "Enter your password to confirm.")
        code, _ = _call("POST", "/auth/v1/token", {"email": user.get("email"), "password": pw},
                        query={"grant_type": "password"})
        if code != 200:
            raise AccountError(401, "The password is incorrect, so the account was not deleted.")
        if not _cfg("SUPABASE_SERVICE_ROLE_KEY"):
            raise AccountError(503, "Account deletion is not switched on yet. Email us and we will delete it within 30 days.")
        code, res = _call("DELETE", f"/auth/v1/admin/users/{urllib.parse.quote(user['id'])}", service=True)
        if code >= 400:
            raise AccountError(502, "The account could not be deleted. Please try again or email us.")
        out += clear_cookies()             # saved_runs rows go with it (ON DELETE CASCADE)
        return {"deleted": True}

    raise AccountError(400, "Unknown action.")
