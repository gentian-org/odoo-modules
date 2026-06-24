# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0 (Odoo addon).

{
    "name": "gentian_os",
    "version": "18.0.1.0.0",
    "category": "Hidden",
    "summary": "Gentian OS integration driver for Odoo",
    "description": """
Gentian platform integration: portal embed mode, IdM bindings, and module registry.
""",
    "author": "Gentian",
    "license": "LGPL-3",
    "depends": ["base", "web", "auth_oauth"],
    "data": [
        "data/ir_actions.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "gentian_os/static/src/web/embed_mode.js",
            "gentian_os/static/src/web/embed_mode.scss",
        ],
    },
    "installable": True,
    "application": False,
}
