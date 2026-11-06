# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

"""Sign in through the platform's realm with the authorization-code flow.

Odoo's auth_oauth knows only the implicit flow: it asks for
response_type=token, and the access token comes back in the redirect URL. The
platform's realms do not allow that flow -- it is deprecated (OAuth 2.1), and a
token in a URL ends up in browser history and logs -- so a sign-in through the
platform's client asks for a code instead, with PKCE, and the server exchanges
it for the access token with the confidential client's secret. From there
Odoo's own auth_oauth does what it always did: validates the token at userinfo
and signs the person in.

Only the platform's provider -- the one whose client is OIDC_CLIENT_ID -- is
switched. Any other provider an administrator configured keeps Odoo's own
behaviour.

Each sign-in started here gets a random key in its state, and the PKCE
verifier is kept in the session under that key. A code is exchanged only for a
state whose key the session holds, so a code cannot be replayed into another
browser's session (login CSRF), and a key is used once.
"""

import base64
import hashlib
import logging
import os
import secrets

import requests

_logger = logging.getLogger(__name__)

# The session key holding the verifiers of the sign-ins this browser started.
SESSION_KEY = "gentian_oauth_pkce"
# The key in Odoo's state JSON naming one of them.
STATE_KEY = "g"
# How many unfinished sign-ins one session keeps: a person may open the
# sign-in page in a few tabs; more than this and the oldest is dropped.
MAX_PENDING = 5
EXCHANGE_TIMEOUT = 15


def platform_client_id():
    """The platform's client, from the environment the chart sets."""
    return (os.environ.get("OIDC_CLIENT_ID") or "").strip()


def is_platform_provider(provider):
    client_id = platform_client_id()
    return bool(client_id) and provider.get("client_id") == client_id


def token_endpoint():
    """Where the code is exchanged: the in-cluster issuer when there is one,
    as for validation, since a tenant app may not leave the cluster to reach
    the public one."""
    base = (os.environ.get("OIDC_INTERNAL_ISSUER") or "").strip() or (os.environ.get("OIDC_ISSUER") or "").strip()
    if not base:
        return ""
    return base.rstrip("/") + "/protocol/openid-connect/token"


def new_verifier():
    """A PKCE verifier (RFC 7636): 43-128 characters of the unreserved set."""
    return secrets.token_urlsafe(64)[:96]


def challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def remember(session, key, verifier, redirect_uri):
    """Keep a sign-in's verifier and redirect_uri under key, dropping the
    oldest past MAX_PENDING. The redirect_uri is kept rather than worked out
    again at the exchange: the token endpoint wants exactly the one the
    authorization request named."""
    pending = dict(session.get(SESSION_KEY) or {})
    pending[key] = {"v": verifier, "r": redirect_uri}
    while len(pending) > MAX_PENDING:
        pending.pop(next(iter(pending)))
    session[SESSION_KEY] = pending


def take(session, key):
    """The (verifier, redirect_uri) kept under key, removed: each is used
    once. (None, None) when the session holds none under it."""
    pending = dict(session.get(SESSION_KEY) or {})
    kept = pending.pop(key, None) if key else None
    session[SESSION_KEY] = pending
    if not isinstance(kept, dict) or not kept.get("v") or not kept.get("r"):
        return None, None
    return kept["v"], kept["r"]


class ExchangeError(Exception):
    """The code could not be exchanged; the message carries no credential."""


def exchange(code, redirect_uri, verifier):
    """Exchange a code for an access token at the realm's token endpoint."""
    endpoint = token_endpoint()
    client_id = platform_client_id()
    secret = (os.environ.get("OIDC_CLIENT_SECRET") or "").strip()
    if not (endpoint and client_id and secret):
        raise ExchangeError("the platform's client is not configured (OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET)")
    try:
        response = requests.post(
            endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": secret,
                "code_verifier": verifier,
            },
            timeout=EXCHANGE_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ExchangeError("the token endpoint did not answer: %s" % type(exc).__name__) from None
    if response.status_code != 200:
        # Keycloak's error body names the error, never the code or a token.
        try:
            body = response.json()
            detail = "%s: %s" % (body.get("error"), body.get("error_description"))
        except ValueError:
            detail = "no JSON body"
        raise ExchangeError("the token endpoint refused the code (%s, %s)" % (response.status_code, detail))
    try:
        token = response.json().get("access_token")
    except ValueError:
        token = None
    if not token:
        raise ExchangeError("the token endpoint answered without an access token")
    return token
