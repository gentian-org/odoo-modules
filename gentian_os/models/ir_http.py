# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import logging
from odoo import models, http
from odoo.http import request
from odoo.addons.gentian_os.controllers.web_client import _rewrite_response

_logger = logging.getLogger(__name__)


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

        return super()._dispatch(endpoint)
