# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPlatformRoles(TransactionCase):
    """A person's groups are set at sign-in to the roles the platform says."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = cls.env.ref("base.group_user")
        cls.portal = cls.env.ref("base.group_portal")
        cls.system = cls.env.ref("base.group_system")
        cls.erp_manager = cls.env.ref("base.group_erp_manager")
        cls.own = cls.env["res.groups"].create({"name": "Given inside Odoo"})
        cls.mapped = ["base.group_user", "base.group_system", "base.group_erp_manager", "not_installed.group_x"]

    def _person(self, groups):
        return self.env["res.users"].create({
            "name": "Person",
            "login": "roles-%s@example.test" % len(self.env["res.users"].search([])),
            "group_ids": [(6, 0, [g.id for g in groups])],
        })

    def test_held_roles_are_given_and_the_rest_of_the_mapped_taken(self):
        person = self._person([self.internal, self.system, self.own])
        person._sync_platform_roles({
            "gentian_app_roles": ["base.group_user", "base.group_erp_manager"],
            "gentian_app_roles_mapped": self.mapped,
        })
        self.assertIn(self.internal, person.group_ids)
        self.assertIn(self.erp_manager, person.group_ids)
        self.assertNotIn(self.system, person.group_ids)
        # What an administrator gave inside Odoo is not the platform's.
        self.assertIn(self.own, person.group_ids)

    def test_a_person_with_a_role_becomes_an_internal_user(self):
        person = self._person([self.portal])
        person._sync_platform_roles({"gentian_app_roles": ["base.group_user"], "gentian_app_roles_mapped": self.mapped})
        self.assertIn(self.internal, person.group_ids)
        self.assertNotIn(self.portal, person.group_ids)

    def test_a_token_that_does_not_say_changes_nothing(self):
        person = self._person([self.internal, self.system])
        before = person.group_ids
        person._sync_platform_roles({"sub": "sub-1", "groups": ["gentian:tenant:acme:admins"]})
        self.assertEqual(person.group_ids, before)

    def test_a_group_the_platform_did_not_map_is_not_given(self):
        person = self._person([self.internal])
        person._sync_platform_roles({
            "gentian_app_roles": ["base.group_user", "base.group_system"],
            "gentian_app_roles_mapped": ["base.group_user"],
        })
        self.assertNotIn(self.system, person.group_ids)

    def test_no_role_takes_every_mapped_group(self):
        person = self._person([self.internal, self.system])
        person._sync_platform_roles({"gentian_app_roles": [], "gentian_app_roles_mapped": ["base.group_system"]})
        self.assertNotIn(self.system, person.group_ids)

    def test_the_accounts_odoo_ships_with_are_not_demoted(self):
        admin = self.env.ref("base.user_admin")
        self.assertIn(self.system, admin.group_ids)
        admin._sync_platform_roles({"gentian_app_roles": ["base.group_user"], "gentian_app_roles_mapped": self.mapped})
        self.assertIn(self.system, admin.group_ids)
