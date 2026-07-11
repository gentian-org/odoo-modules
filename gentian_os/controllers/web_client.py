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
        
        # Convert action query parameter to hash fragment only if the user is authenticated.
        # If they are not authenticated, keep it in the query string so Odoo's login redirect
        # preserves it in the "redirect" parameter.
        action = request.params.get("action")
        if action and request.session.uid:
            params = dict(request.params)
            params.pop("action", None)
            from urllib.parse import urlencode
            query = urlencode(params)
            # Redirect to the hash version
            redirect_url = f"/web?{query}#action={action}"
            return _rewrite_response(request.redirect(redirect_url))
            
        return _rewrite_response(super().web_client(s_action=s_action, **kw))

    @http.route('/web/login', type='http', auth='none', readonly=False)
    def web_login(self, redirect=None, **kw):
        request.httprequest.environ['wsgi.url_scheme'] = 'https'
        
        # Check if we are embedded in the Gentian portal, either from query parameters
        # or extracted from the URL-encoded redirect parameter (common when redirected by Odoo core)
        gentian_embed = request.params.get("gentian_embed") == "1"
        login_hint = request.params.get("login_hint")
        
        redirect_param = request.params.get("redirect")
        if redirect_param and (not gentian_embed or not login_hint):
            from urllib.parse import urlparse, parse_qs
            try:
                parsed = urlparse(redirect_param)
                qs = parse_qs(parsed.query)
                if not gentian_embed and qs.get("gentian_embed") == ["1"]:
                    gentian_embed = True
                if not login_hint:
                    hints = qs.get("login_hint")
                    if hints:
                        login_hint = hints[0]
            except Exception:
                pass

        # Auto-redirect embedded login requests to Keycloak for Zero-Click SSO
        if gentian_embed and not request.session.uid and not kw.get("oauth_error"):
            oauth_login = GentianOAuthLogin()
            providers = oauth_login.list_providers()
            keycloak_provider = next((p for p in providers if p.get("name") == "Keycloak"), None)
            if keycloak_provider and keycloak_provider.get("auth_link"):
                auth_link = keycloak_provider["auth_link"]
                # Forward login_hint if available to enable silent/pre-filled SSO in Keycloak
                if login_hint:
                    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
                    try:
                        parsed_auth = urlparse(auth_link)
                        qsl = parse_qsl(parsed_auth.query)
                        qsl = [item for item in qsl if item[0] != 'login_hint']
                        qsl.append(('login_hint', login_hint))
                        auth_link = urlunparse(parsed_auth._replace(query=urlencode(qsl)))
                    except Exception:
                        pass
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

