# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import base64
import json
import os
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from odoo.tests import BaseCase, HttpCase, tagged

from odoo.addons.gentian_os import realm_token

ISSUER = "https://id.example.test/auth/realms/team"
ENV = {
    "OIDC_CLIENT_ID": "odoo-cb",
    "OIDC_ISSUER": ISSUER,
    "OIDC_INTERNAL_ISSUER": "http://keycloak.internal:8080/auth/realms/team",
    "GENTIAN_TOKEN_AUDIENCE": "odoo-base-ce",
}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwk(key, kid):
    numbers = key.public_key().public_numbers()

    def number(value):
        return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))

    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": number(numbers.n), "e": number(numbers.e)}


def token(key=KEY, kid="k1", alg="RS256", **over):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "sub-1",
        "aud": ["odoo-base-ce"],
        "azp": "vouch-chaperone",
        "typ": "Bearer",
        "iat": now,
        "exp": now + 300,
        **over,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    signed = b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode()) + "." + b64(json.dumps(claims).encode())
    signature = key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256()) if key else b""
    return signed + "." + b64(signature)


class Realm:
    """Stands in for the realm's key endpoint and counts the fetches."""

    def __init__(self):
        self.fetches = []

    def get(self, endpoint, timeout=None):
        self.fetches.append(endpoint)
        response = MagicMock(status_code=200)
        response.json.return_value = {"keys": [jwk(KEY, "k1"), {"kty": "EC", "kid": "k9"}]}
        return response


class RealmCase:
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        self.realm = Realm()
        fetch = patch.object(realm_token.requests, "get", self.realm.get)
        fetch.start()
        self.addCleanup(fetch.stop)
        realm_token.reset_for_tests()
        self.addCleanup(realm_token.reset_for_tests)


@tagged("post_install", "-at_install")
class TestRealmToken(RealmCase, BaseCase):
    """What a token must say to be good at this Odoo."""

    def refused(self, value, **env):
        with patch.dict(os.environ, env), self.assertRaises(realm_token.Refused):
            realm_token.verify(value)

    def test_a_token_of_the_realm_made_out_to_this_odoo_is_good(self):
        claims = realm_token.verify(token())
        self.assertEqual(claims["sub"], "sub-1")
        # The keys are read inside the cluster.
        self.assertEqual(self.realm.fetches, ["http://keycloak.internal:8080/auth/realms/team/protocol/openid-connect/certs"])
        self.assertEqual(realm_token.verify(token(aud="odoo-base-ce"))["sub"], "sub-1")

    def test_a_token_that_says_anything_else_is_refused(self):
        self.refused(token(aud=["odoo-crm-ce", "https://mcp.team.example.test"]))
        self.refused(token(aud=None))
        self.refused(token(iss="https://id.example.test/auth/realms/other"))
        self.refused(token(typ="ID"))
        self.refused(token(typ=None))
        self.refused(token(sub=None))
        self.refused(token(sub=7))
        self.refused(token(exp=int(time.time()) - 1))
        self.refused(token(exp=None))
        self.refused(token(exp="tomorrow"))

    def test_a_token_not_signed_by_the_realm_is_refused(self):
        self.refused(token(key=OTHER))
        self.refused(token(kid="k2"))
        self.refused(token(kid="k9"))
        self.refused(token(key=None, alg="none"))
        self.refused(token(alg="HS256"))
        good = token()
        head, body, signature = good.split(".")
        forged = b64(json.dumps({"iss": ISSUER, "sub": "admin", "aud": "odoo-base-ce", "typ": "Bearer", "exp": 9999999999}).encode())
        self.refused(".".join([head, forged, signature]))
        self.refused("a.b.c")
        self.refused("not-a-token")

    def test_without_the_realm_or_the_audience_nothing_is_accepted(self):
        self.refused(token(), GENTIAN_TOKEN_AUDIENCE="")
        self.refused(token(), OIDC_ISSUER="", OIDC_INTERNAL_ISSUER="")
        with patch.dict(os.environ, {"GENTIAN_TOKEN_AUDIENCE": ""}):
            self.assertFalse(realm_token.configured())

    def test_the_keys_are_fetched_once_and_not_again_for_every_unknown_key(self):
        realm_token.verify(token())
        realm_token.verify(token())
        self.assertEqual(len(self.realm.fetches), 1)
        # An unknown key right after a fetch is refused without another one.
        self.refused(token(kid="k2"))
        self.refused(token(kid="k3"))
        self.assertEqual(len(self.realm.fetches), 1)
        # Later, it costs one fetch: the realm may have a new key.
        with patch.object(realm_token.time, "monotonic", return_value=time.monotonic() + realm_token.KEYS_MIN_INTERVAL + 1):
            self.refused(token(kid="k2"))
        self.assertEqual(len(self.realm.fetches), 2)

    def test_a_realm_that_does_not_answer_is_a_refusal(self):
        with patch.object(realm_token.requests, "get", side_effect=realm_token.requests.ConnectionError("down")):
            self.refused(token())

    def test_an_api_key_does_not_look_like_a_token(self):
        self.assertFalse(realm_token.looks_like_one("0123456789abcdef0123456789abcdef01234567"))
        self.assertTrue(realm_token.looks_like_one(token()))


