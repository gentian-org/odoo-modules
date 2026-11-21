# Copyright 2026 Gentian Authors. Licensed under AGPL-3.0.

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user


class TestAttachPicked(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Acme"})
        cls.picked = {
            "name": "Offer.pdf",
            "id": "4711",
            "url": "https://cloud.acme.example/f/4711",
        }

    def test_a_picked_file_is_attached_as_a_link(self):
        Attachment = self.env["ir.attachment"]
        attachment = Attachment.browse(
            Attachment.gentian_attach_picked("res.partner", self.partner.id, self.picked)
        )
        self.assertEqual(attachment.type, "url")
        self.assertEqual(attachment.url, "https://cloud.acme.example/f/4711")
        self.assertEqual(attachment.mimetype, "application/link")
        self.assertEqual(attachment.gentian_file_id, "4711")
        self.assertEqual((attachment.res_model, attachment.res_id), ("res.partner", self.partner.id))

    def test_only_an_https_address_is_kept(self):
        Attachment = self.env["ir.attachment"]
        for url in ("javascript:alert(1)", "http://cloud.acme.example/f/1", "https:///f/1", ""):
            with self.assertRaises(UserError):
                Attachment.gentian_attach_picked(
                    "res.partner", self.partner.id, dict(self.picked, url=url)
                )
        with self.assertRaises(UserError):
            Attachment.gentian_attach_picked("res.partner", self.partner.id, dict(self.picked, id=""))

    def test_the_record_must_be_writable_by_the_person(self):
        reader = new_test_user(self.env, login="reader", groups="base.group_portal")
        with self.assertRaises(AccessError):
            self.env["ir.attachment"].with_user(reader).gentian_attach_picked(
                "res.partner", self.partner.id, self.picked
            )
