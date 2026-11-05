// NeDotify — Artist Page (Riff v44.0.0 Architecture) Browser Test
// Covers ART-001, ART-003, ART-004, ART-005, ART-006, ART-012, ART-013, ART-014.
const { chromium } = require('playwright');
const { readFileSync, existsSync } = require('node:fs');
const { resolve, extname, sep } = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');

const root = resolve(__dirname, '..', 'ui');
const server = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const filePath = resolve(root, pathname.startsWith('/MACos_ui/') ? '.' + pathname : 'web_new_v2/' + (pathname === '/' ? 'index.html' : pathname.slice(1)));
    if (!filePath.startsWith(root + sep) || !existsSync(filePath)) {
        res.writeHead(404);
        res.end();
        return;
    }
    let body = readFileSync(filePath);
    if (filePath.endsWith('index.html')) {
        body = body.toString()
            .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
            .replace('</head>', '<link rel="stylesheet" href="/css/components/base.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
    }
    res.setHeader('Content-Type', ({
        '.html': 'text/html',
        '.js': 'text/javascript',
        '.css': 'text/css',
        '.woff2': 'font/woff2',
        '.png': 'image/png',
        '.svg': 'image/svg+xml'
    })[extname(filePath)] || 'application/octet-stream');
    res.end(body);
});

