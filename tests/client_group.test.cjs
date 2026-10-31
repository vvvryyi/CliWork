const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

for (const outcome of ['success', 'http-error', 'network-error']) {
    test(`group selection saves or reports the error: ${outcome}`, async () => {
        const listeners = {};
        const field = { value: 'd', dataset: { savedGroup: 'none' }, disabled: false,
            addEventListener: (name, listener) => { listeners[name] = listener; } };
        const status = { hidden: true, textContent: '' };
        const form = { action: '/clients/1/group', querySelector: () => field, addEventListener() {} };
        const navigation = [];
        vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/js/app.js'), 'utf8'), {
            document: { querySelectorAll: (selector) => selector === '[data-client-group]' ? [form] : [],
                querySelector: (selector) => selector === '[data-client-group-status]' ? status : null, addEventListener() {} },
            window: { location: { assign: (url) => navigation.push(url) } }, navigator: {},
            FormData: class extends FormData { constructor() { super(); this.set('group', field.value); this.set('csrf_token', 'token'); } },
            fetch: async (url, options) => {
                assert.equal(url, form.action);
                assert.equal(options.body.get('group'), 'd');
                assert.equal(options.body.get('csrf_token'), 'token');
                assert.equal(field.disabled, true);
                if (outcome === 'network-error') throw new Error('offline');
                return { ok: outcome === 'success', json: async () => ({ group: 'd', url: '/clients/1' }) };
            },
        });
        await listeners.change();
        assert.equal(field.disabled, false);
        assert.equal(field.value, outcome === 'success' ? 'd' : 'none');
        assert.equal(navigation.length, outcome === 'success' ? 1 : 0);
        if (outcome !== 'success') assert.match(status.textContent, /Не удалось/);
    });
}
