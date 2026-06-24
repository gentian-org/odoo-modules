/** @odoo-module **/

import { WebClient } from "@web/webclient/webclient";
import { patch } from "@web/core/utils/patch";

function gentianEmbedActive() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("gentian_embed") === "1") {
        return true;
    }
    try {
        return window.parent !== window && window.parent.location.origin !== window.location.origin;
    } catch (_e) {
        return false;
    }
}

patch(WebClient.prototype, {
  setup() {
    super.setup(...arguments);
    if (gentianEmbedActive()) {
      document.body.classList.add("o_gentian_embed");
    }
  },
});
