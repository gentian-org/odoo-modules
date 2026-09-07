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
 * Read from ?gentian_app= on the tile URL. An override for the rare action the
 * rules below cannot place; most tiles send nothing and do not need to.
 */
function gentianAppHint() {
    return new URLSearchParams(window.location.search).get("gentian_app") || null;
}

/**
 * The module an action-by-xmlid URL names, e.g. "account" for
 * /odoo/action-account.open_account_journal_dashboard_kanban.
 *
 * Null for the other URL shapes -- /odoo/<path>, /odoo/action-<numeric id> --
 * which carry no module to read.
 */
function gentianActionModule() {
    const part = window.location.pathname.split("/").filter(Boolean).pop() || "";
    if (!part.startsWith("action-")) {
        return null;
    }
    const xmlid = part.slice("action-".length);
    const dot = xmlid.indexOf(".");
    return dot > 0 ? xmlid.slice(0, dot) : null;
}

/**
 * Which app owns what is on screen, decided from the tile's own URL.
 *
 * WebClient.loadRouterState answers this by looking for an ir.ui.menu that
 * points at the action, and when it finds none it falls back to
 * sessionStorage's "menu_id" -- the last app visited. That fallback is sound
 * for stock Odoo, where a browser session holds one web client. It is wrong
 * here: every Gentian tile is a separate same-origin iframe in one tab, and
 * same-origin iframes share one sessionStorage, so "the last app visited"
 * means "whichever tile the user opened most recently, in any window". The top
 * bar of one app then shows another app's menu sections.
 *
 * Finding no menu is not the exception it sounds like. Odoo sends the client
 * only the menus that user may see, so it depends on who is looking:
 * account.open_account_journal_dashboard_kanban is reached from Invoicing /
 * Dashboard, and for a user without that menu the action arrives owned by
 * nothing at all. crm.crm_lead_action_pipeline has no menu for anyone.
 *
 * Deciding from the URL instead makes each tile's result depend only on that
 * tile -- the same every time, for every user, whatever else is open.
 *
 * Returns null when nothing places the action, which leaves Odoo's own choice
 * alone rather than replacing it with a worse guess.
 */
function resolveOwningApp(menuService) {
    const menus = menuService.getAll();
    const apps = menus.filter((m) => m.appID && m.appID === m.id && m.xmlid);

    // 1. The tile said so outright. Nothing outranks that -- Gentian writes
    //    the URL. Only needed where the module below cannot be read.
    const hint = gentianAppHint();
    if (hint) {
        const hinted = menus.find((m) => m.xmlid === hint);
        if (hinted && hinted.appID) {
            return hinted.appID;
        }
    }

    // 2. The module that defines the action also defines the app's root menu:
    //    account.open_account_journal_dashboard_kanban and account.menu_finance,
    //    hr.open_view_employee_list_my and hr.menu_hr_root. Both halves are
    //    already on hand -- the xmlid is in the URL, and load_web_menus sends
    //    each menu's xmlid -- so no declaration and no lookup table is needed,
    //    and a module added later is covered without touching anything here.
    const module = gentianActionModule();
    if (module) {
        const app = apps.find((m) => m.xmlid.startsWith(module + "."));
        if (app) {
            return app.appID;
        }
    }

    return null;
}

patch(WebClient.prototype, {
    setup() {
        super.setup(...arguments);
        if (gentianEmbedActive()) {
            document.body.classList.add("o_gentian_embed");
        }
    },

    /**
     * Pin the app the top bar belongs to, so it cannot be decided by another
     * iframe's sessionStorage. See resolveOwningApp.
     *
     * Applied before the original call as well as after: it reads only the URL
     * and the menu list, both available immediately, so running it first spares
     * the tile the flash of rendering another app's menu sections and then
     * correcting itself. Running it again afterwards makes sure nothing the
     * original did -- including its own sessionStorage fallback -- gets the
     * last word.
     */
    async loadRouterState() {
        const pin = () => {
            const appID = resolveOwningApp(this.menuService);
            if (appID) {
                this.menuService.setCurrentMenu(appID);
            }
        };
        if (gentianEmbedActive()) {
            pin();
        }
        const result = await super.loadRouterState(...arguments);
        if (gentianEmbedActive()) {
            pin();
        }
        return result;
    },
});
