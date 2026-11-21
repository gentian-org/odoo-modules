/** @odoo-module **/
// Copyright 2026 Gentian Authors. License AGPL-3.0.
//
// "Attach from files": opens the platform's file dialog, a window at the
// platform's own address, and attaches what the person picked as a link.
// The dialog and this page speak by messages:
//
//   dialog -> page   {gentianFiles: "ready"}
//   page -> dialog   {gentianFiles: "ask", use: "pick", id}
//   dialog -> page   {gentianFiles: "picked", id, file: {name, id, url}}
//   dialog -> page   {gentianFiles: "cancelled", id}
//
// A message is taken only from the dialog's window and origin.

import {Chatter} from "@mail/chatter/web_portal/chatter";
import {patch} from "@web/core/utils/patch";
import {_t} from "@web/core/l10n/translation";

// The dialog is at files.<the workspace's domain>: the address of this page
// with its first label replaced.
function dialogOrigin() {
    const host = window.location.host;
    const dot = host.indexOf(".");
    return `https://files${dot >= 0 ? host.slice(dot) : "." + host}`;
}

patch(Chatter.prototype, {
    _onAttachFromFiles(event) {
        event.preventDefault();
        event.stopPropagation();
        const origin = dialogOrigin();
        const thread = this.state.thread;
        const ask = Math.random().toString(36).slice(2);
        const dialog = window.open(
            `${origin}/dialog`,
            "gentian-files",
            "popup,width=720,height=560"
        );
        if (!dialog) {
            this.env.services.notification.add(
                _t("The file dialog could not be opened. Allow pop-ups for this page."),
                {type: "warning"}
            );
            return;
        }
        const done = () => {
            window.removeEventListener("message", onMessage);
            clearInterval(watch);
        };
        const onMessage = async (ev) => {
            if (ev.origin !== origin || ev.source !== dialog || !ev.data) {
                return;
            }
            const what = ev.data.gentianFiles;
            if (what === "ready") {
                dialog.postMessage({gentianFiles: "ask", use: "pick", id: ask}, origin);
            } else if (what === "cancelled" && ev.data.id === ask) {
                done();
            } else if (what === "picked" && ev.data.id === ask) {
                done();
                try {
                    await this.orm.call("ir.attachment", "gentian_attach_picked", [
                        thread.model,
                        thread.id,
                        ev.data.file,
                    ]);
                    await this.updateThreadAttachments();
                } catch (error) {
                    this.env.services.notification.add(
                        error?.data?.message || _t("The file could not be attached."),
                        {type: "danger"}
                    );
                }
            }
        };
        window.addEventListener("message", onMessage);
        // A window closed without a word ends the asking too.
        const watch = setInterval(() => {
            if (dialog.closed) {
                done();
            }
        }, 1000);
    },
});
