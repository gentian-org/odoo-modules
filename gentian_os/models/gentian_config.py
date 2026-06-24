# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import json
import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)


class GentianConfig(models.AbstractModel):
    """Tenant/module metadata injected by the Gentian app composition."""

    _name = "gentian.config"
    _description = "Gentian platform configuration"

    @api.model
    def _config_path(self):
        return os.environ.get("GENTIAN_CONFIG_PATH", "/etc/gentian/config.json")

    @api.model
    def load(self):
        path = self._config_path()
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            _logger.debug("Gentian config file not present: %s", path)
            return {}
        except json.JSONDecodeError:
            _logger.warning("Invalid Gentian config JSON at %s", path)
            return {}

    @api.model
    def tenant_id(self):
        return self.load().get("tenantId") or os.environ.get("GENTIAN_TENANT_ID", "")

    @api.model
    def module_profiles(self):
        raw = self.load().get("moduleProfiles") or []
        return list(raw)
