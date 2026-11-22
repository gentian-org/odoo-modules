# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import hashlib
import logging

from odoo import api, models
from odoo.http import request

_logger = logging.getLogger(__name__)

# The session key naming the module set a session's rights were synced for.
# Odoo learns a person's groups only when they sign in, so a session that
# outlived an addon install would never get that addon's roles: the tile opens
# an app the session may not use, and Odoo shows its first app instead.
# ir_http compares this with the current set and sends a stale session through
# the zero-click sign-in again.
SYNCED_MODULES_KEY = "gentian_synced_modules"

# The claim the platform writes a person's roles to, as group XML ids. The
# claim of the same name followed by "_mapped" lists every group it decides.
ROLES_CLAIM = "gentian_roles"


def _xml_ids(claim):
    """A claim as a list of group XML ids, or None when the token has none."""
    if claim is None:
        return None
    if isinstance(claim, str):
        claim = [claim]
    if not isinstance(claim, list):
        return None
    return [c.strip() for c in claim if isinstance(c, str) and c.strip()]


class ResUsers(models.Model):
    """Sets a person's groups at sign-in to the roles the platform says they hold."""

    _inherit = "res.users"

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

        # As the superuser: a person does not hold the right to change groups.
        try:
            user = self.sudo().search([("login", "=", login)], limit=1)
            if user:
                user._sync_platform_roles(validation)
        except Exception as e:
            _logger.exception("Failed to set the platform's roles for user %s: %s", login, e)

        # Stamped whether or not the sync succeeded: the session is as current
        # as a sign-in can make it, and sending it round again would not help.
        if request:
            request.session[SYNCED_MODULES_KEY] = self._gentian_modules_stamp()

        return login

    @api.model
    def _gentian_modules_stamp(self):
        """A digest of the installed modules. The roles a sign-in grants name
        modules' groups, so a different set is what makes a session stale."""
        self.env["ir.module.module"].flush_model(["name", "state"])
        self.env.cr.execute("SELECT name FROM ir_module_module WHERE state = 'installed' ORDER BY name")
        names = ",".join(row[0] for row in self.env.cr.fetchall())
        return hashlib.sha256(names.encode()).hexdigest()[:16]

    def _sync_platform_roles(self, validation):
        """Set the person's groups to the roles the platform says they hold.

        The sign-in token carries two lists of group XML ids. ``gentian_roles``
        are the groups of the roles the person holds on Odoo and on the
        modules installed in it. ``gentian_roles_mapped`` are all the groups
        the platform decides. The person is given the first and loses the rest
        of the second. A group in neither is Odoo's own to keep: what an
        administrator gave inside Odoo stays.

        A token without the second list comes from a platform that does not
        say, and changes nothing.
        """
        self.ensure_one()
        mapped = _xml_ids(validation.get(ROLES_CLAIM + "_mapped"))
        if mapped is None:
            _logger.info("No platform roles in the sign-in of %s: groups left as they are", self.login)
            return
        held = _xml_ids(validation.get(ROLES_CLAIM)) or []
        # Only a name the platform decides is taken from the first list, so a
        # token cannot give a group the platform never mapped.
        held = [xml_id for xml_id in held if xml_id in mapped]

        # The two accounts Odoo ships with are not the platform's to demote.
        protected = self.id in (
            self.env.ref("base.user_admin", raise_if_not_found=False).id or 0,
            self.env.ref("base.user_root", raise_if_not_found=False).id or 0,
        )

        ResGroups = self.env["res.groups"]
        to_add = ResGroups
        to_remove = ResGroups
        for xml_id in mapped:
            group = self.env.ref(xml_id, raise_if_not_found=False)
            if not group or group._name != "res.groups":
                # A module that is not installed: its groups are not there.
                continue
            if xml_id in held:
                to_add |= group
            elif not protected:
                to_remove |= group

        # A person with a role is an internal user, and Odoo allows one user
        # type: the portal group goes when the internal one comes.
        internal = self.env.ref("base.group_user", raise_if_not_found=False)
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        if internal and portal and internal in to_add and portal in self.group_ids:
            to_remove |= portal

        # A group named by both sides is an add: implied groups make that
        # possible, and what the person holds now decides.
        updates = [(4, g.id) for g in to_add if g not in self.group_ids]
        updates += [(3, g.id) for g in to_remove - to_add if g in self.group_ids]
        if updates:
            self.write({"group_ids": updates})
            _logger.info("Updated groups of %s from the platform's roles: %s", self.login, updates)

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
        # Where the token is VALIDATED, as opposed to where the browser is
        # sent. auth_oauth calls the userinfo endpoint from inside the pod, and
        # the public issuer is the kernel gateway -- so that leg leaves the
        # cluster and comes back in. A tenant app is not allowed out to the
        # gateway, so the call times out and Odoo answers oauth_error=2, which
        # the browser shows as "access denied" on a perfectly good token.
        #
        # This used to be keyed on `"id.desk.gentian.org" in issuer` -- one
        # cluster's hostname, hardcoded -- so every other cluster silently took
        # the public path and could not sign in. OIDC_INTERNAL_ISSUER carries
        # the in-cluster base instead, set by the chart, and the platform is
        # what knows its own Keycloak Service name rather than this module.
        #
        # Unset falls back to the public issuer, which is both the old
        # behaviour and the right answer anywhere the two are the same.
        internal = (os.environ.get("OIDC_INTERNAL_ISSUER") or "").strip().rstrip('/')
        validation_base = internal or issuer
        validation_endpoint = f"{validation_base}/protocol/openid-connect/userinfo"
        vals = {
            "name": "Keycloak",
            "client_id": client_id,
            "enabled": True,
            "auth_endpoint": f"{issuer}/protocol/openid-connect/auth",
            "validation_endpoint": validation_endpoint,
            "scope": "openid profile email",
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

        # Ensure default POS journal exists if point_of_sale is installed
        if "pos.config" in self.env:
            try:
                with self.env.cr.savepoint():
                    self.env["account.journal"].sudo()._ensure_company_account_journal()
                self.env.cr.commit()
                _logger.info("Successfully pre-created default POS journals.")
            except Exception as e:
                _logger.warning("Failed to pre-create default POS journals: %s", e)


