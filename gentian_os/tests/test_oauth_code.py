# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import json
import os
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, quote_plus, urlparse

from odoo.tests import BaseCase, HttpCase, tagged

from odoo.addons.gentian_os import oauth_code

ENV = {
    "OIDC_CLIENT_ID": "odoo-cb",
    "OIDC_CLIENT_SECRET": "client-secret-1",
    "OIDC_ISSUER": "https://id.example.test/auth/realms/team",
    "OIDC_INTERNAL_ISSUER": "http://keycloak.internal:8080/auth/realms/team",
}


@tagged("post_install", "-at_install")
class TestCodeFlowSignIn(HttpCase):
    """The platform's provider signs in with a code, never a token in the URL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["auth.oauth.provider"].search([("name", "=", "Keycloak")]).write({"enabled": False})
        cls.provider = cls.env["auth.oauth.provider"].create({
            "name": "Keycloak",
            "client_id": "odoo-cb",
            "enabled": True,
            "auth_endpoint": "https://id.example.test/auth/realms/team/protocol/openid-connect/auth",
            "validation_endpoint": "http://keycloak.internal:8080/auth/realms/team/protocol/openid-connect/userinfo",
            "scope": "openid profile email",
            "body": "Keycloak",
        })
        cls.user = cls.env["res.users"].create({
            "name": "Person",
            "login": "person@example.test",
            "oauth_provider_id": cls.provider.id,
            "oauth_uid": "sub-1",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)

    def _start(self):
        """The embedded login sends the browser to Keycloak; the link it names."""
        res = self.url_open("/web/login?gentian_embed=1", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303), res.text[:300])
        link = urlparse(res.headers["Location"])
        return link, {k: v[0] for k, v in parse_qs(link.query).items()}

    def _return(self, params, code="code-1"):
        validation = {"sub": "sub-1", "email": "person@example.test", "groups": []}
        Users = type(self.env["res.users"])
        query = "code=%s&state=%s&session_state=s-1" % (code, quote_plus(params["state"]))
        with patch.object(Users, "_auth_oauth_rpc", return_value=validation):
            return self.url_open("/auth_oauth/signin?" + query, allow_redirects=False)

    def test_link_asks_for_a_code_with_pkce(self):
        _, params = self._start()
        self.assertEqual(params["response_type"], "code")
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertTrue(params["code_challenge"])
        self.assertEqual(params["client_id"], "odoo-cb")
        self.assertIn(oauth_code.STATE_KEY, json.loads(params["state"]))

    def test_code_is_exchanged_and_signs_in(self):
        _, params = self._start()
        with patch.object(oauth_code, "exchange", return_value="token-1") as exchanged:
            res = self._return(params)
        self.assertEqual(res.status_code, 303, res.text[:300])
        self.assertNotIn("oauth_error", res.headers["Location"])
        code, redirect_uri, verifier = exchanged.call_args.args
        self.assertEqual(code, "code-1")
        self.assertEqual(redirect_uri, params["redirect_uri"])
        self.assertEqual(oauth_code.challenge(verifier), params["code_challenge"])
        self.assertEqual(self.url_open("/odoo", allow_redirects=False).status_code, 200)

    def test_a_code_for_a_sign_in_not_started_here_is_refused(self):
        _, params = self._start()
        state = json.loads(params["state"])
        state[oauth_code.STATE_KEY] = "another"
        params["state"] = json.dumps(state)
        with patch.object(oauth_code, "exchange") as exchanged:
            res = self._return(params)
        exchanged.assert_not_called()
        self.assertIn("oauth_error=2", res.headers["Location"])

    def test_a_state_is_used_once(self):
        _, params = self._start()
        with patch.object(oauth_code, "exchange", return_value="token-1"):
            self._return(params)
        self.url_open("/web/session/logout", allow_redirects=False)
        with patch.object(oauth_code, "exchange", return_value="token-1") as exchanged:
            res = self._return(params)
        exchanged.assert_not_called()
        self.assertIn("oauth_error", res.headers["Location"])

    def test_a_refused_exchange_ends_in_access_denied(self):
        _, params = self._start()
        refused = oauth_code.ExchangeError("the token endpoint refused the code (400, invalid_grant: Code not valid)")
        with patch.object(oauth_code, "exchange", side_effect=refused), \
                self.assertLogs("odoo.addons.gentian_os.controllers.web_client", "WARNING") as logged:
            res = self._return(params, code="secret-code-1")
        self.assertIn("oauth_error=2", res.headers["Location"])
        self.assertNotIn("secret-code-1", "\n".join(logged.output))

    def test_another_provider_keeps_odoo_behaviour(self):
        self.provider.client_id = "someone-else"
        res = self.url_open("/web/login", allow_redirects=False)
        self.assertNotIn("code_challenge", res.text)


@tagged("post_install", "-at_install")
class TestExchange(BaseCase):
    """The exchange posts what the token endpoint needs and leaks nothing."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)

    def _answer(self, status, body):
        response = MagicMock(status_code=status)
        response.json.return_value = body
        return response

    def test_posts_to_the_internal_issuer(self):
        with patch.object(oauth_code.requests, "post", return_value=self._answer(200, {"access_token": "t-1"})) as post:
            token = oauth_code.exchange("c-1", "https://odoo.example.test/auth_oauth/signin", "v-1")
        self.assertEqual(token, "t-1")
        url = post.call_args.args[0]
        data = post.call_args.kwargs["data"]
        self.assertEqual(url, "http://keycloak.internal:8080/auth/realms/team/protocol/openid-connect/token")
        self.assertEqual(data["grant_type"], "authorization_code")
        self.assertEqual(data["code_verifier"], "v-1")
        self.assertEqual(data["client_secret"], "client-secret-1")
        self.assertEqual(data["redirect_uri"], "https://odoo.example.test/auth_oauth/signin")

    def test_refusal_names_the_error_not_the_code(self):
        refused = self._answer(400, {"error": "invalid_grant", "error_description": "Code not valid"})
        with patch.object(oauth_code.requests, "post", return_value=refused):
            with self.assertRaises(oauth_code.ExchangeError) as raised:
                oauth_code.exchange("secret-code-1", "https://x/auth_oauth/signin", "v-1")
        self.assertIn("invalid_grant", str(raised.exception))
        self.assertNotIn("secret-code-1", str(raised.exception))
        self.assertNotIn("client-secret-1", str(raised.exception))

    def test_challenge_is_rfc7636_s256(self):
        # RFC 7636 appendix B.
        self.assertEqual(
            oauth_code.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )
