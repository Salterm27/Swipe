// End-to-end: the wizard, the deck (buttons, keys, drag), results, rounds.
// Each test makes its own project and only asserts on it, so they can share
// one server.
const { test, expect } = require('@playwright/test');

async function createViaApi(request, name, text, extra = {}) {
  const r = await request.post('/api/projects', { data: { name, text, ...extra } });
  return (await r.json()).id;
}

const topTitle = page => page.locator('.card[data-item] .title');

test('wizard: name, meanings, paste, guessed layout, start swiping', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /new/i }).first().click();
  await page.locator('input[name=name]').fill('Weekend trips');
  await page.locator('input[name=label-right]').fill('Go');
  await page.click('[data-next="1"]');

  await page.locator('textarea[name=list]').fill(
    'name,region,photo,notes\n' +
    'Tigre,Buenos Aires,https://example.com/tigre.jpg,Boats and the delta market\n' +
    'Colonia,Uruguay,https://example.com/colonia.jpg,Ferry over and walk the old town');
  await page.click('[data-next="2"]');

  // the guess, shown as a real card
  await expect(page.locator('select[name=format]')).toHaveValue('csv');
  await expect(page.locator('select[name=slot-title]')).toHaveValue('name');
  await expect(page.locator('select[name=slot-image]')).toHaveValue('photo');
  await expect(page.locator('.preview-wrap .card .title')).toHaveText('Tigre');
  await page.locator('select[name=slot-subtitle]').selectOption('region');
  await expect(page.locator('.preview-wrap .card .subtitle')).toHaveText('Buenos Aires');

  await page.click('[data-create]');
  await expect(topTitle(page)).toHaveText('Tigre');
  await expect(page.locator('[data-choice=right]')).toHaveAttribute('title', 'Go');
});

test('deck: buttons, keyboard, undo, then the results page', async ({ page, request }) => {
  const pid = await createViaApi(request, 'Snacks', 'Apple\nBanana\nCherry\nDate');
  await page.goto(`/#/p/${pid}`);
  await expect(topTitle(page)).toHaveText('Apple');

  await page.click('[data-choice=right]');
  await expect(topTitle(page)).toHaveText('Banana');
  await page.keyboard.press('ArrowLeft');
  await expect(topTitle(page)).toHaveText('Cherry');
  await page.keyboard.press('Backspace');               // undo the left
  await expect(topTitle(page)).toHaveText('Banana');
  await page.keyboard.press('ArrowUp');                 // not sure
  await expect(topTitle(page)).toHaveText('Cherry');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByText('That’s round 1,')).toBeVisible();
  await expect(page.locator('#pcount')).toHaveText('4 / 4');

  await page.getByRole('button', { name: /see the results/i }).click();
  await expect(page.locator('[data-tile=right] .n')).toHaveText('2');
  await expect(page.locator('[data-tile=unsure] .n')).toHaveText('1');
  await expect(page.locator('[data-tile=left] .n')).toHaveText('1');
});

test('deck: only a long, clear drag decides; nudges and diagonals snap back', async ({ page, request }) => {
  const pid = await createViaApi(request, 'Drag', 'One\nTwo\nThree');
  await page.goto(`/#/p/${pid}`);
  await expect(topTitle(page)).toHaveText('One');
  const box = await page.locator('.card[data-item]').boundingBox();
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  const drag = async (dx, dy) => {
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + dx, cy + dy, { steps: 8 });
    await page.mouse.up();
  };

  await drag(90, 0);                                   // used to commit: now a nudge
  await expect(topTitle(page)).toHaveText('One');
  await drag(box.width * 0.45, -box.width * 0.45);     // diagonal: neither way
  await expect(topTitle(page)).toHaveText('One');
  await drag(box.width * 0.3, 0);                      // most of the way, then let go
  await expect(topTitle(page)).toHaveText('One');

  // the stamp only arms once a release would count
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + box.width * 0.2, cy, { steps: 6 });
  await expect(page.locator('.card[data-item] [data-stamp=right]')).not.toHaveClass(/armed/);
  await page.mouse.move(cx + box.width * 0.5, cy + 10, { steps: 6 });
  await expect(page.locator('.card[data-item] [data-stamp=right]')).toHaveClass(/armed/);
  await page.mouse.up();
  await expect(topTitle(page)).toHaveText('Two');

  await expect.poll(async () =>
    (await (await request.get(`/api/projects/${pid}`)).json()).round.counts.right).toBe(1);
});

