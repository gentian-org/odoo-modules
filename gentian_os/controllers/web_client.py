# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
try:
    from odoo.addons.auth_oauth.controllers.main import OAuthLogin
except ImportError:
    OAuthLogin = object


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
        
        # Auto-redirect embedded login requests to Keycloak for Zero-Click SSO
        if request.params.get("gentian_embed") == "1" and not request.session.uid and not kw.get("oauth_error"):
            oauth_login = GentianOAuthLogin()
            providers = oauth_login.list_providers()
            keycloak_provider = next((p for p in providers if p.get("name") == "Keycloak"), None)
            if keycloak_provider and keycloak_provider.get("auth_link"):
                auth_link = keycloak_provider["auth_link"]
                _logger.info("Auto-redirecting portal-embedded Odoo login to Keycloak: %s", auth_link)
                return _rewrite_response(request.redirect(auth_link, local=False))

        return _rewrite_response(super().web_login(redirect=redirect, **kw))


class GentianOAuthLogin(OAuthLogin):
    """Override OAuthLogin controller to force HTTPS redirect URI for providers."""

    def list_providers(self):
        providers = super().list_providers() if OAuthLogin is not object else []
        for provider in providers:
            if provider.get('auth_link'):
                auth_link = provider['auth_link']
                # Correct redirect_uri to HTTPS
                if 'redirect_uri=http%3A' in auth_link:
                    provider['auth_link'] = auth_link.replace('redirect_uri=http%3A', 'redirect_uri=https%3A', 1)
                # Correct state redirect parameter to HTTPS if needed
                if 'http%253A%252F%252F' in auth_link:
                    provider['auth_link'] = provider['auth_link'].replace('http%253A%252F%252F', 'https%253A%252F%252F')
        return providers

