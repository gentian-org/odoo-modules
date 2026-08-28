# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

"""Keep OAuth credentials out of the log.

auth_oauth uses the implicit flow: Keycloak returns the access token in the URL
fragment, and Odoo's own JS turns that fragment into a query string before
re-requesting. By the time werkzeug logs the request line, the bearer token is
a query parameter — so every sign-in wrote a usable token into the access log
in plaintext, readable for its full lifetime by anything that can read logs.

Redacting at the logging layer rather than at the callers, because the caller
here is werkzeug: the URL is logged by the WSGI server before any Odoo code of
ours runs, and there is no hook to change what it logs.
"""

import logging
import re

# Anchored on a query-parameter boundary (? or &) so that a bare word like
# "code" inside a path or a message is left alone — the intent is to redact
# credentials, not to make lines unreadable.
_SENSITIVE_PARAMS = (
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "code",
    "session_state",
)

_QUERY_CREDENTIAL = re.compile(
    r"([?&](?:%s)=)([^&\s\"'#]+)" % "|".join(re.escape(p) for p in _SENSITIVE_PARAMS),
    re.IGNORECASE,
)

_REPLACEMENT = r"\1<redacted>"


def scrub(value):
    """Redact credential query parameters in one value, if it is a string."""
    if isinstance(value, str):
        return _QUERY_CREDENTIAL.sub(_REPLACEMENT, value)
    return value


class RedactCredentialsFilter(logging.Filter):
    """Rewrite credential query parameters out of a record before it is emitted.

    Operates on msg and args rather than the formatted line, because a filter
    runs before formatting — the URL is still sitting in record.args at this
    point, which is exactly where werkzeug puts the request line.
    """

    def filter(self, record):
        record.msg = scrub(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: scrub(val) for key, val in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(scrub(arg) for arg in record.args)
        return True


def install():
    """Attach the filter everywhere a request URL can reach the log.

    Both the werkzeug logger and the root handlers: a logger's filters apply
    only to records logged through that logger and are not inherited by
    children, so the werkzeug logger has to be named directly. The root
    handlers then cover anything else that formats a URL into a message, since
    handler filters do see every record that reaches them.
    """
    log_filter = RedactCredentialsFilter()

    werkzeug_logger = logging.getLogger("werkzeug")
    if not any(isinstance(f, RedactCredentialsFilter) for f in werkzeug_logger.filters):
        werkzeug_logger.addFilter(log_filter)

    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactCredentialsFilter) for f in handler.filters):
            handler.addFilter(log_filter)
