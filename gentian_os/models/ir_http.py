# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import logging
from urllib.parse import urlencode

from odoo import models, http
from odoo.http import request
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


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

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