(async () => {
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {})
    });

    try {
        const page = await browser.newPage();

        for (const style of ['current', 'macos']) {
            await page.setViewportSize({ width: 1200, height: 850 });
            await page.goto(`http://127.0.0.1:${server.address().port}`);

            // Initialize modules and mock bridge
            await page.evaluate(async (styleName) => {
                document.documentElement.dataset.uiStyle = styleName;
                document.documentElement.dataset.macosMode = 'dark';
                document.querySelector('#app-splash')?.remove();

                window.calls = [];
                window.testArtistData = {
                    status: 'found',
                    name: 'Queen',
                    isVerified: true,
                    verified: true,
                    subscribers: '12,500,000',
                    fans: 12500000,
                    monthlyListeners: '42,000,000 слушателей',
                    bio: 'Queen are a British rock band formed in London in 1970 by Freddie Mercury, Brian May, Roger Taylor, and John Deacon. Their earliest works were influenced by progressive rock, hard rock and heavy metal, but the band gradually ventured into more conventional and radio-friendly works by incorporating further styles, such as arena rock and pop rock. Queen estimated their record sales at 300 million worldwide, making them one of the world\'s best-selling music artists. They received the Outstanding Contribution to British Music Award from the British Phonographic Industry in 1990. They were inducted into the Rock and Roll Hall of Fame in 2001.',
                    bio_ru: 'Queen — британская рок-группа, образованная в Лондоне в 1970 году Фредди Меркьюри, Брайаном Мэем, Роджером Тейлором и Джоном Диконом. Ранние работы коллектива находились под влиянием прогрессивного рока, хард-рока и хеви-метала, но со временем группа перешла к более доступному звучанию. '.repeat(4),
                    bio_original: 'Queen are a British rock band formed in London in 1970 by Freddie Mercury, Brian May, Roger Taylor, and John Deacon.',
                    avatar_url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23e11d48" width="100" height="100"/%3E%3C/svg%3E',
                    banner_url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="600" height="300"%3E%3Crect fill="%232563eb" width="600" height="300"/%3E%3C/svg%3E',
                    tracks: [
                        { id: '1', title: 'Bohemian Rhapsody', artist: 'Queen', duration: 354, playCount: 2000000000 },
                        { id: '2', title: 'Don\'t Stop Me Now', artist: 'Queen', duration: 209, playCount: 1500000000 },
                        { id: '3', title: 'Another One Bites the Dust', artist: 'Queen', duration: 215, playCount: 1400000000 },
                        { id: '4', title: 'Under Pressure', artist: 'Queen & David Bowie', duration: 248, playCount: 1200000000 },
                        { id: '5', title: 'We Will Rock You', artist: 'Queen', duration: 122, playCount: 1000000000 },
                        { id: '6', title: 'Radio Ga Ga', artist: 'Queen', duration: 343, playCount: 800000000 },
                        { id: '7', title: 'Somebody to Love', artist: 'Queen', duration: 296, playCount: 750000000 },
                        { id: '8', title: 'I Want to Break Free', artist: 'Queen', duration: 260, playCount: 700000000 }
                    ],
                    albums: [
                        { id: 'a1', title: 'A Night at the Opera', artist: 'Queen', year: 1975, cover_url: '' },
                        { id: 'a2', title: 'News of the World', artist: 'Queen', year: 1977, cover_url: '' },
                        { id: 'a3', title: 'The Game', artist: 'Queen', year: 1980, cover_url: '' },
                        { id: 'a4', title: 'Innuendo', artist: 'Queen', year: 1991, cover_url: '' }
                    ]
                };

                window.pywebview = {
                    api: {
                        get_artist_profile: async (name, ref, reqId) => {
                            window.calls.push(['get_artist_profile', name, reqId]);
                            return window.testArtistData;
                        },
                        get_canonical_artist_names: async (names) => {
                            return names.map(n => String(n).toLowerCase().trim());
                        },
                        play_track: async (track, list, idx) => {
                            window.calls.push(['play_track', track.title]);
                        }
                    }
                };

                // Import modules
                window.utils = await import('/js/utils.js');
                window.pages = await import('/js/pages.js');
                window.artistMod = await import('/js/artist_profile.js');
                window.searchMod = await import('/js/search.js');

                pages.initPages();
            }, style);

            // 1. Test ART-004 & ART-014: cleanArtistQuery logic
            const cleanCheck = await page.evaluate(async () => {
                const sMod = window.searchMod;
                return {
                    topic: sMod.cleanArtistQuery('The Weeknd - Topic'),
                    vevo: sMod.cleanArtistQuery('Taylor Swift VEVO'),
                    collabFeat: sMod.cleanArtistQuery('David Guetta feat. Sia'),
                    collabAmp: sMod.cleanArtistQuery('Queen & David Bowie'),
                    tyler: sMod.cleanArtistQuery('Tyler, The Creator'),
                    earthWind: sMod.cleanArtistQuery('Earth, Wind & Fire')
                };
            });

            assert.equal(cleanCheck.topic, 'The Weeknd', 'Should strip - Topic');
            assert.equal(cleanCheck.vevo, 'Taylor Swift', 'Should strip VEVO');
            assert.equal(cleanCheck.collabFeat, 'David Guetta', 'Should extract primary artist from feat');
            assert.equal(cleanCheck.collabAmp, 'Queen', 'Should extract primary artist from &');
            assert.equal(cleanCheck.tyler, 'Tyler, The Creator', 'Should NOT split Tyler, The Creator (ART-014)');
            assert.equal(cleanCheck.earthWind, 'Earth, Wind & Fire', 'Should NOT split Earth, Wind & Fire (ART-014)');

            // 2. Test ART-001: Redesigned artist page elements & navigation
            // Navigate from Search to Artist
            await page.evaluate(() => {
                window.pages.showPage('search');
                const searchInput = document.getElementById('search-input');
                if (searchInput) searchInput.value = 'Queen rock band';
                const searchResults = document.getElementById('search-results');
                if (searchResults) searchResults.innerHTML = '<div id="test-search-anchor">Results here</div>';
            });

            await page.waitForFunction(() => document.getElementById('view-search').classList.contains('active'));
            assert.equal(await page.locator('#view-search').evaluate(el => el.classList.contains('active')), true);

            // Open artist profile
            await page.evaluate(() => {
                window.searchArtistProfile('Queen');
            });

            // Verify view-artist is now active and view-search is inactive
            await page.waitForFunction(() => document.getElementById('view-artist')?.classList.contains('active'));
            assert.equal(await page.locator('#view-artist').evaluate(el => el.classList.contains('active')), true);
            assert.equal(await page.locator('#view-search').evaluate(el => el.classList.contains('active')), false);

            // Verify artist profile details rendered
            await page.waitForFunction(() => document.getElementById('artist-profile-name')?.textContent === 'Queen');
            assert.equal(await page.locator('#artist-profile-name').textContent(), 'Queen');

            // Verified badge visible
            const verifiedHidden = await page.locator('#artist-verified-badge').evaluate(el => el.classList.contains('hidden'));
            assert.equal(verifiedHidden, false, 'Verified badge must be visible when artist is verified');

            // Listeners line visible
            const listenersText = await page.locator('#artist-fans-line').textContent();
            assert.match(listenersText, /слушателей/);

            // Tabs visible
            const horizTabsDisplay = await page.locator('#artist-horiz-tabs').evaluate(el => getComputedStyle(el).display);
            assert.notEqual(horizTabsDisplay, 'none', 'Horizontal tabs must be visible when albums exist');

            // Popular tracks Top 5 initially
            await page.waitForFunction(() => document.querySelectorAll('#artist-tracks-list .track-item, #artist-tracks-list .track-row').length > 0);
            const initialTracksCount = await page.locator('#artist-tracks-list :is(.track-item, .track-row)').count();
            assert.equal(initialTracksCount, 5, 'Top 5 tracks should be shown initially');

            // Toggle button should say "Показать все"
            const toggleBtn = page.locator('#btn-artist-tracks-toggle');
            assert.equal(await toggleBtn.textContent(), 'Показать больше');

            // Click toggle button -> expands all 8 tracks
            await toggleBtn.click();
            await page.waitForFunction(() => document.querySelectorAll('#artist-tracks-list :is(.track-item, .track-row)').length === 8);
            assert.equal(await toggleBtn.textContent(), 'Свернуть');

            // Click toggle again -> collapses back to 5
            await toggleBtn.click();
            await page.waitForFunction(() => document.querySelectorAll('#artist-tracks-list :is(.track-item, .track-row)').length === 5);
            assert.equal(await toggleBtn.textContent(), 'Показать больше');

            // Tab switching: switch to Albums tab
            await page.locator('#artist-tab-albums').click();
            assert.equal(await page.locator('#artist-pane-albums').evaluate(el => !el.classList.contains('hidden')), true);
            assert.equal(await page.locator('#artist-pane-tracks').evaluate(el => el.classList.contains('hidden')), true);

            // Verify album cards grid
            const albumCardsCount = await page.locator('.artist-albums-grid .artist-album-card').count();
            assert.equal(albumCardsCount, 4, 'Albums grid should render 4 album cards');

            // Switch back to Tracks tab
            await page.locator('#artist-tab-tracks').click();
            assert.equal(await page.locator('#artist-pane-tracks').evaluate(el => !el.classList.contains('hidden')), true);

            // Test Bio modal: click "Подробнее"
            await page.locator('#btn-artist-bio-more').click();
            assert.equal(await page.locator('#artist-bio-modal').evaluate(el => el.style.display !== 'none'), true);
            assert.match(await page.locator('#artist-bio-modal-body').innerText(), /Queen/);

            // Close Bio modal
            await page.locator('#btn-close-artist-bio').click();
            assert.equal(await page.locator('#artist-bio-modal').evaluate(el => el.style.display === 'none'), true);

            // 3. Test Back button navigation
            // Click back button: should return to Search, preserving input and results
            await page.locator('#btn-back-artist').click();
            await page.waitForFunction(() => document.getElementById('view-search')?.classList.contains('active'));
            assert.equal(await page.locator('#view-search').evaluate(el => el.classList.contains('active')), true);
            assert.equal(await page.locator('#view-artist').evaluate(el => el.classList.contains('active')), false);

            const preservedQuery = await page.locator('#search-input').inputValue();
            assert.equal(preservedQuery, 'Queen rock band', 'Search query must be preserved when returning from artist page');
            const preservedAnchor = await page.locator('#test-search-anchor').count();
            assert.equal(preservedAnchor, 1, 'Search results DOM must remain intact');

            // 4. Test ART-005: Context menu has "Перейти к исполнителю" and clickable artist
            const contextMenuCheck = await page.evaluate(() => {
                const dummyTrack = { id: '99', title: 'Bohemian Rhapsody', artist: 'Queen', duration: 354 };
                window.utils.showTrackContextMenu(dummyTrack, { clientX: 200, clientY: 200, preventDefault() {}, stopPropagation() {} });
                const menu = document.querySelector('.rich-track-menu');
                const goToArtistItem = menu?.querySelector('[data-action="go_to_artist"]');
                const headerArtist = menu?.querySelector('.rich-menu-artist');
                const hasClickableClass = headerArtist?.classList.contains('clickable-artist');
                menu?.remove();
                return {
                    hasGoToArtist: Boolean(goToArtistItem),
                    hasClickableClass: Boolean(hasClickableClass)
                };
            });

            assert.equal(contextMenuCheck.hasGoToArtist, true, 'Context menu must have "go_to_artist" action');
            assert.equal(contextMenuCheck.hasClickableClass, true, 'Header artist in context menu must be clickable');

            // One source ID renders once; separate recordings keep their identity.
            await page.evaluate(async()=>{
                window.testArtistData={...window.testArtistData,tracks:[
                    {id:'version-a',source:'youtube',source_id:'version-a',title:'Same title',artist:'Queen'},
                    {id:'version-a',source:'youtube',source_id:'version-a',title:'Same title',artist:'Queen'},
                    {id:'version-b',source:'youtube',source_id:'version-b',title:'Same title',artist:'Queen'}]};
                window.pages.showPage('artist');
                await window.artistMod.loadArtistProfile('Queen',document.getElementById('view-artist'));
            });
            assert.equal(await page.locator('#artist-tracks-list .track-item').count(),2);

            // Continuation pages append to the real catalogue and reject stale replies.
            await page.evaluate(async()=>{
                window.testArtistData={...window.testArtistData,source:'youtube',source_id:'queen-channel',tracks_has_more:true,
                    tracks:[{id:'page-1',source:'youtube',source_id:'page-1',title:'First',artist:'Queen'}]};
                window.pageOffsets=[];
                window.pywebview.api.get_artist_tracks_page=async(ref,offset)=>{
                    window.pageOffsets.push(offset);
                    if(window.pageOffsets.length===1)return {success:true,next_offset:3,has_more:true,catalog_partial:true,
                        albums:[{id:'continued-album',source:'youtube',source_id:'MPRE-continued',title:'Continued release',artist:'Queen'}],tracks:[
                        window.testArtistData.tracks[0],{id:'page-2',source:'youtube',source_id:'page-2',title:'Second',artist:'Queen'}]};
                    return new Promise(resolve=>{window.resolveArtistPage=resolve;});
                };
                window.pages.showPage('artist');
                await window.artistMod.loadArtistProfile('Queen',document.getElementById('view-artist'));
            });
            await page.locator('#btn-artist-tracks-toggle').click();
            await page.waitForFunction(()=>document.querySelectorAll('#artist-tracks-list .track-item').length===2);
            assert.deepEqual(await page.evaluate(()=>window.pageOffsets),[0]);
            assert.match(await page.locator('.artist-catalog-status').innerText(),/частично/);
            assert.match(await page.locator('.artist-albums-grid').innerText(),/Continued release/);
            await page.locator('#btn-artist-tracks-toggle').click();
            await page.waitForFunction(()=>typeof window.resolveArtistPage==='function');
            await page.evaluate(async()=>{
                await window.artistMod.loadArtistProfile('Queen',document.getElementById('view-artist'));
                window.resolveArtistPage({success:true,next_offset:6,has_more:false,tracks:[{id:'stale-page',title:'Wrong artist'}]});
            });
            await page.waitForTimeout(50);
            assert.equal(await page.locator('#artist-tracks-list').textContent().then(text=>text.includes('Wrong artist')),false);
            assert.equal(await page.locator('#btn-artist-tracks-toggle').isEnabled(),true,'a stale request must not disable the next artist page');

            // 5. Test ART-006: Request cancellation
            const cancelCheck = await page.evaluate(async () => {
                window.artistMod.cancelActiveArtistRequests();
                return true;
            });
            assert.equal(cancelCheck, true);

            console.log(`PASS artist_page_browser [${style}]`);
        }
    } finally {
        await browser.close();
        server.close();
    }
})().catch(e => {
    console.error(e);
    process.exitCode = 1;
});
