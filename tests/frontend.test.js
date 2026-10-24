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
const EXPORTS = ['projectIdFrom', 'icon', 'choiceGlyph', 'deckArt', 'splitUrls', 'photoFrame', 'showPhoto', 'stepPhoto', 'renderDetail', 'openDetail',
  'closeDetail', 'cardTap', 'h', 'safeUrl', 'cardModel', 'dragChoice', 'dragLean', 'swipeThresholds', 'SWIPE', 'choicesOf', 'plural', 'renderCard',
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
  mapping: { title: 'name', subtitle: 'city', highlight: 'price', image: 'img', description: 'about', link: 'url',
             gallery: ['more'] },
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

  test('cardModel: face slots, and every other non-empty field as details', () => {
    const m = app.cardModel(
      { n: 'Chair', p: '40', h: '$90', img: 'https://x.com/c.jpg', d: 'comfy', u: 'ftp://nope', c: '', w: 'oak' },
      { title: 'n', subtitle: 'p', highlight: 'h', image: 'img', description: 'd', link: 'u' });
    assert.equal(m.title, 'Chair');
    assert.equal(m.subtitle, '40');
    assert.equal(m.highlight, '$90');
    assert.equal(m.image, 'https://x.com/c.jpg');
    assert.equal(m.link, null);
    assert.deepEqual(m.details, [['w', 'oak']]);       // mapped fields aren't repeated; empty ones skipped
  });

  test('cardModel collects photos from the main field and the gallery', () => {
    const m = app.cardModel(
      { a: 'https://x.com/1.jpg, https://x.com/2.jpg', b: 'https://x.com/2.jpg | javascript:alert(1)',
        c: 'data:image/png;base64,AA,BB' },
      { image: 'a', gallery: ['b', 'c'] });
    assert.deepEqual(m.images, ['https://x.com/1.jpg', 'https://x.com/2.jpg', 'data:image/png;base64,AA,BB']);
    assert.equal(m.image, 'https://x.com/1.jpg');
    assert.deepEqual(m.details, []);                   // photo fields aren't repeated as details
  });

  test('splitUrls', () => {
    assert.deepEqual(app.splitUrls(' a , b|c\nd '), ['a', 'b', 'c', 'd']);
    assert.deepEqual(app.splitUrls('data:image/gif;base64,R0,lG'), ['data:image/gif;base64,R0,lG']);
    assert.deepEqual(app.splitUrls(null), []);
  });

  test('cardModel never shows a blank title and tolerates odd values', () => {
    assert.equal(app.cardModel({ a: '', b: 'second' }, { title: 'a' }).title, 'second');
    assert.equal(app.cardModel({}, {}).title, '(empty)');
    assert.equal(app.cardModel({ n: 7 }, { title: 'n' }).title, '7');
    assert.equal(app.cardModel({ n: '  x  ' }, null).title, '  x  ');   // no mapping: first value as-is
    assert.deepEqual(app.cardModel({ a: '1' }, { gallery: ['missing'] }).images, []);
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

  test('projectIdFrom only lets a real id through', () => {
    assert.equal(app.projectIdFrom('3f9a0c1b2d4e'), '3f9a0c1b2d4e');
    for (const bad of ['..%2F..%2Fapi', '../x', '', null, undefined, '3f9a0c1b2d4e?x=1']) {
      assert.equal(app.projectIdFrom(bad), null, String(bad));
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
    data: { name: 'Ana', city: 'Rosario', price: '$400', img: 'https://x.com/a.jpg', more: 'https://x.com/b.jpg',
            about: 'Line one\nline two', url: 'https://ana.dev', age: '31' },
    history: [{ round: 1, choice: 'right' }],
  };

  test('the face shows only the essentials', () => {
    const card = app.renderCard(item, project());
    assert.ok(card.classList.contains('photo'));
    assert.equal(card.querySelector('.title').textContent, 'Ana');
    assert.equal(card.querySelector('.highlight').textContent, '$400');
    assert.equal(card.querySelector('.subtitle').textContent, 'Rosario');
    assert.equal(card.querySelector('.media img').getAttribute('src'), 'https://x.com/a.jpg');
    assert.equal(card.querySelectorAll('.bars i').length, 2);
    assert.match(card.querySelector('.hist').textContent, /R1 ✓ Yes/);
    assert.ok(card.querySelector('[data-info]'));
    // details wait for the sheet
    assert.equal(card.querySelector('dl'), null);
    assert.equal(card.querySelector('a'), null);
    assert.equal(card.querySelectorAll('[data-stamp]').length, 0);
  });

  test('a card without photos is a text card that shows its description', () => {
    const card = app.renderCard({ data: { name: 'Plain', about: 'Some words' } }, project());
    assert.ok(card.classList.contains('text'));
    assert.equal(card.querySelector('.media'), null);
    assert.equal(card.querySelector('.desc').textContent, 'Some words');
  });

  test('hostile list data stays inert', () => {
    const evil = '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>';
    const card = app.renderCard({
      data: { name: evil, city: evil, price: evil, about: evil, img: 'javascript:alert(1)', url: 'javascript:alert(1)',
              age: evil },
    }, project());
    const sheet = app.renderDetail({ data: { name: evil, url: 'javascript:alert(1)', age: evil } }, project());
    document.body.append(card, sheet);
    for (const el of [card, sheet]) {
      assert.equal(el.querySelectorAll('script, img').length, 0);   // bad image url dropped
      assert.equal(el.querySelector('a'), null);                      // bad link dropped
      assert.equal(el.querySelector('.title').textContent, evil);
    }
    assert.equal(sheet.querySelector('dd').textContent, evil);
    assert.equal(window.pwned, undefined);
    card.remove(); sheet.remove();
  });

  test('empty slots render nothing; broken photos are skipped, then the card falls back to text', () => {
    const card = app.renderCard({ data: { name: 'x', img: 'https://x.com/404.png', more: 'https://x.com/ok.png' } }, project());
    assert.equal(card.querySelector('.subtitle'), null);
    assert.equal(card.querySelector('.highlight'), null);
    assert.equal(card.querySelector('.hist'), null);
    const img = card.querySelector('img');
    img.onerror();                                      // first fails: show the next
    assert.equal(img.getAttribute('src'), 'https://x.com/ok.png');
    assert.equal(card.querySelector('.bars'), null);    // one photo left: no bars
    img.onerror();                                      // none left
    assert.equal(card.querySelector('.media'), null);
    assert.ok(card.classList.contains('text'));
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

describe('photos and details', () => {
  const item = {
    data: { name: 'Flat', city: 'Palermo', price: '$400', img: 'https://x.com/1.jpg, https://x.com/2.jpg',
            more: 'https://x.com/3.jpg', about: 'Bright', url: 'https://flat.dev', rooms: '3', floor: '' },
    history: [],
  };

  test('showPhoto wraps around and moves the bar', () => {
    const f = app.photoFrame(['a.jpg', 'b.jpg', 'c.jpg'].map(x => `https://x.com/${x}`));
    const on = () => [...f.querySelectorAll('.bars i')].findIndex(b => b.classList.contains('on'));
    assert.equal(on(), 0);
    app.showPhoto(f, -1);
    assert.equal(f.index, 2);
    assert.equal(on(), 2);
    assert.equal(f.querySelector('img').getAttribute('src'), 'https://x.com/c.jpg');
    app.showPhoto(f, 3);
    assert.equal(on(), 0);
  });

  test('stepPhoto: edges step, the middle does not', () => {
    const f = app.photoFrame(['https://x.com/a.jpg', 'https://x.com/b.jpg']);
    assert.equal(app.stepPhoto(f, 290, 300), true);
    assert.equal(f.index, 1);
    assert.equal(app.stepPhoto(f, 10, 300), true);
    assert.equal(f.index, 0);
    assert.equal(app.stepPhoto(f, 150, 300), false);
    assert.equal(app.stepPhoto(app.photoFrame(['https://x.com/a.jpg']), 290, 300), false);   // single photo
    assert.equal(app.stepPhoto(null, 290, 300), false);
  });

  test('the details sheet has the big gallery and every field', () => {
    const decided = [];
    const sheet = app.renderDetail(item, project(), { onDecide: c => decided.push(c), photo: 1 });
    const g = sheet.querySelector('.gallery');
    assert.equal(g.images.length, 3);
    assert.equal(g.index, 1);
    assert.equal(g.querySelector('.count').textContent, '2 / 3');
    assert.equal(sheet.querySelector('.highlight').textContent, '$400');
    assert.equal(sheet.querySelector('.desc').textContent, 'Bright');
    assert.deepEqual([...sheet.querySelectorAll('dt')].map(d => d.textContent), ['rooms']);   // empty floor skipped
    assert.equal(sheet.querySelector('a.link').href, 'https://flat.dev/');
    assert.match(sheet.querySelector('a.link').rel, /noopener/);
    sheet.querySelector('[data-sheet-choice=right]').click();
    assert.deepEqual(decided, ['right']);
    // read-only (no onDecide): only a close button
    const ro = app.renderDetail(item, project());
    assert.equal(ro.querySelectorAll('[data-sheet-choice]').length, 0);
    assert.ok(ro.querySelector('[data-close]'));
  });

  test('openDetail/closeDetail: one sheet at a time, deciding closes it first', () => {
    const decided = [];
    app.openDetail(item, project(), { onDecide: c => decided.push([c, !!document.querySelector('.sheet')]) });
    app.openDetail(item, project());                   // a second open is ignored
    assert.equal(document.querySelectorAll('.sheet').length, 1);
    assert.ok(document.body.classList.contains('sheet-open'));
    document.querySelector('[data-sheet-choice=left]').click();
    assert.deepEqual(decided, [['left', false]]);
    assert.equal(document.querySelector('.sheet'), null);
    assert.ok(!document.body.classList.contains('sheet-open'));
    app.closeDetail();                                 // closing nothing is fine
  });

  test('cardTap: info button opens details, photo edges step, the middle opens', () => {
    const card = app.renderCard(item, project());
    document.body.appendChild(card);
    card.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 400 });
    const frame = card.querySelector('.media');
    app.cardTap(card, item, project(), { x: 280, target: card });
    assert.equal(frame.index, 1);
    assert.equal(document.querySelector('.sheet'), null);
    app.cardTap(card, item, project(), { x: 280, target: card.querySelector('[data-info]') });
    assert.equal(frame.index, 1);                      // info never steps
    assert.equal(document.querySelector('.sheet .gallery').index, 1);   // sheet opens on the same photo
    app.closeDetail();
    app.cardTap(card, item, project(), { x: 150, target: card });
    assert.ok(document.querySelector('.sheet'));
    app.closeDetail();
    card.remove();
  });
});

describe('icons', () => {
  test('icon() draws an inline, decorative SVG', () => {
    const svg = app.icon('check');
    assert.equal(svg.namespaceURI, 'http://www.w3.org/2000/svg');
    assert.equal(svg.getAttribute('aria-hidden'), 'true');
    assert.ok(svg.querySelector('path').getAttribute('d'));
    assert.ok(app.deckArt().querySelectorAll('rect').length >= 3);
  });

  test('default decisions get line icons; custom ones show as typed', () => {
    assert.equal(app.choiceGlyph({ icon: '✓' }).tagName, 'svg');
    assert.equal(app.choiceGlyph({ icon: '✕' }).tagName, 'svg');
    assert.equal(app.choiceGlyph({ icon: '?' }).className, 'glyph');
    assert.equal(app.choiceGlyph({ icon: '❤️' }).textContent, '❤️');
  });

  test('default colours are the house palette', () => {
    assert.deepEqual(Object.fromEntries(Object.entries(app.DEFAULT_CHOICES).map(([k, v]) => [k, v.color])),
      { left: '#b0604a', right: '#1f4a35', unsure: '#a8802a' });
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
    const mapping = { title: 'a' };
    const sample = [{ a: 'first', b: 'second', p: 'https://x.com/1.jpg', q: 'https://x.com/2.jpg' },
                    { a: 'next', b: 'other', p: '', q: '' }];
    let key = 'a';
    const ed = app.mappingEditor({ mapping, fields: ['a', 'b', 'p', 'q'], sample, project: project({ mapping }),
                                   keyField: key, onKeyField: v => { key = v; } });
    const title = () => ed.querySelector('.preview-wrap .card .title').textContent;
    assert.equal(title(), 'first');

    const sel = ed.querySelector('select[name=slot-title]');
    sel.value = 'b';
    sel.dispatchEvent(new window.Event('change'));
    assert.equal(mapping.title, 'b');
    assert.equal(title(), 'second');

    const hl = ed.querySelector('select[name=slot-highlight]');
    hl.value = 'a';
    hl.dispatchEvent(new window.Event('change'));
    assert.equal(ed.querySelector('.preview-wrap .card .highlight').textContent, 'first');

    // only link-holding fields are offered as more photos, minus the main one
    const img = ed.querySelector('select[name=slot-image]');
    img.value = 'p';
    img.dispatchEvent(new window.Event('change'));
    assert.deepEqual([...ed.querySelectorAll('.gallery-pick input')].map(i => i.name), ['gallery-q']);
    const cb = ed.querySelector('input[name=gallery-q]');
    cb.checked = true;
    cb.dispatchEvent(new window.Event('change'));
    assert.deepEqual(mapping.gallery, ['q']);
    assert.equal(ed.querySelectorAll('.preview-wrap .card .bars i').length, 2);
    // picking q as the main photo drops it from the gallery
    img.value = 'q';
    img.dispatchEvent(new window.Event('change'));
    assert.deepEqual(mapping.gallery, []);

    [...ed.querySelectorAll('.preview-wrap button')].at(-1).click();   // next sample
    assert.equal(title(), 'other');

    const ks = ed.querySelector('select[name=key-field]');
    ks.value = '';
    ks.dispatchEvent(new window.Event('change'));
    assert.equal(key, null);
  });
});
