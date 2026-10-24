/**
 * Unit tests for the frontend's pure logic. Run with:  node --test tests/frontend.test.js
 *
 * static/index.html is one file with the whole app in a <script> block, so
 * we extract that block (up to the boot marker) and evaluate it in a vm
 * context with just enough DOM shimmed for it to load.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const BOOT_MARKER = '/* ============================================================ boot */';

function loadApp() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
  const m = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(m, 'could not find the <script> block in index.html');
  const cut = m[1].indexOf(BOOT_MARKER);
  assert.notEqual(cut, -1, 'boot marker not found in index.html — update BOOT_MARKER in this harness');
  const ctx = vm.createContext({
    document: { addEventListener() {}, getElementById: () => null },
    window: { addEventListener() {} },
    structuredClone,
  });
  vm.runInContext(m[1].slice(0, cut) + ';this.__app = { safeUrl, cardModel, dragChoice, choicesOf, plural };', ctx);
  return ctx.__app;
}

const app = loadApp();

test('safeUrl only lets http(s) through, plus data:image for images', () => {
  assert.equal(app.safeUrl('https://x.com/a.jpg'), 'https://x.com/a.jpg');
  assert.equal(app.safeUrl('  http://x.com  '), 'http://x.com');
  assert.equal(app.safeUrl('javascript:alert(1)'), null);
  assert.equal(app.safeUrl('data:image/png;base64,AAA'), null);
  assert.equal(app.safeUrl('data:image/png;base64,AAA', { image: true }), 'data:image/png;base64,AAA');
  assert.equal(app.safeUrl('data:text/html,<b>', { image: true }), null);
  assert.equal(app.safeUrl(''), null);
});

test('cardModel follows the mapping and skips empty details', () => {
  const m = app.cardModel(
    { n: 'Chair', p: '40', img: 'https://x.com/c.jpg', d: 'comfy', u: 'ftp://nope', c: '', w: 'oak' },
    { title: 'n', subtitle: 'p', image: 'img', description: 'd', link: 'u', details: ['c', 'w'] });
  assert.equal(m.title, 'Chair');
  assert.equal(m.subtitle, '40');
  assert.equal(m.image, 'https://x.com/c.jpg');
  assert.equal(m.link, null);
  assert.deepEqual(m.details, [['w', 'oak']]);
});

test('cardModel never shows a blank title', () => {
  assert.equal(app.cardModel({ a: '', b: 'second' }, { title: 'a' }).title, 'second');
  assert.equal(app.cardModel({}, {}).title, '(empty)');
});

test('dragChoice needs the threshold and prefers the dominant axis for up', () => {
  assert.equal(app.dragChoice(30, 0), null);
  assert.equal(app.dragChoice(120, 0), 'right');
  assert.equal(app.dragChoice(-120, 40), 'left');
  assert.equal(app.dragChoice(20, -150), 'unsure');
  assert.equal(app.dragChoice(150, -120), 'right');   // mostly sideways
  assert.equal(app.dragChoice(0, 150), null);          // down is not a choice
});

test('choicesOf fills in defaults', () => {
  const c = app.choicesOf({ choices: { right: { label: 'Keep', icon: '❤️', color: '#ff0000' } } });
  assert.equal(c.right.label, 'Keep');
  assert.equal(c.left.label, 'No');
  assert.equal(app.choicesOf(null).unsure.icon, '?');
});
