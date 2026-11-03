# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo.addons.web.controllers import webmanifest

# Odoo's worker answers every page load itself, with fetch(request). The
# platform's edge sees that fetch as a request a page makes in the background
# (Sec-Fetch-Dest: empty) and, once the edge session has ended, answers it 401
# instead of sending the browser to sign in: the tab shows "OAuth flow
# failed." Registered first, this listener ends the dispatch for a page load
# before Odoo's listener sees it, so the browser loads the page itself and
# follows the redirect. Everything else in the worker stays; the offline page
# is what goes.
NAVIGATION_PASSTHROUGH = """\
// gentian_os: page loads are the browser's own, so a sign-in redirect is followed.
self.addEventListener("fetch", (event) => {
    if (event.request.mode === "navigate") {
        event.stopImmediatePropagation();
    }
});

"""


class GentianWebManifest(webmanifest.WebManifest):

    def _get_service_worker_content(self):
        return NAVIGATION_PASSTHROUGH + super()._get_service_worker_content()
