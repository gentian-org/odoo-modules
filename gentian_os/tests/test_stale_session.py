# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import json
from unittest.mock import patch
from urllib.parse import parse_qs, quote_plus, urlparse

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestStaleSession(HttpCase):
    """A session synced for another module set signs in again on a page load."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["auth.oauth.provider"].create({
            "name": "Keycloak",
            "client_id": "odoo",
            "enabled": True,
            "auth_endpoint": "https://id.example.test/auth",
            "validation_endpoint": "https://id.example.test/userinfo",
            "scope": "openid",
            "body": "Keycloak",
        })
        cls.user = cls.env["res.users"].create({
            "name": "Person",
            "login": "person@example.test",
            "password": "person-password-1",
            "oauth_provider_id": cls.provider.id,
            "oauth_uid": "sub-1",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def _sign_in_by_oauth(self):
        validation = {"sub": "sub-1", "email": "person@example.test", "groups": []}
        state = json.dumps({"d": self.env.cr.dbname, "p": self.provider.id, "r": quote_plus("/odoo")})
        with patch.object(type(self.env["res.users"]), "_auth_oauth_rpc", return_value=validation):
            return self.url_open(
                "/auth_oauth/signin?" + "&".join([
                    "access_token=token-1", "state=" + quote_plus(state),
                ]),
                allow_redirects=False,
            )

    def test_stale_session_is_sent_round(self):
        # A password session carries no stamp: as an old session would.
        self.authenticate("person@example.test", "person-password-1")
        res = self.url_open("/odoo/action-base.action_res_users?gentian_embed=1", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
        location = urlparse(res.headers["Location"])
        self.assertEqual(location.path, "/web/login")
        query = parse_qs(location.query)
        self.assertEqual(query["gentian_embed"], ["1"])
        self.assertEqual(
            query["redirect"], ["/odoo/action-base.action_res_users?gentian_embed=1&gentian_resync=1"]
        )

    def test_resync_param_ends_it(self):
        self.authenticate("person@example.test", "person-password-1")
        res = self.url_open("/odoo?gentian_resync=1", allow_redirects=False)
        self.assertEqual(res.status_code, 200)

    def test_oauth_sign_in_stamps_the_session(self):
        res = self._sign_in_by_oauth()
        self.assertIn(res.status_code, (302, 303), res.text[:500])
        res = self.url_open("/odoo", allow_redirects=False)
        self.assertEqual(res.status_code, 200)

    def test_changed_modules_make_it_stale(self):
        self._sign_in_by_oauth()
        Users = type(self.env["res.users"])
        with patch.object(Users, "_gentian_modules_stamp", return_value="another-set"):
            res = self.url_open("/odoo", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
        self.assertTrue(urlparse(res.headers["Location"]).path.endswith("/web/login"))

    def test_password_users_are_left_alone(self):
        self.user.oauth_uid = False
        self.authenticate("person@example.test", "person-password-1")
        res = self.url_open("/odoo", allow_redirects=False)
        self.assertEqual(res.status_code, 200)

    def test_stamp_follows_installed_modules(self):
        Users = self.env["res.users"]
        before = Users._gentian_modules_stamp()
        self.assertEqual(before, Users._gentian_modules_stamp())
        self.env["ir.module.module"].search([("name", "=", "gentian_os")]).state = "to upgrade"
        self.assertNotEqual(before, Users._gentian_modules_stamp())
