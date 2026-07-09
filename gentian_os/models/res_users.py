# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """Overrides user sign-in to dynamically map Keycloak group claims."""

    _inherit = "res.users"

    gentian_dynamic_roles = fields.Char(
        string="Gentian Dynamic Roles",
        help="Comma-separated XML IDs of dynamically mapped Odoo roles.",
    )

    @api.model
    def _auth_oauth_rpc(self, endpoint, access_token):
        import requests
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(endpoint, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception:
            _logger.exception("OAuth RPC failed with Authorization header.")
        return super(ResUsers, self)._auth_oauth_rpc(endpoint, access_token)

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
                group = ResGroups.create({
                    "name": f"Gentian / {name}",
                    "gentian_group_name": name,
                })
                _logger.info("Created linked Odoo group for Keycloak group: %s", name)
            groups_to_add.append(group)

        # Find all Gentian-linked res.groups that this user is NO LONGER a member of
        groups_to_remove = ResGroups.search([
            ("gentian_group_name", "!=", False),
            ("gentian_group_name", "not in", list(keycloak_group_names)),
        ])

        # Dynamic in-app roles mapping (tier 3 RBAC)
        raw_roles = validation.get("gentianOdooGroupRoles") or []
        if not isinstance(raw_roles, list):
            raw_roles = [raw_roles]

        mapped_role_xml_ids = []
        for role_entry in raw_roles:
            if not isinstance(role_entry, str):
                continue
            role_entry = role_entry.strip()
            if not role_entry:
                continue
            if role_entry.startswith("[") and role_entry.endswith("]"):
                import json
                try:
                    parsed = json.loads(role_entry)
                    if isinstance(parsed, list):
                        mapped_role_xml_ids.extend([str(r).strip() for r in parsed if r])
                    else:
                        mapped_role_xml_ids.append(str(parsed).strip())
                except Exception:
                    mapped_role_xml_ids.append(role_entry)
            else:
                mapped_role_xml_ids.extend([r.strip() for r in role_entry.split(",") if r.strip()])

        # Previous dynamic roles
        prev_roles_str = self.gentian_dynamic_roles or ""
        prev_roles = [r.strip() for r in prev_roles_str.split(",") if r.strip()]

        # Groups to add: new roles that are not already in user's groups
        for xml_id in mapped_role_xml_ids:
            role_group = self.env.ref(xml_id, raise_if_not_found=False)
            if role_group and role_group._name == "res.groups":
                groups_to_add.append(role_group)
                _logger.info("Mapped dynamic Odoo role group: %s", xml_id)
            else:
                _logger.warning("Mapped dynamic Odoo role XML ID not found or invalid: %s", xml_id)

        # Groups to remove: previous roles that are not in new roles
        for xml_id in prev_roles:
            if xml_id not in mapped_role_xml_ids:
                role_group = self.env.ref(xml_id, raise_if_not_found=False)
                if role_group and role_group._name == "res.groups":
                    groups_to_remove |= role_group
                    _logger.info("Removing stale dynamic mapped Odoo role group: %s", xml_id)

        # Update saved dynamic roles on user
        self.gentian_dynamic_roles = ",".join(mapped_role_xml_ids)

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

        # Promote portal user to internal user so they can access backend app modules (/web)
        portal_group = self.env.ref("base.group_portal", raise_if_not_found=False)
        internal_group = self.env.ref("base.group_user", raise_if_not_found=False)
        if portal_group and internal_group:
            if portal_group in self.group_ids or internal_group not in self.group_ids:
                if portal_group in self.group_ids:
                    groups_to_remove |= portal_group
                if internal_group not in groups_to_add and internal_group not in self.group_ids:
                    groups_to_add.append(internal_group)

        # Apply group assignments using standard ORM command tuple list:
        # (4, id) adds a relation, (3, id) removes a relation.
        updates = []
        for g in groups_to_add:
            if g not in self.group_ids:
                updates.append((4, g.id))
        for g in groups_to_remove:
            if g in self.group_ids:
                updates.append((3, g.id))

        if updates:
            self.write({"group_ids": updates})
            _logger.info("Updated group memberships for user %s: %s", self.login, updates)

    @api.model
    def _register_hook(self):
        super()._register_hook()
        import os
        client_id = os.environ.get("OIDC_CLIENT_ID")
        issuer = os.environ.get("OIDC_ISSUER")
        if not (client_id and issuer):
            return
        issuer = issuer.rstrip('/')
        self = self.sudo()
        Provider = self.env["auth.oauth.provider"]
        provider = Provider.search([("name", "=", "Keycloak")], limit=1)
        validation_endpoint = f"{issuer}/protocol/openid-connect/userinfo"
        if "id.desk.gentian.org" in issuer:
            realm = issuer.split('/')[-1]
            validation_endpoint = f"http://gentian-idp-keycloak-keycloakx-http.platform-kernel.svc.cluster.local:8080/auth/realms/{realm}/protocol/openid-connect/userinfo"
        vals = {
            "name": "Keycloak",
            "client_id": client_id,
            "enabled": True,
            "auth_endpoint": f"{issuer}/protocol/openid-connect/auth",
            "validation_endpoint": validation_endpoint,
            "scope": "openid profile email groups",
            "css_class": "o_auth_oauth_provider_icon",
            "body": "Keycloak",
        }
        if provider:
            needs_update = any(provider[k] != v for k, v in vals.items())
            if needs_update:
                try:
                    with self.env.cr.savepoint():
                        provider.write(vals)
                    self.env.cr.commit()
                    _logger.info("Successfully updated Keycloak OAuth provider validation endpoint to internal URL.")
                except Exception as e:
                    _logger.warning("Failed to update Keycloak provider due to concurrent transaction: %s", e)
        else:
            try:
                with self.env.cr.savepoint():
                    Provider.create(vals)
                self.env.cr.commit()
                _logger.info("Automatically registered Keycloak OAuth provider.")
            except Exception as e:
                _logger.warning("Failed to create Keycloak provider due to concurrent transaction: %s", e)

        # Update default company logo to Gentian logo
        import base64
        from odoo.modules.module import get_module_path
        module_path = get_module_path("gentian_os")
        logo_path = os.path.join(module_path, "static", "src", "img", "logo.png") if module_path else None
        if logo_path and os.path.exists(logo_path):
            try:
                with open(logo_path, "rb") as f:
                    logo_data = base64.b64encode(f.read())
                company = self.env["res.company"].search([], limit=1)
                if company and company.logo != logo_data:
                    with self.env.cr.savepoint():
                        company.write({"logo": logo_data})
                    self.env.cr.commit()
                    _logger.info("Successfully updated company logo to Gentian logo.")
            except Exception as e:
                _logger.warning("Failed to update company logo to Gentian logo: %s", e)
