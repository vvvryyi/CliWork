const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../app/static/js/app.js"), "utf8");

for (const inClientCard of [true, false]) {
    test(`selected documents appear before saving (client card=${inClientCard})`, () => {
        const listeners = {};
        const status = {};
        let visibleList;
        const compose = { prepend: (element) => { visibleList = element; } };
        const upload = {
            querySelector: () => status,
            closest: () => inClientCard ? compose : null,
            insertAdjacentElement: (position, element) => { visibleList = element; },
        };
        const input = {
            files: [],
            closest: () => upload,
            addEventListener: (name, listener) => { listeners[name] = listener; },
        };
        vm.runInNewContext(script, {
            document: {
                querySelectorAll: (selector) => selector === "[data-file-input]" ? [input] : [],
                querySelector: () => null,
                addEventListener() {},
                createElement: (tag) => ({
                    tag,
                    setAttribute() {},
                    replaceChildren(...children) { this.children = children; },
                }),
            },
            navigator: {},
            window: {},
        });
        assert.equal(visibleList.hidden, true);
        input.files = [{ name: "Договор.pdf" }, { name: "Презентация.pptx" }];
        listeners.change();
        assert.equal(visibleList.hidden, false);
        assert.equal(status.textContent, "Выбрано: 2 · До 20 МБ");
        assert.deepEqual(visibleList.children.map((item) => item.textContent), [
            "📎 Договор.pdf", "📎 Презентация.pptx",
        ]);
        assert.equal(input.files.length, 2);

        // A new selection replaces the previous names and displays markup as text.
        input.files = [{ name: "<img src=x onerror=alert(1)>.pdf" }];
        listeners.change();
        assert.equal(visibleList.children.length, 1);
        assert.equal(visibleList.children[0].tag, "span");
        assert.equal(visibleList.children[0].textContent, "📎 <img src=x onerror=alert(1)>.pdf");

        input.files = [];
        listeners.change();
        assert.equal(visibleList.hidden, true);
        assert.equal(visibleList.children.length, 0);
        assert.equal(status.textContent, "До 20 МБ");
    });
}