@tagged("post_install", "-at_install")
class TestBearerOnTheApi(RealmCase, HttpCase):
    """A person's token of the realm on the JSON-2 API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["auth.oauth.provider"].search([("client_id", "=", "odoo-cb")]).write({"client_id": "retired"})
        cls.provider = cls.env["auth.oauth.provider"].create({
            "name": "Keycloak",
            "client_id": "odoo-cb",
            "enabled": True,
            "auth_endpoint": ISSUER + "/protocol/openid-connect/auth",
            "validation_endpoint": ISSUER + "/protocol/openid-connect/userinfo",
            "body": "Keycloak",
        })
        cls.other_provider = cls.env["auth.oauth.provider"].create({
            "name": "Another",
            "client_id": "another",
            "enabled": True,
            "auth_endpoint": "https://other.example.test/auth",
            "validation_endpoint": "https://other.example.test/userinfo",
            "body": "Another",
        })
        cls.user = cls.env["res.users"].create({
            "name": "Person",
            "login": "person@example.test",
            "oauth_provider_id": cls.provider.id,
            "oauth_uid": "sub-1",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.stranger = cls.env["res.users"].create({
            "name": "Stranger",
            "login": "stranger@example.test",
            "oauth_provider_id": cls.other_provider.id,
            "oauth_uid": "sub-2",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def call(self, bearer, model="res.users", method="context_get", body=None):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        return self.url_open(f"/json/2/{model}/{method}", data=json.dumps(body or {}), headers=headers)

    def test_the_call_is_made_as_the_person_the_token_names(self):
        res = self.call(token())
        self.assertEqual(res.status_code, 200, res.text[:500])
        self.assertEqual(res.json()["uid"], self.user.id)

    def test_the_person_can_do_what_their_user_can_and_no_more(self):
        res = self.call(token(), "ir.config_parameter", "search_read", {"domain": [], "fields": ["key"]})
        self.assertEqual(res.status_code, 403, res.text[:500])

    def test_a_token_that_is_not_good_is_refused(self):
        self.assertEqual(self.call(token(aud=["odoo-crm-ce"])).status_code, 401)
        self.assertEqual(self.call(token(key=OTHER)).status_code, 401)
        self.assertEqual(self.call(token(exp=int(time.time()) - 1)).status_code, 401)
        self.assertEqual(self.call(None).status_code, 401)

    def test_a_call_makes_no_user(self):
        before = self.env["res.users"].with_context(active_test=False).search_count([])
        self.assertEqual(self.call(token(sub="sub-never-signed-in")).status_code, 401)
        self.assertEqual(self.env["res.users"].with_context(active_test=False).search_count([]), before)

    def test_a_user_of_another_provider_or_an_archived_one_is_nobody(self):
        self.assertEqual(self.call(token(sub="sub-2")).status_code, 401)
        self.user.active = False
        self.assertEqual(self.call(token()).status_code, 401)

    def test_odoos_own_api_keys_work_as_before(self):
        key = self.env["res.users.apikeys"].with_user(self.user)._generate("rpc", "test", datetime.now() + timedelta(days=1))
        res = self.call(key)
        self.assertEqual(res.status_code, 200, res.text[:500])
        self.assertEqual(res.json()["uid"], self.user.id)
        self.assertEqual(self.call("0123456789abcdef0123456789abcdef01234567").status_code, 401)

    def test_without_the_audience_a_token_is_only_a_bad_api_key(self):
        with patch.dict(os.environ, {"GENTIAN_TOKEN_AUDIENCE": ""}):
            self.assertEqual(self.call(token()).status_code, 401)
