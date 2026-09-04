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

/**
 * The app a Gentian tile declares it belongs to, as an ir.ui.menu xml id.
 *
 * Read from ?gentian_app= on the tile URL, which the portal builds from the
 * profile's linkSuffix. Absent on tiles that do not need it.
 */
function gentianAppHint() {
    return new URLSearchParams(window.location.search).get("gentian_app") || null;
}

patch(WebClient.prototype, {
    setup() {
        super.setup(...arguments);
        if (gentianEmbedActive()) {
            document.body.classList.add("o_gentian_embed");
        }
    },

    /**
     * Honour ?gentian_app= when the tile supplies it.
     *
     * WebClient.loadRouterState decides which app the top bar belongs to by
     * matching the action against ir.ui.menu -- first by the action in the
     * URL, then, once the action has loaded, by its resolved id. When neither
     * finds an owner it falls back to sessionStorage's "menu_id", the last app
     * visited. That fallback is sound for stock Odoo, where a browser session
     * holds one web client. It is wrong here: every Gentian tile is a separate
     * same-origin iframe in one tab, and same-origin iframes share one
     * sessionStorage, so "the last app visited" means "whichever tile the user
     * opened most recently", in any window.
     *
     * crm.crm_lead_action_pipeline is such an action -- no menu points at it
     * and it has no path -- so CRM's own top bar showed the sections of
     * whatever tile preceded it. Pointing the tile at crm.action_your_pipeline
     * instead does not help: that is a server action, and
     * ActionService._executeServerAction runs it and recurses into whatever it
     * returns, which is this same menu-less action, so the wrapper's own menu
     * and path are discarded before anything reads them.
     *
     * Rather than teach the web client to infer an owner Odoo's data genuinely
     * does not record, the tile states it. Gentian knows which app it is
     * launching -- it writes the URL -- so the hint is authoritative and needs
     * no heuristic.
     *
     * Set before and after the original: before so the first paint is already
     * right, after so nothing the original does can leave a different app
     * selected. Both are no-ops when the hint is absent or names a menu this
     * user cannot see, which leaves stock behaviour untouched for every tile
     * that does not send one.
     */
    async loadRouterState() {
        const applyHint = () => {
            const hint = gentianAppHint();
            if (!hint) {
                return;
            }
            const menu = this.menuService.getAll().find((m) => m.xmlid === hint);
            if (menu && menu.appID) {
                this.menuService.setCurrentMenu(menu.appID);
            }
        };
        applyHint();
        const result = await super.loadRouterState(...arguments);
        applyHint();
        return result;
    },
});
