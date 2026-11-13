# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

"""A person's access token from the platform's realm, on Odoo's API.

Odoo's JSON-2 API knows a caller by an API key. A program that acts for a
person on the platform holds no key of Odoo's: it is handed that person's
token, issued by the tenant's realm for Odoo and nothing else (a token
exchange, RFC 8693). This module says whether such a token is good here.

Good means: signed by a key the realm publishes, issued by this tenant's
realm, made out to this Odoo, an access token, and not expired. What the
token is for is the realm's word; nothing here asks anybody else.

The realm is the one the sign-in uses (OIDC_ISSUER, and OIDC_INTERNAL_ISSUER
for the leg from inside the cluster). The audience is GENTIAN_TOKEN_AUDIENCE,
which the chart sets to the name the realm puts into tokens for this Odoo.
While either is unset no token is accepted.
"""

import base64
import binascii
import json
import logging
import os
import threading
import time

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_logger = logging.getLogger(__name__)

# How long the realm's keys are kept, and how soon they may be asked for
# again: a token naming a key that is not known costs one fetch, so that a
# rotated key is not an outage, but a stream of such tokens is not a stream
# of fetches.
KEYS_TTL = 600
KEYS_MIN_INTERVAL = 10
FETCH_TIMEOUT = 5

_lock = threading.Lock()
_keys = {}
_fetched = 0.0
_source = ""


class Refused(Exception):
    """The token is not good here. The message names no part of the token."""


def audience():
    return (os.environ.get("GENTIAN_TOKEN_AUDIENCE") or "").strip()


def issuer():
    return (os.environ.get("OIDC_ISSUER") or "").strip().rstrip("/")


def certs_endpoint():
    """Where the realm publishes its keys: in the cluster when there is an
    address for that, since a tenant app may not leave it to reach the public
    one."""
    base = (os.environ.get("OIDC_INTERNAL_ISSUER") or "").strip().rstrip("/") or issuer()
    return base + "/protocol/openid-connect/certs" if base else ""


def configured():
    return bool(audience() and issuer())


def looks_like_one(token):
    """A JWT has three parts; an API key of Odoo's has no dot in it."""
    return isinstance(token, str) and token.count(".") == 2


def _decode(part):
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError):
        raise Refused("the token is not readable") from None


def _number(value):
    return int.from_bytes(_decode(value), "big")


def _fetch_keys(endpoint):
    response = requests.get(endpoint, timeout=FETCH_TIMEOUT)
    response.raise_for_status()
    found = {}
    for key in response.json().get("keys", []):
        if key.get("kty") != "RSA" or key.get("use", "sig") != "sig" or not key.get("kid"):
            continue
        try:
            found[key["kid"]] = rsa.RSAPublicNumbers(_number(key["e"]), _number(key["n"])).public_key()
        except (KeyError, ValueError, Refused):
            continue
    return found


def _key(kid):
    global _keys, _fetched, _source
    endpoint = certs_endpoint()
    with _lock:
        now = time.monotonic()
        if _source != endpoint:
            _keys, _fetched, _source = {}, 0.0, endpoint
        stale = not _fetched or now - _fetched > KEYS_TTL
        unknown = kid not in _keys and now - _fetched > KEYS_MIN_INTERVAL
        if stale or unknown:
            try:
                _keys = _fetch_keys(endpoint)
            except (requests.RequestException, ValueError) as exc:
                _logger.warning("The realm's keys could not be read: %s", type(exc).__name__)
                raise Refused("the realm's keys could not be read") from None
            _fetched = time.monotonic()
        key = _keys.get(kid)
    if key is None:
        raise Refused("the token is signed with an unknown key")
    return key


def verify(token, now=None):
    """The claims of a token that is good here, or Refused."""
    if not configured():
        raise Refused("this Odoo accepts no token of the realm")
    parts = token.split(".")
    if len(parts) != 3:
        raise Refused("the token is not readable")
    try:
        header = json.loads(_decode(parts[0]))
        claims = json.loads(_decode(parts[1]))
    except ValueError:
        raise Refused("the token is not readable") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise Refused("the token is not readable")
    # One algorithm, named here and not taken from the token: the realm
    # signs access tokens with RS256.
    if header.get("alg") != "RS256":
        raise Refused("the token is signed in a way the realm does not sign")
    try:
        _key(header.get("kid")).verify(
            _decode(parts[2]),
            (parts[0] + "." + parts[1]).encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, UnicodeEncodeError):
        raise Refused("the token's signature is not the realm's") from None

    if claims.get("iss") != issuer():
        raise Refused("the token is of another realm")
    made_out_to = claims.get("aud")
    if isinstance(made_out_to, str):
        made_out_to = [made_out_to]
    if not isinstance(made_out_to, list) or audience() not in made_out_to:
        raise Refused("the token is not made out to this Odoo")
    if claims.get("typ") != "Bearer":
        raise Refused("this is not an access token")
    expires = claims.get("exp")
    if not isinstance(expires, (int, float)) or isinstance(expires, bool) or expires <= (time.time() if now is None else now):
        raise Refused("the token has expired")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise Refused("the token names no person")
    return claims


def reset_for_tests():
    global _keys, _fetched, _source
    with _lock:
        _keys, _fetched, _source = {}, 0.0, ""
