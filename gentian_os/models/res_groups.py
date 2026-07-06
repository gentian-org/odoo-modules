# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo import fields, models


class ResGroups(models.Model):
    """Integrates Keycloak group identifiers with Odoo security groups."""

    _inherit = "res.groups"

    gentian_group_name = fields.Char(
        string="Gentian Group Name",
        index=True,
        help="The name/path of the matching Keycloak group.",
    )
