const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../static/app.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function notebook() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, hidden: false, listeners: {},
      classList: { toggle() {} }, setAttribute() {}, removeAttribute() {},
      replaceChildren() {}, append() {}, focus() {},
      addEventListener(type, callback) { this.listeners[type] = callback; },
    });
    return elements.get(id);
  };
  const writes = [];
  const response = data => ({ status: 200, ok: true, headers: new Headers(), json: async () => data });
  const context = vm.createContext({
    document: { getElementById: element, createElement: () => element(Symbol()) },
    window: { confirm: () => true },
    structuredClone, URLSearchParams, DOMException, setTimeout, clearTimeout,
    fetch: async (path, options) => {
      if (path === '/api/refresh') return response({ access_token: 'token', user: { id: 'alice' } });
      if (path === '/api/me') return response({ id: 'alice' });
      if (options.method === 'POST' || options.method === 'PATCH') {
        return new Promise(resolve => writes.push({ path, options, resolve }));
      }
      return response({ items: [], total: 0 });
    },
  });
  vm.runInContext(source, context);
  await tick();
  return {
    element, writes,
    submit() { element('note-form').listeners.submit({ preventDefault() {} }); },
    async finishSave(index) {
      const write = writes[index];
      write.resolve(response({
        ...JSON.parse(write.options.body), id: 'saved-note',
        updated_at: '2026-01-01T00:00:00Z',
      }));
      await tick();
    },
  };
}

for (const editingExisting of [false, true]) {
  test(`a delayed ${editingExisting ? 'update' : 'create'} preserves newer edits and the saved identity`, async () => {
    const ui = await notebook();
    if (editingExisting) {
      ui.element('note-title').value = 'Original';
      ui.submit();
      await ui.finishSave(0);
    }
    const index = ui.writes.length;
    ui.element('note-title').value = 'Submitted title';
    ui.submit();
    ui.element('note-title').value = 'Newer title';
    ui.element('note-body').value = 'Newer body';
    ui.element('note-pinned').checked = true;
    await ui.finishSave(index);
    assert.equal(ui.element('note-title').value, 'Newer title');
    assert.equal(ui.element('note-body').value, 'Newer body');
    assert.equal(ui.element('note-pinned').checked, true);
    assert.equal(ui.element('save-state').textContent, 'Unsaved changes');
    ui.submit();
    assert.equal(ui.writes[index + 1].path, '/api/notes/saved-note');
    assert.equal(ui.writes[index + 1].options.method, 'PATCH');
    await ui.finishSave(index + 1);
    assert.equal(ui.element('save-state').textContent, 'Saved');
  });
}

test('a delayed save cannot replace a different draft opened while waiting', async () => {
  const ui = await notebook();
  ui.element('note-title').value = 'Submitted title';
  ui.submit();
  ui.element('new-note').listeners.click();
  ui.element('note-title').value = 'Different draft';
  await ui.finishSave(0);
  assert.equal(ui.element('note-title').value, 'Different draft');
  ui.submit();
  assert.equal(ui.writes[1].path, '/api/notes');
  assert.equal(ui.writes[1].options.method, 'POST');
  await ui.finishSave(1);
});
