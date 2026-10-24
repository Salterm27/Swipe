/**
 * Unit tests for the frontend. Run with:  node --test tests/frontend.test.js
 *
 * static/index.html is one file with the whole app in a <script> block, so
 * there's nothing to import. We load the page's markup into jsdom and
 * evaluate the script up to its boot marker (so no routing or fetching
 * happens), then call its functions directly. Milliseconds, no browser;
 * gestures and async flows are covered by the Playwright suite.
 */

const { test, describe } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const BOOT_MARKER = '/* ============================================================ boot */';
const EXPORTS = ['h', 'safeUrl', 'cardModel', 'dragChoice', 'dragLean', 'swipeThresholds', 'SWIPE', 'choicesOf', 'plural', 'renderCard',
  'statsBar', 'choiceChip', 'choiceEditor', 'mappingEditor', 'setStamps', 'DEFAULT_CHOICES',
  'PROJECT_ID'];

function loadApp() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://swipe.test/' });
  const script = dom.window.document.querySelector('script:not([src])');
  assert.ok(script, 'could not find the inline <script> in index.html');
  const source = script.textContent;
  script.remove();   // the page markup stays, the app code is run below
  const cut = source.indexOf(BOOT_MARKER);
  assert.notEqual(cut, -1, 'boot marker not found in index.html — update BOOT_MARKER in this harness');
  dom.window.eval(`${source.slice(0, cut)};window.__app = { ${EXPORTS.join(', ')} };`);
  return { app: dom.window.__app, window: dom.window, document: dom.window.document };
}

const { app, window, document } = loadApp();

const project = (over = {}) => ({
  choices: app.DEFAULT_CHOICES,
  mapping: { title: 'name', subtitle: 'city', image: 'img', description: 'about', link: 'url', details: ['age'] },
  ...over,
});

