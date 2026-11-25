# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import api, fields, models

from .summary import to_html


class CrmMeetingTranscript(models.Model):
    """A meeting's transcript, kept with the opportunity it belongs to.

    The model knows no recorder's format. A transcript is filed by a person or
    by a program acting for one (the Odoo adapter's tools); `source` and
    `external_ref` say where it came from, so the same recording filed twice
    is refused instead of kept twice.
    """

    _name = "crm.meeting.transcript"
    _description = "Meeting transcript"
    _inherit = ["mail.thread"]
    _order = "meeting_date desc, id desc"

    name = fields.Char(required=True, tracking=True)
    meeting_date = fields.Datetime(
        string="Meeting date", required=True, default=fields.Datetime.now, tracking=True
    )
    duration_minutes = fields.Integer(string="Duration (minutes)")
    lead_id = fields.Many2one(
        "crm.lead", string="Opportunity", index=True, ondelete="cascade", tracking=True
    )
    partner_ids = fields.Many2many("res.partner", string="Participants")
    user_id = fields.Many2one(
        "res.users", string="Recorded by", default=lambda self: self.env.user, index=True
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        index=True,
    )
    summary = fields.Html()
    transcript = fields.Text()
    source = fields.Selection(
        [("manual", "Manual"), ("plaud", "Plaud")], required=True, default="manual"
    )
    external_ref = fields.Char(
        string="Reference at the source",
        copy=False,
        index=True,
        help="The recording's identifier where it came from.",
    )

    _source_ref_unique = models.Constraint(
        "UNIQUE(source, external_ref)",
        "This recording is filed already.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # A summary written as text or Markdown is kept as formatted HTML.
        for vals in vals_list:
            if isinstance(vals.get("summary"), str):
                vals["summary"] = to_html(vals["summary"])
        return super().create(vals_list)

    def write(self, vals):
        if isinstance(vals.get("summary"), str):
            vals = {**vals, "summary": to_html(vals["summary"])}
        return super().write(vals)

    @api.depends("lead_id")
    def _compute_company_id(self):
        # The opportunity's company; without one, the company it was filed in.
        for transcript in self:
            transcript.company_id = (
                transcript.lead_id.company_id or transcript.company_id or self.env.company
            )
