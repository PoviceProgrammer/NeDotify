// Browser test for NeDotify Riff-style update banner and dialog in both UI styles.
// Run with NODE_PATH pointing at the installed Playwright runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');

const root = path.resolve(__dirname, '..', 'ui');
const htmlSource = fs.readFileSync(path.join(root, 'web_new_v2/index.html'), 'utf8');

(async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        for (const width of [800, 360]) {
            const page = await browser.newPage({ viewport: { width, height: 600 } });
            await page.emulateMedia({ reducedMotion: 'reduce' });

            // Minimal DOM containing notification stack, dialog and buttons
            await page.setContent(`
                <div id="notification-stack">
                    <div id="update-banner" class="update-banner hidden" role="status" aria-live="polite">
                        <div class="update-banner-icon" aria-hidden="true"><svg></svg></div>
                        <div class="update-banner-content">
                            <span class="update-banner-text">Доступно обновление NeDotify <strong id="update-banner-version"></strong></span>
                        </div>
                        <div class="update-banner-actions">
                            <button type="button" class="update-banner-btn update-btn-primary" id="update-banner-action-btn">Обновить</button>
                            <button type="button" class="update-banner-btn update-btn-secondary" id="update-banner-details-btn">Подробнее</button>
                            <button type="button" class="update-banner-close" id="update-banner-close-btn" aria-label="Закрыть">×</button>
                        </div>
                    </div>
                    <div id="network-banner" class="network-banner hidden" role="status" aria-live="polite">
                        <svg></svg><span id="network-banner-text">Нет сети</span>
                    </div>
                    <div id="toast-container" role="status" aria-live="polite"></div>
                </div>
                <dialog id="update-modal" class="glass-modal update-dialog">
                    <div class="update-modal-header">
                        <span class="update-modal-badge" id="update-modal-badge">v2.5.2</span>
                        <span class="update-modal-time" id="update-modal-time"></span>
                        <h2 id="update-modal-title">Вышло обновление NeDotify</h2>
                        <button id="update-modal-close" type="button" class="icon-btn">×</button>
                    </div>
                    <div class="update-modal-body">
                        <div class="update-modal-notes" id="update-modal-notes"></div>
                    </div>
                    <div class="update-modal-footer">
                        <button type="button" class="home-pill" id="update-modal-ignore-btn">Не напоминать</button>
                        <button type="button" class="profile-save-button" id="update-modal-download-btn">Скачать</button>
                    </div>
                </dialog>
            `);

            // Load stylesheets
            for (const file of [
                'web_new_v2/css/components/base.css',
                'web_new_v2/css/components/visual-polish.css',
                'MACos_ui/tokens.css',
                'MACos_ui/interface.css',
                'web_new_v2/css/components/notifications.css',
            ]) {
                await page.addStyleTag({ content: fs.readFileSync(path.join(root, file), 'utf8') });
            }

            for (const style of ['current', 'macos-light', 'macos-dark']) {
                await page.evaluate((styleMode) => {
                    const isMac = styleMode.startsWith('macos');
                    document.documentElement.dataset.uiStyle = isMac ? 'macos' : 'current';
                    document.documentElement.dataset.macosMode = isMac ? (styleMode.includes('light') ? 'light' : 'dark') : '';

                    const banner = document.getElementById('update-banner');
                    banner.classList.remove('hidden', 'leaving');
                    document.getElementById('update-banner-version').textContent = 'v2.5.2';
                }, style);

                const bannerBox = await page.locator('#update-banner').evaluate((el) => {
                    const rect = el.getBoundingClientRect();
                    const css = getComputedStyle(el);
                    return {
                        top: rect.top,
                        left: rect.left,
                        right: rect.right,
                        bottom: rect.bottom,
                        height: rect.height,
                        width: rect.width,
                        radiusBottomLeft: css.borderBottomLeftRadius,
                        radiusBottomRight: css.borderBottomRightRadius,
                        radiusTopLeft: css.borderTopLeftRadius,
                        radiusTopRight: css.borderTopRightRadius,
                    };
                });

                // Top attachment check: in both styles, it MUST attach to window top
                assert.equal(bannerBox.top, 0, `${style}/${width}: update banner top must be 0`);
                // Authentic Riff droplet shape: bottom radius 22px, top radius 0
                assert.equal(bannerBox.radiusBottomLeft, '22px', `${style}/${width}: borderBottomLeftRadius must be 22px`);
                assert.equal(bannerBox.radiusBottomRight, '22px', `${style}/${width}: borderBottomRightRadius must be 22px`);
                assert.equal(bannerBox.radiusTopLeft, '0px', `${style}/${width}: borderTopLeftRadius must be 0px`);
                assert.equal(bannerBox.radiusTopRight, '0px', `${style}/${width}: borderTopRightRadius must be 0px`);

                // Ensure it fits within viewport
                assert.ok(bannerBox.left >= 0, `${style}/${width}: banner must not overflow left`);
                assert.ok(bannerBox.right <= width, `${style}/${width}: banner must not overflow right`);

                // Verify interactive buttons exist and are visible
                const actionBtn = page.locator('#update-banner-action-btn');
                const detailsBtn = page.locator('#update-banner-details-btn');
                const closeBtn = page.locator('#update-banner-close-btn');

                await assert.doesNotReject(async () => {
                    await actionBtn.click();
                    await detailsBtn.click();
                });

                // Test vertical stacking with #network-banner
                await page.locator('#network-banner').evaluate((el) => {
                    el.classList.remove('hidden');
                });

                const stack = await page.evaluate(() => {
                    const ub = document.getElementById('update-banner').getBoundingClientRect();
                    const nb = document.getElementById('network-banner').getBoundingClientRect();
                    return { updateBottom: ub.bottom, networkTop: nb.top };
                });

                assert.ok(
                    stack.networkTop >= stack.updateBottom,
                    `${style}/${width}: network banner must not overlap update banner: ${stack.networkTop} < ${stack.updateBottom}`
                );

                // Close banner
                await closeBtn.click();
                await page.locator('#update-banner').evaluate((el) => el.classList.add('hidden'));
                await page.locator('#network-banner').evaluate((el) => el.classList.add('hidden'));

                console.log(`PASS ${style}/${width}: Riff droplet geometry and stacking verified`);
            }
            await page.close();
        }
    } finally {
        await browser.close();
    }
})().catch((err) => {
    console.error(err);
    process.exitCode = 1;
});
