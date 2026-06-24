# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import http
from odoo.http import request


class GentianWebClient(http.Controller):
    """Expose embed-mode flag to the web client assets."""

    @http.route("/gentian_os/embed_mode", type="json", auth="public", readonly=True)
    def embed_mode(self):
        embed = request.httprequest.args.get("gentian_embed") == "1"
        return {"embed": embed}
