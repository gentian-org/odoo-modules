# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestServiceWorker(HttpCase):
    """The worker leaves page loads to the browser, ahead of Odoo's own listener."""

    def test_navigation_listener_comes_first(self):
        response = self.url_open("/web/service-worker.js")
        self.assertEqual(response.status_code, 200)
        body = response.text
        ours = body.find("event.stopImmediatePropagation()")
        odoos = body.find("navigateOrDisplayOfflinePage(event.request)")
        self.assertNotEqual(ours, -1)
        self.assertNotEqual(odoos, -1)
        self.assertLess(ours, odoos)
