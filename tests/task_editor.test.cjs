const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../app/static/js/app.js"), "utf8");

function editor(scope, calendar) {
    const listeners = {};
    const classes = { contains: () => false, toggle() {}, remove() {} };
    const input = { value: "Сохранённое дело", style: {} };
    const controls = {
        "[data-task-text]": input,
        "[data-task-check]": { checked: false },
        "[data-task-important]": { checked: false },
    };
    const row = {
        dataset: { taskId: "1", savedText: input.value, savedCompleted: "0", savedImportant: "0", dueDate: "2030-12-05" },
        classList: classes,
        querySelector: (selector) => controls[selector],
        remove() { this.removed = true; },
    };
    const blank = { classList: classes };
    const list = {
        addEventListener: (name, callback) => { listeners[name] = callback; },
        querySelector: () => calendar ? null : blank,
        querySelectorAll: () => row.removed ? [] : [row],
        insertBefore() {},
    };
    const elements = {
        "[data-task-list]": list,
        "[data-task-status]": { classList: classes },
        "[data-task-csrf]": { value: "test-csrf" },
    };
    return {
        row, input, listeners,
        dataset: { taskScope: scope, selectedDate: "2030-12-05", saveUrl: "/tasks/save", allowCreate: calendar ? "0" : "1" },
        querySelector: (selector) => elements[selector],
        addEventListener() {},
    };
}

for (const calendar of [false, true]) {
    test(`deletion requires confirmation for both scopes (calendar=${calendar})`, async () => {
        const editors = [editor("daily", calendar), editor("general", calendar)];
        const requests = [];
        let accepted = false;
        let confirmations = 0;
        vm.runInNewContext(script, {
            document: {
                querySelectorAll: (selector) => selector === "[data-task-editor]" ? editors : [],
                querySelector: () => null,
                addEventListener() {},
            },
            navigator: {},
            window: { confirm: () => { confirmations++; return accepted; } },
            FormData,
            fetch: async (url, options) => {
                requests.push(Object.fromEntries(options.body.entries()));
                return { ok: true, json: async () => ({ deleted: true }) };
            },
        });

        for (const item of editors) {
            const button = { closest: () => item.row };
            const event = { target: { closest: () => button } };
            accepted = false;
            item.listeners.click(event);
            await new Promise(setImmediate);
            assert.equal(item.row.removed, undefined);
            assert.equal(requests.length, editors.indexOf(item));
            assert.equal(item.input.value, "Сохранённое дело");

            accepted = true;
            item.listeners.click(event);
            await new Promise(setImmediate);
            assert.equal(item.row.removed, true);
            assert.deepEqual(requests.at(-1), {
                csrf_token: "test-csrf", task_id: "1", task_scope: item.dataset.taskScope, delete: "1",
            });
        }
        assert.equal(confirmations, 4);
        assert.equal(requests.length, 2);
    });
}

for (const scope of ["daily", "general"]) {
    test(`calendar completion stays at the bottom through undo and redo (${scope})`, async () => {
        const item = editor(scope, true);
        item.dataset.hideCompleted = "0";
        const row = item.row;
        row.dataset.savedText = item.input.value = "Альфа";
        const classes = new Set();
        row.classList.toggle = (name, enabled) => enabled ? classes.add(name) : classes.delete(name);
        const link = { classList: { toggle() {} } };
        const controls = {
            "[data-task-text]": item.input,
            "[data-task-check]": { checked: false, closest: () => row },
            "[data-task-important]": { checked: false },
            "[data-task-calendar]": link,
        };
        row.querySelector = (selector) => controls[selector];
        const pending = { dataset: { taskId: "2", savedText: "Ясень", savedCompleted: "0" } };
        const rows = [row, pending];
        const list = item.querySelector("[data-task-list]");
        list.querySelectorAll = () => rows.filter((entry) => !entry.removed);
        list.querySelector = (selector) => selector.includes('data-task-id="1"') ? row : null;
        list.insertBefore = (entry, anchor) => {
            rows.splice(rows.indexOf(entry), 1);
            const index = anchor ? rows.indexOf(anchor) : rows.length;
            rows.splice(index, 0, entry);
        };
        const historyListeners = {};
        item.addEventListener = (name, callback) => { historyListeners[name] = callback; };
        const requests = [];
        vm.runInNewContext(script, {
            document: {
                querySelectorAll: (selector) => selector === "[data-task-editor]" ? [item] : [],
                querySelector: () => null,
                addEventListener() {},
            },
            navigator: {},
            FormData,
            fetch: async (url, options) => {
                const payload = Object.fromEntries(options.body.entries());
                requests.push(payload);
                return { ok: true, json: async () => ({
                    task_id: 1, text: payload.text, due_date: payload.due_date,
                    comment: "", completed: payload.completed === "1",
                    important: false, calendar_url: "/calendar/events/1/edit", has_comment: false,
                }) };
            },
        });

        controls["[data-task-check]"].checked = true;
        item.listeners.change({ target: { closest: () => controls["[data-task-check]"] } });
        await new Promise(setImmediate);
        assert.equal(requests.at(-1).task_scope, scope);
        assert.equal(requests.at(-1).completed, "1");
        assert.equal(row.removed, undefined);
        assert.equal(classes.has("is-completed"), true);
        assert.deepEqual(rows, [pending, row]);

        historyListeners.keydown({ key: "z", ctrlKey: true, preventDefault() {} });
        await new Promise(setImmediate);
        assert.equal(requests.at(-1).completed, "0");
        assert.equal(controls["[data-task-check]"].checked, false);
        assert.deepEqual(rows, [row, pending]);

        historyListeners.keydown({ key: "y", ctrlKey: true, preventDefault() {} });
        await new Promise(setImmediate);
        assert.equal(requests.at(-1).completed, "1");
        assert.equal(row.removed, undefined);
        assert.equal(controls["[data-task-check]"].checked, true);
        assert.deepEqual(rows, [pending, row]);

        controls["[data-task-check]"].checked = false;
        item.listeners.change({ target: { closest: () => controls["[data-task-check]"] } });
        await new Promise(setImmediate);
        assert.equal(classes.has("is-completed"), false);
        assert.deepEqual(rows, [row, pending]);
    });
}
