# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """Overrides user sign-in to dynamically map Keycloak group claims."""

    _inherit = "res.users"

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        # Call standard OAuth sign-in to authenticate/provision the user
        login = super(ResUsers, self)._auth_oauth_signin(provider, validation, params)
        if not login:
            return login

        # Run group claim synchronization in a sudo block to manage res.groups
        try:
            user = self.sudo().search([("login", "=", login)], limit=1)
            if user:
                user._sync_keycloak_groups(validation)
        except Exception as e:
            _logger.exception("Failed to sync Keycloak groups for user %s: %s", login, e)

        return login

    def _sync_keycloak_groups(self, validation):
        self.ensure_one()

        # Keycloak group list claim is typically under 'groups'
        raw_groups = validation.get("groups") or []
        if not isinstance(raw_groups, list):
            raw_groups = [raw_groups]

        # Clean names (strip leading slashes from Keycloak group paths)
        keycloak_group_names = {
            g.lstrip("/") for g in raw_groups if isinstance(g, str) and g
        }
        _logger.info("Syncing Keycloak groups %s for user %s", keycloak_group_names, self.login)

        ResGroups = self.env["res.groups"]

        # Ensure res.groups exist for all active Keycloak groups
        groups_to_add = []
        for name in keycloak_group_names:
            group = ResGroups.search([("gentian_group_name", "=", name)], limit=1)
            if not group:
                category = self.env.ref("base.module_category_hidden", raise_if_not_found=False)
                group = ResGroups.create({
                    "name": f"Gentian / {name}",
                    "gentian_group_name": name,
                    "category_id": category.id if category else False,
                })
                _logger.info("Created linked Odoo group for Keycloak group: %s", name)
            groups_to_add.append(group)

        # Find all Gentian-linked res.groups that this user is NO LONGER a member of
        groups_to_remove = ResGroups.search([
            ("gentian_group_name", "!=", False),
            ("gentian_group_name", "not in", list(keycloak_group_names)),
        ])

        # Admin privilege mapping
        admin_group = self.env.ref("base.group_system", raise_if_not_found=False)
        access_group = self.env.ref("base.group_erp_manager", raise_if_not_found=False)

        # Safety: Don't modify administrative rights for global root admin/system users
        is_protected_user = self.id in (
            self.env.ref("base.user_admin", raise_if_not_found=False).id or 0,
            self.env.ref("base.user_root", raise_if_not_found=False).id or 0,
        )

        if not is_protected_user and admin_group and access_group:
            if "Tenant Admins" in keycloak_group_names:
                groups_to_add.extend([admin_group, access_group])
            else:
                groups_to_remove |= admin_group
                groups_to_remove |= access_group

        # Apply group assignments using standard ORM command tuple list:
        # (4, id) adds a relation, (3, id) removes a relation.
        updates = []
        for g in groups_to_add:
            if g not in self.groups_id:
                updates.append((4, g.id))
        for g in groups_to_remove:
            if g in self.groups_id:
                updates.append((3, g.id))

        if updates:
            self.write({"groups_id": updates})
            _logger.info("Updated group memberships for user %s: %s", self.login, updates)
