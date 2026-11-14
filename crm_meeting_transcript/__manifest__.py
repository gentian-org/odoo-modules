# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0 (Odoo addon).

{
    "name": "Meeting transcripts",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Keep meeting transcripts with the opportunities they belong to",
    "description": """
A transcript of a meeting -- recorded with a voice recorder, or written down --
kept with its opportunity: who took part, a summary, the full text, and where
it came from. A recording filed twice from the same source is kept once.
""",
    "author": "Gentian",
    "license": "LGPL-3",
    "depends": ["crm", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "views/crm_meeting_transcript_views.xml",
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
}
