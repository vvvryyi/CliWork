const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../app/static/js/app.js"), "utf8");
const divider = "\n\u2063";

function element() {
    return {
        dataset: {}, style: {}, listeners: {}, children: [],
        addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); },
        emit(name, event = {}) { for (const listener of this.listeners[name] || []) listener(event); },
        append(child) { this.children.push(child); },
        replaceChildren(...children) { this.children = children; },
        getBoundingClientRect() { return { top: 0 }; },
        set textContent(text) { this.firstChild = { textContent: text }; },
    };
}

function historyEditor(colors, sections, ids = "1,2") {
    const fields = colors.map((value) => ({ value }));
    const recordSelect = Object.assign(element(), { value: String(fields.length - 1) });
    const colorSelect = Object.assign(element(), { value: "" });
    const controls = {
        querySelector: (selector) => selector === "[data-history-record]" ? recordSelect : colorSelect,
        querySelectorAll: () => fields,
    };
    const dots = element();
    const parent = element();
    parent.querySelector = () => dots;
    const editor = Object.assign(element(), {
        value: sections.join(divider), selectionStart: 0, scrollTop: 0, clientWidth: 500,
        parentElement: parent,
        form: {
            elements: { namedItem: () => ({ value: ids }) },
            querySelector: (selector) => selector === "[data-history-colors]" ? controls : null,
        },
        focus() {},
        setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
    });
    return { editor, fields, recordSelect, colorSelect, dots };
}

function initialize(editors) {
    vm.runInNewContext(script, {
        document: {
            querySelectorAll: (selector) => selector === "textarea[data-history-editor]" ? editors.map((item) => item.editor) : [],
            querySelector: () => null,
            addEventListener() {},
            createElement: element,
            createRange: () => ({
                setStart(content, offset) { this.content = content; this.offset = offset; },
                setEnd() {},
                getBoundingClientRect() {
                    return { top: this.content.textContent.slice(0, this.offset).split("\n").length * 24, height: 20 };
                },
            }),
        },
        window: { getComputedStyle: () => ({}), addEventListener() {}, location: { hash: "" } },
        navigator: {},
    });
}

test("color changes affect only the selected comment in its own editor", () => {
    const general = historyEditor(["red", "gray", ""], ["250101 Первый", "Без даты", "261028 "]);
    const d = historyEditor(["orange", ""], ["250102 Документы", "261028 "], "3");
    initialize([general, d]);
    assert.equal(general.colorSelect.value, "");
    assert.deepEqual(general.dots.children.map((dot) => dot.dataset.color), ["red", "gray", ""]);
    general.recordSelect.value = "1";
    general.recordSelect.emit("change");
    assert.equal(general.colorSelect.value, "gray");
    assert.equal(general.editor.value.slice(general.editor.selectionStart, general.editor.selectionEnd), "Без даты");
    general.colorSelect.value = "lemon";
    general.colorSelect.emit("change");
    assert.deepEqual(general.fields.map((field) => field.value), ["red", "lemon", ""]);
    assert.deepEqual(general.dots.children.map((dot) => dot.dataset.color), ["red", "lemon", ""]);
    assert.deepEqual(d.fields.map((field) => field.value), ["orange", ""]);
    general.recordSelect.value = "2";
    general.recordSelect.emit("change");
    general.colorSelect.value = "light_green";
    general.colorSelect.emit("change");
    assert.equal(general.fields[2].value, "light_green");
    // Removing a label restores the unmarked state without touching neighboring comments.
    general.recordSelect.value = "0";
    general.recordSelect.emit("change");
    general.colorSelect.value = "";
    general.colorSelect.emit("change");
    assert.deepEqual(general.fields.map((field) => field.value), ["", "lemon", "light_green"]);
});

