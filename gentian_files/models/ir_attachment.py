# Copyright 2026 Gentian Authors. Licensed under AGPL-3.0.

from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    gentian_file_id = fields.Char(
        string="File id",
        readonly=True,
        help="The file's id at the workspace's file storage, for a file "
        "attached from there.",
    )

    @api.model
    def gentian_attach_picked(self, res_model, res_id, picked):
        """Attach a file the person picked in the platform's file dialog to a
        record, as a link: its name, its id and the address that opens it.

        The record is checked as for any attachment: the person must be able
        to write to it. The address must be an https address, so nothing but a
        link to a page is kept."""
        name = (picked or {}).get("name") or ""
        file_id = (picked or {}).get("id") or ""
        url = (picked or {}).get("url") or ""
        parsed = urlparse(url)
        if not name or not file_id or parsed.scheme != "https" or not parsed.netloc:
            raise UserError(_("The file dialog did not name a file."))
        record = self.env[res_model].browse(int(res_id)).exists()
        if not record:
            raise UserError(_("The record is not there any more."))
        record.check_access("write")
        attachment = self.create(
            {
                "name": name[:255],
                "type": "url",
                "url": url,
                "gentian_file_id": file_id[:255],
                "res_model": res_model,
                "res_id": record.id,
            }
        )
        return attachment.id
