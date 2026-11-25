# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestMeetingTranscript(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.anna = new_test_user(cls.env, "anna", groups="sales_team.group_sale_salesman")
        cls.ben = new_test_user(cls.env, "ben", groups="sales_team.group_sale_salesman")
        cls.mia = new_test_user(cls.env, "mia", groups="sales_team.group_sale_salesman_all_leads")
        cls.customer = cls.env["res.partner"].create({"name": "Acme AG"})
        cls.annas_deal = cls.env["crm.lead"].create(
            {"name": "Acme pilot", "type": "opportunity", "user_id": cls.anna.id,
             "partner_id": cls.customer.id}
        )
        cls.bens_deal = cls.env["crm.lead"].create(
            {"name": "Other deal", "type": "opportunity", "user_id": cls.ben.id}
        )
        Transcript = cls.env["crm.meeting.transcript"]
        cls.on_annas = Transcript.create(
            {"name": "Kick-off", "lead_id": cls.annas_deal.id, "user_id": cls.anna.id,
             "transcript": "We agreed on a pilot.", "source": "plaud", "external_ref": "rec-1"}
        )
        cls.on_bens = Transcript.create(
            {"name": "Call", "lead_id": cls.bens_deal.id, "user_id": cls.ben.id}
        )
        cls.bens_loose = Transcript.create({"name": "Notes", "user_id": cls.ben.id})

    def visible_to(self, user):
        return self.env["crm.meeting.transcript"].with_user(user).search([])

    def test_a_salesperson_sees_the_transcripts_of_the_opportunities_they_see(self):
        seen = self.visible_to(self.anna)
        self.assertIn(self.on_annas, seen)
        self.assertNotIn(self.on_bens, seen)
        self.assertNotIn(self.bens_loose, seen)

    def test_one_without_an_opportunity_is_seen_by_the_person_who_filed_it(self):
        seen = self.visible_to(self.ben)
        self.assertIn(self.bens_loose, seen)
        self.assertIn(self.on_bens, seen)
        self.assertNotIn(self.on_annas, seen)

    def test_whoever_sees_all_opportunities_sees_all_transcripts(self):
        seen = self.visible_to(self.mia)
        self.assertTrue({self.on_annas, self.on_bens, self.bens_loose} <= set(seen))

    def test_a_transcript_of_an_unassigned_opportunity_is_seen_like_the_opportunity(self):
        open_deal = self.env["crm.lead"].create({"name": "Open", "type": "opportunity", "user_id": False})
        transcript = self.env["crm.meeting.transcript"].create(
            {"name": "Intro", "lead_id": open_deal.id, "user_id": self.ben.id}
        )
        self.assertIn(transcript, self.visible_to(self.anna))

    def test_the_same_recording_is_not_filed_twice(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["crm.meeting.transcript"].create(
                {"name": "Again", "source": "plaud", "external_ref": "rec-1"}
            )

    def test_transcripts_without_a_reference_are_not_held_to_one(self):
        Transcript = self.env["crm.meeting.transcript"]
        Transcript.create({"name": "One", "source": "manual"})
        Transcript.create({"name": "Two", "source": "manual"})

    def test_the_opportunity_counts_and_opens_its_transcripts(self):
        self.assertEqual(self.annas_deal.transcript_count, 1)
        action = self.annas_deal.action_view_transcripts()
        self.assertEqual(action["res_model"], "crm.meeting.transcript")
        self.assertEqual(action["domain"], [("lead_id", "=", self.annas_deal.id)])
        self.assertEqual(action["context"]["default_lead_id"], self.annas_deal.id)

    def test_the_company_is_the_opportunitys(self):
        self.assertEqual(self.on_annas.company_id, self.annas_deal.company_id)

    def test_a_salesperson_files_a_transcript_for_their_opportunity(self):
        filed = self.env["crm.meeting.transcript"].with_user(self.anna).create(
            {"name": "Follow-up", "lead_id": self.annas_deal.id}
        )
        self.assertEqual(filed.user_id, self.anna)
        self.assertEqual(filed.source, "manual")

    def test_a_summary_written_as_markdown_is_kept_as_html(self):
        transcript = self.env["crm.meeting.transcript"].create({
            "name": "Dictation",
            "summary": (
                "[](plaud://highlight-card?title=Summary)\n"
                "- **Goal**: more soup <script>x</script>\n"
                "## Action Items\n"
                "- [ ] Find providers [](plaud://source?x=1)\n"
                "- [x] Send a card"
            ),
        })
        html = str(transcript.summary)
        self.assertIn("<li><strong>Goal</strong>: more soup &lt;script&gt;x&lt;/script&gt;</li>", html)
        self.assertIn("Action Items</h4>", html)
        self.assertIn("<li>☐ Find providers</li>", html)
        self.assertIn("<li>☑ Send a card</li>", html)
        self.assertNotIn("plaud://", html)
        self.assertNotIn("<script>", html)

    def test_a_summary_given_as_html_is_kept_and_text_keeps_its_lines(self):
        Transcript = self.env["crm.meeting.transcript"]
        given = Transcript.create({"name": "A", "summary": "<p>Kept <em>as is</em></p>"})
        self.assertEqual(str(given.summary), "<p>Kept <em>as is</em></p>")
        given.write({"summary": "first line\nsecond line"})
        self.assertEqual(str(given.summary), "<p>first line<br>second line</p>")
