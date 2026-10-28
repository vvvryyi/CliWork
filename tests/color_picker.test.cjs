const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('swatches update the submitted field and preview without a visible color name', () => {
    const listeners = {};
    const labels = { '': 'Метки', red: 'Красный', gray: 'Серый', unlabeled: 'Без метки' };
    const preview = { dataset: {} };
    const placeholder = {};
    const summary = { dataset: {}, getAttribute: () => 'Метки', focus() {} };
    const buttons = Object.keys(labels).map((value) => ({
        dataset: { colorOption: value },
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, listener) { this[name] = listener; },
    }));
    const field = {
        value: '',
        get selectedOptions() { return [{ textContent: labels[this.value] }]; },
        closest: () => picker,
        addEventListener(name, listener) { (listeners[name] ||= []).push(listener); },
        dispatchEvent(event) { for (const listener of listeners[event.type] || []) listener(); },
    };
    const picker = {
        open: true,
        querySelector(selector) { return ({
            '[data-palette-field]': field, '[data-color-preview]': preview,
            '[data-color-placeholder]': placeholder, summary,
        })[selector]; },
        querySelectorAll: () => buttons,
        addEventListener() {},
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/js/app.js'), 'utf8'), {
        Event,
        document: {
            querySelectorAll: (selector) => selector === '[data-color-picker]' ? [picker] : [],
            querySelector: () => null, addEventListener() {},
        },
        window: {}, navigator: {},
    });
    assert.equal(placeholder.textContent, 'Метки');
    assert.equal(preview.hidden, true);
    buttons.find((button) => button.dataset.colorOption === 'red').click();
    assert.equal(field.value, 'red');
    assert.equal(preview.dataset.color, 'red');
    assert.equal(placeholder.hidden, true);
    assert.equal(picker.open, false);
    assert.equal(buttons.find((button) => button.dataset.colorOption === 'red').attributes['aria-pressed'], 'true');
    buttons.find((button) => button.dataset.colorOption === 'gray').click();
    assert.equal(field.value, 'gray');
    buttons.find((button) => button.dataset.colorOption === '').click();
    assert.equal(field.value, '');
    assert.equal(preview.hidden, true);
    assert.equal(placeholder.hidden, false);
});
