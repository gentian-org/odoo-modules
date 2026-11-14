# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    transcript_ids = fields.One2many(
        "crm.meeting.transcript", "lead_id", string="Meeting transcripts"
    )
    transcript_count = fields.Integer(compute="_compute_transcript_count")

    @api.depends("transcript_ids")
    def _compute_transcript_count(self):
        for lead in self:
            lead.transcript_count = len(lead.transcript_ids)

    def action_view_transcripts(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "crm_meeting_transcript.crm_meeting_transcript_action"
        )
        action["domain"] = [("lead_id", "=", self.id)]
        action["context"] = {
            "default_lead_id": self.id,
            "default_partner_ids": self.partner_id.ids,
        }
        return action
