const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../app/static/js/app.js"), "utf8");

for (const outcome of ["success", "http-error", "network-error"]) {
    test(`contact importance saves and restores state on failure: ${outcome}`, async () => {
        const listeners = {};
        const checkbox = {
            checked: false,
            disabled: false,
            addEventListener: (name, callback) => { listeners[name] = callback; },
        };
        const classes = new Set();
        const classList = {
            toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
            add: (name) => classes.add(name),
            remove: (name) => classes.delete(name),
        };
        const status = { textContent: "", classList };
        const form = {
            action: "/clients/contacts-today/events/1/importance",
            querySelector: () => checkbox,
            closest: () => ({ classList }),
            addEventListener() {},
        };
        const requests = [];
        vm.runInNewContext(script, {
            document: {
                querySelectorAll: (selector) => selector === "[data-contact-importance]" ? [form] : [],
                querySelector: (selector) => selector === "[data-contact-importance-status]" ? status : null,
                addEventListener() {},
            },
            navigator: {},
            FormData: class extends FormData {
                constructor() { super(); this.set("csrf_token", "test-csrf"); }
            },
            fetch: async (url, options) => {
                assert.equal(checkbox.disabled, true);
                requests.push({ url, ...Object.fromEntries(options.body) });
                if (outcome === "network-error") throw new Error("Нет связи");
                return {
                    ok: outcome === "success",
                    json: async () => ({ important: options.body.get("important") === "1" }),
                };
            },
        });
        checkbox.checked = true;
        await listeners.change();
        assert.equal(checkbox.disabled, false);
        assert.equal(checkbox.checked, outcome === "success");
        assert.equal(classes.has("event-important"), outcome === "success");
        assert.equal(classes.has("is-error"), outcome !== "success");
        assert.deepEqual(requests[0], {
            url: form.action, csrf_token: "test-csrf", important: "1",
        });
        if (outcome === "success") {
            checkbox.checked = false;
            await listeners.change();
            assert.equal(requests[1].important, "0");
            assert.equal(classes.has("event-important"), false);
        }
    });
}
