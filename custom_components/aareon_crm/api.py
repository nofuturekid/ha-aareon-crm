"""Minimal async client for the Aareon CRM tenant portal (independent of Home Assistant).

The portal authenticates through Keycloak (authorization code flow with PKCE, no
second factor). Tokens are short lived, so callers log in, fetch, and log out.
"""

from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
import uuid
from datetime import date
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import aiohttp
from yarl import URL

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_LOGIN_HOPS = 8

_LOGIN_FORM_RE = re.compile(
    r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"'
    r'|<form[^>]*action="([^"]+login-actions/authenticate[^"]*)"'
)


class AareonError(Exception):
    """Base error of the client."""


class AareonConnectionError(AareonError):
    """The portal could not be reached."""


class AareonApiError(AareonError):
    """The portal answered in an unexpected way."""


class AareonAuthError(AareonError):
    """Login failed (wrong credentials or the portal wants an extra step)."""


def normalize_base_url(url: str) -> str:
    """Return scheme://host[:port] of a user-supplied portal URL."""
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("invalid portal URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


class AareonClient:
    """Client for one portal. Use a session with its own cookie jar."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client; nothing is sent until `async_login`."""
        self._session = session
        self.base_url = normalize_base_url(base_url)
        self._username = username
        self._password = password
        self._client_id: str | None = None
        self._oidc: str | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        try:
            return await self._session.request(method, url, **kwargs)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AareonConnectionError(f"{method} {URL(url).path}: {err}") from err

    async def async_get_auth_info(self) -> dict[str, Any]:
        """Fetch the public Keycloak realm/client description."""
        resp = await self._request("GET", f"{self.base_url}/api/auth-info")
        async with resp:
            if resp.status != 200:
                raise AareonApiError(f"auth-info returned HTTP {resp.status}")
            try:
                info = await resp.json(content_type=None)
                realm, client_id = info["realm"], info["client-id"]
            except (aiohttp.ContentTypeError, ValueError, KeyError, TypeError) as err:
                raise AareonApiError("auth-info has an unexpected format") from err
        self._client_id = client_id
        self._oidc = f"{self.base_url}/realms/{realm}/protocol/openid-connect"
        return info

    async def async_login(self) -> None:
        """Run the authorization code + PKCE flow and keep the tokens."""
        self._session.cookie_jar.clear()
        if self._oidc is None:
            await self.async_get_auth_info()
        assert self._oidc and self._client_id
        redirect_uri = f"{self.base_url}/app/de/"
        verifier, challenge = _pkce_pair()
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "scope": "openid",
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": secrets.token_urlsafe(16),
                "nonce": secrets.token_urlsafe(16),
            }
        )
        resp = await self._request("GET", f"{self._oidc}/auth?{query}")
        async with resp:
            page = await resp.text()
            if resp.status != 200:
                raise AareonApiError(f"login page returned HTTP {resp.status}")
        match = _LOGIN_FORM_RE.search(page)
        if not match:
            raise AareonApiError("login form not found")
        action = html.unescape(match.group(1) or match.group(2))

        resp = await self._request(
            "POST",
            action,
            data={
                "username": self._username,
                "password": self._password,
                "credentialId": "",
            },
            allow_redirects=False,
        )
        async with resp:
            if resp.status not in (302, 303):
                # Keycloak re-renders the form (HTTP 200) on wrong credentials.
                raise AareonAuthError("invalid credentials")
            location = resp.headers.get("Location", "")

        code = await self._follow_to_code(location)
        await self._exchange_code(code, verifier, redirect_uri)

    async def _follow_to_code(self, location: str) -> str:
        for _ in range(MAX_LOGIN_HOPS):
            if not location:
                break
            target = str(URL(self.base_url).join(URL(location)))
            parsed = urlparse(target)
            code = (parse_qs(parsed.query) or parse_qs(parsed.fragment)).get("code")
            if code:
                return code[0]
            resp = await self._request("GET", target, allow_redirects=False)
            async with resp:
                if resp.status not in (301, 302, 303):
                    break
                location = resp.headers.get("Location", "")
        raise AareonAuthError("portal requires an additional login step")

    async def _exchange_code(self, code: str, verifier: str, redirect_uri: str) -> None:
        resp = await self._request(
            "POST",
            f"{self._oidc}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )
        async with resp:
            if resp.status in (400, 401):
                raise AareonAuthError("token request rejected")
            if resp.status != 200:
                raise AareonApiError(f"token endpoint returned HTTP {resp.status}")
            try:
                tokens = await resp.json(content_type=None)
                self._access_token = tokens["access_token"]
            except (ValueError, KeyError, TypeError) as err:
                raise AareonApiError("token response has an unexpected format") from err
            self._refresh_token = tokens.get("refresh_token")

    async def async_logout(self) -> None:
        """End the Keycloak session. Failures are ignored (tokens expire anyway)."""
        if not (self._refresh_token and self._oidc):
            return
        try:
            resp = await self._request(
                "POST",
                f"{self._oidc}/logout",
                data={"client_id": self._client_id, "refresh_token": self._refresh_token},
            )
            async with resp:
                pass
        except AareonError:
            pass
        finally:
            self._access_token = self._refresh_token = None

    async def _get_json(self, path: str) -> Any:
        if not self._access_token:
            raise AareonAuthError("not logged in")
        resp = await self._request(
            "GET",
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
                "x-crm-correlation-id": str(uuid.uuid4()),
            },
        )
        async with resp:
            if resp.status in (401, 403):
                raise AareonAuthError(f"HTTP {resp.status}")
            if resp.status != 200:
                raise AareonApiError(f"{path.split('?')[0]} returned HTTP {resp.status}")
            try:
                return await resp.json(content_type=None)
            except ValueError as err:
                raise AareonApiError("response is not JSON") from err

    async def async_get_contracts(self) -> list[dict[str, Any]]:
        """Return the tenant's contracts."""
        data = await self._get_json(
            "/api/tenant/erp-data-provider/contracts?apply-crm-config-filter=1"
        )
        if not isinstance(data, list):
            raise AareonApiError("contracts response has an unexpected format")
        return data

    async def async_get_consumption(self, reference: str, start: date, end: date) -> dict[str, Any]:
        """Return the raw consumption payload (`results`) of a contract reference."""
        path = (
            f"/api/tenant/eed/users/consumption/from/{start.isoformat()}"
            f"/to/{end.isoformat()}/contract/{quote(reference, safe='')}"
        )
        data = await self._get_json(path)
        if not isinstance(data, dict) or "results" not in data:
            raise AareonApiError("consumption response has an unexpected format")
        return data["results"]
