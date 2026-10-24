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
  await expect(page.getByText('Round 1 done')).toBeVisible();
  await expect(page.locator('#pcount')).toHaveText('4 / 4');

  await page.getByRole('button', { name: /see results/i }).click();
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
