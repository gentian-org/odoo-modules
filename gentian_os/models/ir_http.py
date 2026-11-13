# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import logging
import re
from urllib.parse import urlencode

from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import Unauthorized

from odoo import models, http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.addons.gentian_os import oauth_code, realm_token
from odoo.addons.gentian_os.controllers.web_client import _rewrite_response
from odoo.addons.gentian_os.models.res_users import SYNCED_MODULES_KEY

_logger = logging.getLogger(__name__)

# Marks the navigation a stale session was sent round from, so that a sign-in
# that cannot stamp the session ends in the old rights, not in a loop.
RESYNC_PARAM = "gentian_resync"


def _stale_rights_redirect():
    """Send a Keycloak user whose session was synced for another module set
    through the zero-click sign-in again, which syncs their groups.

    Only on a page load of the web client: an RPC from a page already open is
    left alone, because ending its session would show Odoo's "session expired"
    instead of a sign-in. Opening a tile is a page load.
    """
    httpreq = request.httprequest
    path = httpreq.path
    if httpreq.method != "GET" or not request.session.uid:
        return None
    if not (path in ("/web", "/odoo") or path.startswith("/odoo/")):
        return None
    if request.params.get(RESYNC_PARAM):
        return None
    users = request.env["res.users"].sudo()
    user = users.browse(request.session.uid).exists()
    if not user or not user.oauth_uid:
        return None
    if request.session.get(SYNCED_MODULES_KEY) == users._gentian_modules_stamp():
        return None
    _logger.info("Session of %s was synced for another module set. Signing in again.", user.login)
    query = httpreq.query_string.decode()
    target = f"{path}?{query + '&' if query else ''}{RESYNC_PARAM}=1"
    request.session.logout(keep_db=True)
    return _rewrite_response(request.redirect(
        "/web/login?" + urlencode({"gentian_embed": "1", "redirect": target})
    ))


def _bearer_token():
    header = request.httprequest.headers.get("Authorization")
    match = re.match(r"^bearer\s+(.+)$", header, re.IGNORECASE) if header else None
    return match.group(1).strip() if match else None


def _refuse(reason):
    return Unauthorized(reason, www_authenticate=WWWAuthenticate("bearer"))


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _auth_method_bearer(cls):
        """Accept, beside Odoo's own API keys, a person's access token that
        the platform's realm issued for this Odoo (realm_token).

        The token says who the person is; what they may do is what their
        Odoo user may do. That user is the one the sign-in through the realm
        made: a call creates none, so a person who never signed in to Odoo is
        refused, and so is one whose user is archived. Anything that is not
        such a token goes to Odoo's own check unchanged.
        """
        token = _bearer_token()
        if not (token and realm_token.configured() and realm_token.looks_like_one(token)):
            return super()._auth_method_bearer()
        try:
            claims = realm_token.verify(token)
        except realm_token.Refused as exc:
            _logger.info("A realm token was refused on the API: %s", exc)
            raise _refuse(str(exc)) from None
        user = cls._gentian_user_of(claims["sub"])
        if not user:
            _logger.info("A realm token named a person with no Odoo user.")
            raise _refuse("this person has no user in this Odoo: they sign in to it once first")
        if request.env.uid and request.env.uid != user.id:
            raise AccessDenied("Session user does not match the token's person.")
        request.update_env(user=user.id)
        request.session.can_save = False  # stateless, as with an API key
        cls._auth_method_user()

    @classmethod
    def _gentian_user_of(cls, subject):
        """The one active user the platform's sign-in made for this person,
        or none."""
        env = request.env(su=True)
        nobody = env["res.users"]
        client_id = oauth_code.platform_client_id()
        if not client_id:
            return nobody
        providers = env["auth.oauth.provider"].search([("client_id", "=", client_id)])
        if not providers:
            return nobody
        found = env["res.users"].search(
            [("oauth_uid", "=", subject), ("oauth_provider_id", "in", providers.ids)], limit=2
        )
        return found if len(found) == 1 else nobody

    @classmethod
    def _dispatch(cls, endpoint):
        # Prevent session contamination when switching portal accounts
        # This check runs for ALL HTTP requests dispatched by Odoo.
        login_hint = request.params.get("login_hint")
        if login_hint and request.session.uid:
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user:
                current_login = user.login
                current_email = user.email
                current_username = current_login.split('@')[0] if current_login else ""
                # Check if the session user matches the portal login_hint
                if login_hint != current_login and login_hint != current_username and login_hint != current_email:
                    _logger.warning(
                        "Active Odoo session (%s/%s) does not match portal login_hint (%s). Logging out.",
                        current_login, current_email, login_hint
                    )
                    request.session.logout(keep_db=True)
                    # Redirect to trigger re-auth
                    return _rewrite_response(request.redirect(
                        f"/web/login?gentian_embed=1&redirect={request.httprequest.full_path}"
                    ))

        stale = _stale_rights_redirect()
        if stale:
            return stale

        return super()._dispatch(endpoint)
