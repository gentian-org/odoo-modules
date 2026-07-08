# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home


def _get_frame_ancestors():
    host = request.httprequest.host
    if not host:
        return "frame-ancestors 'self'"
    # Remove port if present
    host = host.split(':')[0]
    parts = host.split('.')
    if len(parts) >= 3:
        # For odoo.demo.desk.gentian.org, allow *.desk.gentian.org
        base_domain = '.'.join(parts[-3:])
        return f"frame-ancestors 'self' https://*.{base_domain}"
    return "frame-ancestors 'self'"


class GentianWebClient(http.Controller):
    """Expose embed-mode flag to the web client assets."""

    @http.route("/gentian_os/embed_mode", type="json", auth="public", readonly=True)
    def embed_mode(self):
        embed = request.httprequest.args.get("gentian_embed") == "1"
        return {"embed": embed}


import logging
_logger = logging.getLogger(__name__)


def _rewrite_response(response):
    _logger.info("REWRITE_RESPONSE CALLED: %s, headers: %s", type(response), getattr(response, 'headers', None))
    if isinstance(response, http.Response):
        response.headers.pop('X-Frame-Options', None)
        response.headers['Content-Security-Policy'] = _get_frame_ancestors()
        if 'Location' in response.headers:
            _logger.info("REWRITE_RESPONSE location: %s", response.headers['Location'])
            loc = response.headers['Location']
            if loc.startswith('/'):
                host = request.httprequest.host
                response.headers['Location'] = f"https://{host}{loc}"
                _logger.info("REWRITE_RESPONSE converted relative location: %s", response.headers['Location'])
            elif loc.startswith('http://'):
                response.headers['Location'] = loc.replace('http://', 'https://', 1)
                _logger.info("REWRITE_RESPONSE updated absolute location: %s", response.headers['Location'])
    return response


class GentianHome(Home):
    """Override standard Home routes to allow iframe framing in Gentian portal."""

    @http.route(['/web', '/odoo', '/odoo/<path:subpath>', '/scoped_app/<path:subpath>'], type='http', auth="none")
    def web_client(self, s_action=None, **kw):
        request.httprequest.environ['wsgi.url_scheme'] = 'https'
        return _rewrite_response(super().web_client(s_action=s_action, **kw))

    @http.route('/web/login', type='http', auth='none', readonly=False)
    def web_login(self, redirect=None, **kw):
        request.httprequest.environ['wsgi.url_scheme'] = 'https'
        return _rewrite_response(super().web_login(redirect=redirect, **kw))