test('results: change a decision, start round 2 with more data', async ({ page, request }) => {
  const pid = await createViaApi(request, 'Flats', 'id,name\n1,Palermo\n2,Belgrano\n3,Caballito');
  const items = (await (await request.get(`/api/projects/${pid}/items`)).json()).items;
  for (const [i, c] of [[0, 'right'], [1, 'left'], [2, 'unsure']]) {
    await request.post(`/api/projects/${pid}/decisions`, { data: { item_id: items[i].id, choice: c } });
  }
  await page.goto(`/#/p/${pid}/summary`);
  await expect(page.locator('[data-tile=left] .n')).toHaveText('1');

  // tap the ✓ on Belgrano's row
  await page.locator(`[data-row="${items[1].id}"] .pick button`).nth(2).click();
  await expect(page.locator('[data-tile=left] .n')).toHaveText('0');
  await expect(page.locator('[data-tile=right] .n')).toHaveText('2');

  await page.locator('textarea[name=next-text]').fill('id,rent\n1,500\n4,Recoleta');
  await page.click('[data-next-round]');
  await expect(page.locator('#round-label')).toHaveText('Round 2');
  await expect(page.locator('#pcount')).toHaveText('0 / 4');
  // memory of round 1 is on the card
  await expect(page.locator('.card[data-item] .hist')).toContainText('R1');
});

// 1x1 PNGs served for any https://img.test/… URL, so photos load offline
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
async function mockImages(page) {
  await page.route('https://img.test/**', route =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG }));
}

const FLATS = JSON.stringify([
  { title: 'Palermo loft', rent: '$500', area: 'Palermo', notes: 'Bright, quiet street', rooms: '2',
    photos: ['https://img.test/p1.png', 'https://img.test/p2.png', 'https://img.test/p3.png'],
    url: 'https://example.com/palermo' },
  { title: 'Belgrano flat', rent: '$650', area: 'Belgrano', notes: 'Near the park', rooms: '3',
    photos: ['https://img.test/b1.png'], url: 'https://example.com/belgrano' },
]);

test('card face shows the essentials; a tap opens every detail; decide from the sheet', async ({ page, request }) => {
  await mockImages(page);
  const pid = await createViaApi(request, 'Flats', FLATS);
  await page.goto(`/#/p/${pid}`);
  const card = page.locator('.card[data-item]');
  await expect(card.locator('.title')).toHaveText('Palermo loft');
  await expect(card.locator('.highlight')).toHaveText('$500');
  await expect(card.locator('.subtitle')).toHaveText('Palermo');
  await expect(card.locator('.bars i')).toHaveCount(3);
  await expect(card.locator('dl, a')).toHaveCount(0);        // details stay off the face

  // tapping the right edge steps photos, without opening anything
  const box = await card.boundingBox();
  await page.mouse.click(box.x + box.width * 0.9, box.y + box.height * 0.4);
  await expect(card.locator('.bars i').nth(1)).toHaveClass(/on/);
  await expect(page.locator('.sheet')).toHaveCount(0);

  // the middle opens the sheet on the same photo
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.4);
  const sheet = page.locator('.sheet');
  await expect(sheet).toBeVisible();
  await expect(sheet.locator('.gallery .count')).toHaveText('2 / 3');
  await expect(sheet.locator('.desc')).toHaveText('Bright, quiet street');
  await expect(sheet.locator('dt')).toHaveText(['rooms']);
  await expect(sheet.locator('a.link')).toHaveAttribute('href', 'https://example.com/palermo');
  await sheet.locator('.gallery').click({ position: { x: 5, y: 50 } });   // left edge: back
  await expect(sheet.locator('.gallery .count')).toHaveText('1 / 3');

  // deciding from the sheet closes it and moves on
  await sheet.locator('[data-sheet-choice=right]').click();
  await expect(sheet).toHaveCount(0);
  await expect(card.locator('.title')).toHaveText('Belgrano flat');
  await expect(card.locator('.bars')).toHaveCount(0);       // single photo: no bars
  await expect.poll(async () =>
    (await (await request.get(`/api/projects/${pid}`)).json()).round.counts.right).toBe(1);
});

