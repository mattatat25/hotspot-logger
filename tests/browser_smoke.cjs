const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium, webkit } = require('playwright');

const base = 'http://127.0.0.1:8788';
const credentials = { username: 'N0CALL', password: 'browserpass' };
const output = process.env.BROWSER_OUTPUT || '/tmp/hotspot-browser-results';
fs.mkdirSync(output, { recursive: true });

async function fits(page) {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    `Page overflows at ${page.url()}`);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ httpCredentials: credentials, viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  await page.goto(base);
  await page.locator('.brand-logo').evaluate(img => img.decode());
  await page.screenshot({ path: `${output}/setup-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: 'Add hotspot', exact: true }).click();
  assert.equal(await page.locator('.hotspot-row').count(), 2);
  await page.getByRole('button', { name: 'Remove hotspot', exact: true }).last().click();
  assert.equal(await page.locator('.hotspot-row').count(), 1);
  await page.locator('[name=hotspot_label_0]').fill('Desk hotspot');
  await page.locator('[name=hotspot_url_0]').fill('http://hotspot.test/api/');
  await page.locator('[name=hotspot_freq_0]').fill('441.425');
  await page.locator('[name=station_callsign]').fill('N0CALL');
  await page.locator('[name=theme_mode]').selectOption('logger');
  await page.locator('[name=password]').fill(credentials.password);
  await page.locator('[name=password_confirm]').fill(credentials.password);
  await page.getByRole('button', { name: 'Start logger', exact: true }).click();
  await page.waitForURL(base + '/');
  await fits(page);
  await browser.close();

  for (const [engine, type] of Object.entries({ chromium, webkit })) {
    const browser = await type.launch();
    for (const [device, viewport] of Object.entries({ desktop: { width: 1440, height: 1000 }, phone: { width: 390, height: 844 } })) {
      for (const colorScheme of ['light', 'dark']) {
        const context = await browser.newContext({ httpCredentials: credentials, viewport, colorScheme });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(base);
        await page.locator('.brand-logo').evaluate(img => img.decode());
        assert.equal(await page.locator('.brand-logo').evaluate(img => img.naturalWidth), 2172);
        const bounds = await page.locator('.brand-logo').boundingBox();
        assert(bounds.width > 200 && bounds.height > 50);
        await fits(page);
        assert(await page.locator('footer').innerText().then(text => text.includes('KF0WSS') && text.includes('Beta')));
        await page.screenshot({ path: `${output}/${engine}-${device}-${colorScheme}.png`, fullPage: true });
        await page.getByRole('link', { name: 'Review', exact: true }).first().click();
        await fits(page);
        assert(await page.getByRole('button', { name: 'Log to QRZ', exact: true }).isDisabled());
        await page.goto(base + '/settings');
        await fits(page);
        await page.getByRole('button', { name: 'Add hotspot', exact: true }).click();
        assert.equal(await page.locator('.hotspot-row').count(), 2);
        await page.screenshot({ path: `${output}/${engine}-${device}-${colorScheme}-settings.png`, fullPage: true });
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    await browser.close();
  }
  console.log('Chromium and WebKit desktop/phone layout, setup controls, and logo checks passed.');
})().catch(error => { console.error(error); process.exit(1); });
