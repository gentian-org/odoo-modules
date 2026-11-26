/** @odoo-module **/

import { EditorOverlay } from "@html_editor/core/overlay";
import { ColorPicker } from "@web/core/color_picker/color_picker";
import { patch } from "@web/core/utils/patch";

/**
 * Odoo's HTML editor inside a Gentian tile.
 *
 * A tile is a frame of the desktop, which is on another origin. Two parts of
 * the editor read the top window's document without guarding the read, and in
 * a tile the browser refuses it with a SecurityError that takes the editor's
 * popup down ("Oops! Something went wrong"). Opened directly, Odoo is its own
 * top window and none of this applies: every patch below steps aside when the
 * top document can be read.
 */
function topDocumentReadable() {
    try {
        return Boolean(window.top.document);
    } catch {
        return false;
    }
}

/**
 * EditorOverlay holds every popup of the editor: the formatting toolbar, the
 * link popover, the command menu. Its setup reads
 * `editable.ownerDocument.defaultView.top.document`, to fall back to the top
 * document's root when the field has no scroll container of its own.
 *
 * In a tile, Odoo's own document is the topmost one it may read, so that is
 * the one the setup is given: for the duration of Odoo's own setup the
 * editable's document answers `defaultView` with a stand-in whose `top` is
 * this window. Odoo's code runs unchanged; nothing of it is copied here.
 */
patch(EditorOverlay.prototype, {
    setup() {
        if (topDocumentReadable()) {
            return super.setup(...arguments);
        }
        const doc = this.props.editable.ownerDocument;
        const view = doc.defaultView;
        const viewAsTop = new Proxy(view, {
            get(target, key) {
                if (key === "top") {
                    return target;
                }
                const value = Reflect.get(target, key);
                return typeof value === "function" ? value.bind(target) : value;
            },
        });
        Object.defineProperty(doc, "defaultView", { configurable: true, value: viewAsTop });
        try {
            return super.setup(...arguments);
        } finally {
            // Back to Document.prototype's own defaultView.
            delete doc.defaultView;
        }
    },
});

/**
 * The color picker's tabs that cannot start in a tile. Both show Odoo's
 * CustomColorPicker -- "custom" directly, "gradient" in its gradient editor --
 * whose setup reads `window.top.document` itself, which no stand-in can
 * intercept. In a tile the picker offers the palette ("solid") only.
 */
const TABS_NEEDING_TOP_DOCUMENT = new Set(["custom", "gradient"]);

patch(ColorPicker.prototype, {
    setup() {
        super.setup(...arguments);
        if (topDocumentReadable()) {
            return;
        }
        const tabs = this.tabs.filter((tab) => !TABS_NEEDING_TOP_DOCUMENT.has(tab.id));
        // A picker offered only those tabs (some website-builder options) has
        // nothing left to show; it stays as Odoo built it.
        if (!tabs.length) {
            return;
        }
        this.tabs = tabs;
        // The editor opens the picker on "custom" when the text's color is not
        // in the palette, and on "gradient" for a gradient; it opens on the
        // first tab that remains instead.
        if (!tabs.some((tab) => tab.id === this.state.activeTab)) {
            this.state.activeTab = tabs[0].id;
        }
    },
});