test("caret selection and scrolling keep labels attached to the right multiline record", () => {
    const history = historyEditor(["yellow", "orange", "red"], ["250101 Первая\nВторая строка 301201", "Без даты", "261028 "]);
    initialize([history]);
    const index = history.editor.value.indexOf("Без даты");
    history.editor.setSelectionRange(index, index);
    history.editor.emit("click");
    assert.equal(history.recordSelect.value, "1");
    assert.equal(history.colorSelect.dataset.color, "orange");
    history.editor.scrollTop = 48;
    history.editor.emit("scroll");
    assert.deepEqual(history.dots.children.map((dot) => dot.dataset.color), ["yellow", "yellow", "orange", "red"]);
    assert.equal(history.dots.children[0].style.top, "-14px");
    // Native deletions are accepted while colors retain original record ownership.
    const original = history.editor.value;
    history.editor.emit("beforeinput");
    history.editor.value = original.replace(divider, "\n");
    history.editor.emit("input");
    assert.equal(history.editor.value, original.replace(divider, "\n"));
    assert.deepEqual(history.fields.map((field) => field.value), ["yellow", "orange", "red"]);
});


test("Enter keeps a native newline in both contact history editors", () => {
    for (const history of [historyEditor(["red", ""], ["261029 Старая запись", "261029 "], "1"), historyEditor([""], ["261029 "], "")]) {
        initialize([history]);
        let stopped = false;
        let prevented = false;
        history.editor.emit("keydown", { key: "Enter", stopPropagation() { stopped = true; }, preventDefault() { prevented = true; } });
        assert.equal(stopped, true);
        assert.equal(prevented, false);
        history.editor.emit("beforeinput");
        history.editor.value += "Первая строка\nВторая строка 301201";
        const multiline = history.editor.value;
        history.editor.emit("input");
        assert.equal(history.editor.value, multiline);
    }
});

test("selection deletion keeps original record identities and the new entry slot", () => {
    const history = historyEditor(["red", "orange", ""], ["261030 Первый", "261030 Второй", "261105 "]);
    initialize([history]);
    const original = history.editor.value;
    const end = original.indexOf("261105");
    history.editor.setSelectionRange(0, end);
    history.editor.emit("beforeinput");
    history.editor.value = original.slice(end);
    history.editor.emit("input");
    const field = history.editor.parentElement.children.find((child) => child.name === "history_sections");
    assert.deepEqual(JSON.parse(field.value), ["", "", "261105 "]);
    history.editor.setSelectionRange(history.editor.value.length, history.editor.value.length);
    history.editor.emit("beforeinput");
    history.editor.value += "Новый звонок 270831";
    history.editor.emit("input");
    assert.deepEqual(JSON.parse(field.value), ["", "", "261105 Новый звонок 270831"]);
    assert.equal(history.recordSelect.value, "2");
});

test("replacing all history puts new text in a new record", () => {
    const history = historyEditor(["red", ""], ["261030 Старый звонок", "261105 "], "1");
    initialize([history]);
    history.editor.setSelectionRange(0, history.editor.value.length);
    history.editor.emit("beforeinput");
    history.editor.value = "261105 Новый звонок 270831";
    history.editor.emit("input");
    const field = history.editor.parentElement.children.find((child) => child.name === "history_sections");
    assert.deepEqual(JSON.parse(field.value), ["", "261105 Новый звонок 270831"]);
});


test("new text after a blank date slot belongs to the new record", () => {
    const history = historyEditor(["red", ""], ["261110 Старая запись", ""], "1");
    initialize([history]);
    history.editor.setSelectionRange(history.editor.value.length, history.editor.value.length);
    history.editor.emit("beforeinput");
    history.editor.value += "Новый комментарий 301201";
    history.editor.emit("input");
    const field = history.editor.parentElement.children.find((item) => item.name === "history_sections");
    const sections = JSON.parse(field.value);
    assert.equal(sections[1], "Новый комментарий 301201");
    assert.ok(sections[0].startsWith("261110 Старая запись"));
});
