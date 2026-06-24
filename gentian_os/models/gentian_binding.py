# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

import json
import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)


class GentianBinding(models.AbstractModel):
    """Reads IntegrationBinding credentials synced by Gentian ESO."""

    _name = "gentian.binding"
    _description = "Gentian IntegrationBinding reader"

    @api.model
    def _binding_secret_path(self):
        return os.environ.get("GENTIAN_BINDINGS_SECRET", "/etc/gentian/bindings.json")

    @api.model
    def load_bindings(self):
        path = self._binding_secret_path()
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            _logger.debug("Gentian bindings file not present: %s", path)
            return {}
        except json.JSONDecodeError:
            _logger.warning("Invalid Gentian bindings JSON at %s", path)
            return {}