test('sheet: info button, Esc, the back gesture and keyboard all behave', async ({ page, request }) => {
  await mockImages(page);
  const pid = await createViaApi(request, 'Flats2', FLATS);
  await page.goto(`/#/p/${pid}`);
  const card = page.locator('.card[data-item]');
  await expect(card.locator('.title')).toHaveText('Palermo loft');

  await card.locator('[data-info]').click();
  await expect(page.locator('.sheet')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.sheet')).toHaveCount(0);

  await page.keyboard.press('Enter');                        // keyboard opens it too
  await expect(page.locator('.sheet')).toBeVisible();
  await page.goBack();                                       // phone back: closes, stays on the deck
  await expect(page.locator('.sheet')).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`#/p/${pid}$`));
  await expect(card.locator('.title')).toHaveText('Palermo loft');

  await page.keyboard.press('i');
  await page.keyboard.press('ArrowLeft');                    // arrows decide inside the sheet
  await expect(page.locator('.sheet')).toHaveCount(0);
  await expect(card.locator('.title')).toHaveText('Belgrano flat');
  await page.keyboard.press('Backspace');                    // and undo still works after
  await expect(card.locator('.title')).toHaveText('Palermo loft');
});

test('results: tapping a row opens its details and can change the decision', async ({ page, request }) => {
  await mockImages(page);
  const pid = await createViaApi(request, 'Flats3', FLATS);
  const items = (await (await request.get(`/api/projects/${pid}/items`)).json()).items;
  await request.post(`/api/projects/${pid}/decisions`, { data: { item_id: items[0].id, choice: 'left' } });
  await page.goto(`/#/p/${pid}/summary`);
  await page.locator(`[data-row="${items[0].id}"] .grow`).click();
  await expect(page.locator('.sheet .title')).toHaveText('Palermo loft');
  await page.locator('.sheet [data-sheet-choice=right]').click();
  await expect(page.locator('.sheet')).toHaveCount(0);
  await expect(page.locator('[data-tile=right] .n')).toHaveText('1');
  await expect(page.locator('[data-tile=left] .n')).toHaveText('0');
});

test('wizard: highlight and more-photo pickers drive the preview', async ({ page }) => {
  await mockImages(page);
  await page.goto('/#/new');
  await page.locator('input[name=name]').fill('Flats4');
  await page.click('[data-next="1"]');
  await page.locator('textarea[name=list]').fill(JSON.stringify([
    { name: 'A', price: '$1', cover: 'https://img.test/a.png', extra: 'https://img.test/a2.png' },
    { name: 'B', price: '$2', cover: 'https://img.test/b.png', extra: 'https://img.test/b2.png' }]));
  await page.click('[data-next="2"]');
  await expect(page.locator('select[name=slot-highlight]')).toHaveValue('price');
  await expect(page.locator('.preview-wrap .card .highlight')).toHaveText('$1');
  await expect(page.locator('select[name=slot-image]')).toHaveValue('cover');
  await expect(page.locator('input[name=gallery-extra]')).toBeChecked();   // guessed as a second photo
  await expect(page.locator('.preview-wrap .card .bars i')).toHaveCount(2);
  await page.locator('input[name=gallery-extra]').uncheck();
  await expect(page.locator('.preview-wrap .card .bars')).toHaveCount(0);
  await page.locator('.preview-wrap .card .info').click();                // preview the details
  await expect(page.locator('.sheet .title')).toHaveText('A');
  await expect(page.locator('.sheet [data-sheet-choice]')).toHaveCount(0);  // preview: read-only
  await page.keyboard.press('Escape');
  await page.click('[data-create]');
  await expect(page.locator('.card[data-item] .highlight')).toHaveText('$1');
});

test('design: fonts are served locally and reduced motion turns animation off', async ({ page, request, browser }) => {
  for (const f of ['newsreader-latin-400-normal', 'newsreader-latin-400-italic', 'dm-sans-latin-500-normal']) {
    const r = await request.get(`/fonts/${f}.woff2`);
    expect(r.status()).toBe(200);
  }
  const external = [];
  page.on('request', r => { if (!r.url().startsWith('http://127.0.0.1')) external.push(r.url()); });
  await page.goto('/');
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.fonts.check('16px "DM Sans"') && document.fonts.check('italic 30px Newsreader'))).toBe(true);
  expect(external).toEqual([]);                                   // nothing leaves the Pi

  const ctx = await browser.newContext({ reducedMotion: 'reduce', baseURL: page.url() });
  const calm = await ctx.newPage();
  const pid = await createViaApi(request, 'Calm', 'One\nTwo');
  await calm.goto(`/#/p/${pid}`);
  await calm.locator('.card[data-item] [data-info]').click();
  const dur = await calm.locator('.sheet').evaluate(e => getComputedStyle(e).animationDuration);
  expect(parseFloat(dur)).toBeLessThan(0.01);
  await ctx.close();
});