describe('pure helpers', () => {
  test('safeUrl only lets http(s) through, plus data:image for images', () => {
    assert.equal(app.safeUrl('https://x.com/a.jpg'), 'https://x.com/a.jpg');
    assert.equal(app.safeUrl('  http://x.com  '), 'http://x.com');
    assert.equal(app.safeUrl('javascript:alert(1)'), null);
    assert.equal(app.safeUrl('JaVaScRiPt:alert(1)', { image: true }), null);
    assert.equal(app.safeUrl('https://x.com/a b'), null);          // spaces: not one URL
    assert.equal(app.safeUrl('data:image/png;base64,AAA'), null);
    assert.equal(app.safeUrl('data:image/png;base64,AAA', { image: true }), 'data:image/png;base64,AAA');
    assert.equal(app.safeUrl('data:image/svg+xml,<svg/>', { image: true }), 'data:image/svg+xml,<svg/>');
    assert.equal(app.safeUrl('data:text/html,<b>', { image: true }), null);
    assert.equal(app.safeUrl(''), null);
    assert.equal(app.safeUrl(null), null);
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

  test('cardModel never shows a blank title and tolerates odd values', () => {
    assert.equal(app.cardModel({ a: '', b: 'second' }, { title: 'a' }).title, 'second');
    assert.equal(app.cardModel({}, {}).title, '(empty)');
    assert.equal(app.cardModel({ n: 7 }, { title: 'n' }).title, '7');
    assert.equal(app.cardModel({ n: '  x  ' }, null).title, '  x  ');   // no mapping: first value as-is
    assert.deepEqual(app.cardModel({ a: '1' }, { details: ['missing'] }).details, []);
  });

  test('thresholds scale with the card, with a floor for small screens', () => {
    assert.deepEqual(app.swipeThresholds(400, 600), { x: 160, y: 180 });
    assert.deepEqual(app.swipeThresholds(200, 300), { x: 110, y: 130 });
  });

  test('dragChoice needs the full threshold in a clear direction', () => {
    const th = { x: 160, y: 180 };
    assert.equal(app.dragChoice(90, 0, th), null);        // the old 90px commit point
    assert.equal(app.dragChoice(159, 0, th), null);
    assert.equal(app.dragChoice(160, 0, th), 'right');
    assert.equal(app.dragChoice(-170, 40, th), 'left');
    assert.equal(app.dragChoice(170, -175, th), null);    // diagonal: neither
    assert.equal(app.dragChoice(170, 190, th), null);     // mostly down: nothing
    assert.equal(app.dragChoice(30, -200, th), 'unsure');
    assert.equal(app.dragChoice(100, -200, th), null);    // up, but drifting too far sideways
    assert.equal(app.dragChoice(0, 300, th), null);       // down is not a choice
  });

  test('dragLean reports direction and progress for the stamps', () => {
    const th = { x: 100, y: 100 };
    assert.deepEqual(app.dragLean(50, 0, th), { choice: 'right', progress: 0.5 });
    assert.deepEqual(app.dragLean(0, -150, th), { choice: 'unsure', progress: 1.5 });
    assert.deepEqual(app.dragLean(5, 5, th), { choice: null, progress: 0 });
  });

  test('choicesOf fills in defaults', () => {
    const c = app.choicesOf({ choices: { right: { label: 'Keep', icon: '❤️', color: '#ff0000' } } });
    assert.equal(c.right.label, 'Keep');
    assert.equal(c.left.label, 'No');
    assert.equal(app.choicesOf(null).unsure.icon, '?');
  });

  test('PROJECT_ID only accepts the server id shape', () => {
    assert.ok(app.PROJECT_ID.test('3f9a0c1b2d4e'));
    for (const bad of ['..%2F..%2Fapi', '3F9A0C1B2D4E', '3f9a0c1b2d4', '3f9a0c1b2d4e0', '', '3f9a0c1b2d4e/../x']) {
      assert.ok(!app.PROJECT_ID.test(bad), bad);
    }
  });

  test('plural', () => {
    assert.equal(app.plural(1, 'item'), '1 item');
    assert.equal(app.plural(0, 'item'), '0 items');
  });
});

describe('h()', () => {
  test('sets text as text, never as HTML', () => {
    const el = app.h('div', {}, '<img src=x onerror=alert(1)>');
    assert.equal(el.children.length, 0);
    assert.equal(el.textContent, '<img src=x onerror=alert(1)>');
  });

  test('attributes, properties, events, styles and css vars', () => {
    let clicked = 0;
    const el = app.h('button', {
      class: 'btn', 'data-x': 'y', title: 't', disabled: false, hidden: null,
      onclick: () => { clicked++; }, style: { color: 'red' }, vars: { '--c': '#123456' },
    }, 'Go');
    assert.equal(el.className, 'btn');
    assert.equal(el.dataset.x, 'y');
    assert.equal(el.title, 't');
    assert.equal(el.hasAttribute('disabled'), false);
    assert.equal(el.style.color, 'red');
    assert.equal(el.style.getPropertyValue('--c'), '#123456');
    el.click();
    assert.equal(clicked, 1);
  });

  test('flattens nested child arrays and skips null/false', () => {
    const el = app.h('dl', {}, [[app.h('dt', {}, 'a'), app.h('dd', {}, 'b')], [null, false]], 0);
    assert.deepEqual([...el.childNodes].map(n => n.textContent), ['a', 'b', '0']);
  });
});

describe('renderCard', () => {
  const item = {
    data: { name: 'Ana', city: 'Rosario', img: 'https://x.com/a.jpg', about: 'Line one\nline two',
            url: 'https://ana.dev', age: '31' },
    history: [{ round: 1, choice: 'right' }],
  };

  test('fills every slot from the mapping', () => {
    const card = app.renderCard(item, project());
    assert.equal(card.querySelector('.title').textContent, 'Ana');
    assert.equal(card.querySelector('.subtitle').textContent, 'Rosario');
    assert.equal(card.querySelector('.media img').getAttribute('src'), 'https://x.com/a.jpg');
    assert.equal(card.querySelector('.desc').textContent, 'Line one\nline two');
    assert.equal(card.querySelector('dt').textContent, 'age');
    const a = card.querySelector('a.link');
    assert.equal(a.href, 'https://ana.dev/');
    assert.equal(a.target, '_blank');
    assert.match(a.rel, /noopener/);
    assert.match(card.querySelector('.hist').textContent, /R1 ✓ Yes/);
    assert.equal(card.querySelectorAll('[data-stamp]').length, 0);
  });

  test('hostile list data stays inert', () => {
    const evil = '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>';
    const card = app.renderCard({
      data: { name: evil, city: evil, about: evil, img: 'javascript:alert(1)', url: 'javascript:alert(1)', age: evil },
    }, project());
    document.body.appendChild(card);
    assert.equal(card.querySelectorAll('script, img').length, 0);   // no media: bad image url dropped
    assert.equal(card.querySelector('a'), null);                      // bad link dropped
    assert.equal(card.querySelector('.title').textContent, evil);
    assert.equal(window.pwned, undefined);
    card.remove();
  });

  test('empty slots render nothing, and a broken image removes its frame', () => {
    const card = app.renderCard({ data: { name: 'x', img: 'https://x.com/404.png' } }, project());
    assert.equal(card.querySelector('.subtitle'), null);
    assert.equal(card.querySelector('.desc'), null);
    assert.equal(card.querySelector('dl'), null);
    assert.equal(card.querySelector('.hist'), null);
    const img = card.querySelector('img');
    img.onerror();
    assert.equal(card.querySelector('.media'), null);
  });

  test('stamps use the project labels and colours, and follow the drag', () => {
    const p = project({ choices: { ...app.DEFAULT_CHOICES, right: { label: 'Keep', icon: '❤️', color: '#ff0000' } } });
    const card = app.renderCard(item, p, { withStamps: true });
    const right = card.querySelector('[data-stamp=right]');
    assert.equal(right.textContent, '❤️ Keep');
    assert.equal(right.style.getPropertyValue('--c'), '#ff0000');
    const th = { x: 100, y: 100 };
    app.setStamps(card, 50, 0, th);                   // halfway: faint, not armed
    assert.equal(Number(right.style.opacity), 0.25);
    assert.equal(right.classList.contains('armed'), false);
    assert.equal(Number(card.querySelector('[data-stamp=left]').style.opacity), 0);
    app.setStamps(card, 100, 0, th);                  // release here would commit
    assert.equal(Number(right.style.opacity), 1);
    assert.equal(right.classList.contains('armed'), true);
    app.setStamps(card, 0, -500, th);
    assert.equal(Number(card.querySelector('[data-stamp=unsure]').style.opacity), 1);
    assert.equal(Number(right.style.opacity), 0);
  });
});

describe('small widgets', () => {
  test('statsBar has one segment per non-empty pile, sized by share', () => {
    const bar = app.statsBar({ total: 4, counts: { right: 2, left: 1, unsure: 0 } }, app.DEFAULT_CHOICES);
    const segs = [...bar.children];
    assert.equal(segs.length, 2);
    assert.equal(segs[0].style.width, '50%');
    assert.equal(segs[1].style.width, '25%');
    assert.equal(app.statsBar({ total: 0, counts: {} }, app.DEFAULT_CHOICES).children.length, 0);
    assert.equal(app.statsBar(null, app.DEFAULT_CHOICES).children.length, 0);
  });

  test('choiceChip', () => {
    const chip = app.choiceChip(app.DEFAULT_CHOICES, 'left', 'R2 ');
    assert.equal(chip.textContent, 'R2 ✕ No');
  });

  test('choiceEditor edits the object it is given', () => {
    const choices = structuredClone(app.DEFAULT_CHOICES);
    const ed = app.choiceEditor(choices);
    const label = ed.querySelector('input[name=label-right]');
    label.value = 'Keep';
    label.dispatchEvent(new window.Event('input'));
    assert.equal(choices.right.label, 'Keep');
    // quick-pick icons write into the icon field and the object
    const pick = [...ed.querySelectorAll('.picks button')].find(b => b.textContent === '❤️');
    pick.click();
    assert.equal(choices.right.icon, '❤️');
  });

  test('mappingEditor re-renders the preview as slots change', () => {
    const mapping = { title: 'a', details: [] };
    const sample = [{ a: 'first', b: 'second' }, { a: 'next', b: 'other' }];
    let key = 'a';
    const ed = app.mappingEditor({ mapping, fields: ['a', 'b'], sample, project: project({ mapping }),
                                   keyField: key, onKeyField: v => { key = v; } });
    const title = () => ed.querySelector('.preview-wrap .card .title').textContent;
    assert.equal(title(), 'first');

    const sel = ed.querySelector('select[name=slot-title]');
    sel.value = 'b';
    sel.dispatchEvent(new window.Event('change'));
    assert.equal(mapping.title, 'b');
    assert.equal(title(), 'second');

    [...ed.querySelectorAll('.preview-wrap button')].at(-1).click();   // next sample
    assert.equal(title(), 'other');

    const cb = [...ed.querySelectorAll('.details-pick input')][0];
    cb.checked = true;
    cb.dispatchEvent(new window.Event('change'));
    assert.deepEqual(mapping.details, ['a']);

    const ks = ed.querySelector('select[name=key-field]');
    ks.value = '';
    ks.dispatchEvent(new window.Event('change'));
    assert.equal(key, null);
  });
});
