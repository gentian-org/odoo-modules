# Copyright 2026 Gentian Authors. Licensed under AGPL-3.0.

{
    "name": "Attachments from your files",
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "summary": "Attach a file from the workspace's file storage, chosen in the platform's file dialog",
    "description": """
Adds "Attach from files" to the attachment area of every record. The person
chooses a file in the platform's file dialog, a window of the platform's own;
the record keeps a link to the file, which stays where it is. Whoever opens
the link is asked by the file storage, signed in as themselves.

Odoo is given no access to anybody's files: it is told the file's name, its id
and the address that opens it, and nothing else.
""",
    "author": "Gentian",
    "license": "AGPL-3",
    "depends": ["mail", "document_url"],
    "assets": {
        "web.assets_backend": [
            "gentian_files/static/src/js/attach_from_files.esm.js",
            "gentian_files/static/src/xml/attach_from_files.xml",
        ],
    },
    "installable": True,
    "application": False,
}
