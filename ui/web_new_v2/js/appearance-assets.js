// Local artwork catalog shared by first paint, settings and the macOS pack.
// Source and checksums: assets/backgrounds/SOURCES.json.
(() => {
    const photos = new Set(["photo-1448375240586-882707db888b", "photo-1451187580459-43490279c0fa", "photo-1464822759023-fed622ff2c3b", "photo-1470071459604-3b5ec3a7fe05", "photo-1470770841072-f978cf4d019e", "photo-1500534314209-a25ddb2bd429", "photo-1501785888041-af3ef285b470", "photo-1503899036084-c55cdd92da26", "photo-1507525428034-b723cf961d3e", "photo-1508739773434-c26b3d09e071", "photo-1509114397022-ed747cca3f65", "photo-1511497584788-876760111969", "photo-1518709268805-4e9042af9f23", "photo-1518837695005-2083093ee35b", "photo-1519681393784-d120267933ba", "photo-1522383225653-ed111181a951", "photo-1526374965328-7f61d4dc18c5", "photo-1531366936337-7c912a4589a7", "photo-1532767153582-b1a0e5145009", "photo-1534447677768-be436bb09401", "photo-1542751371-adc38448a05e", "photo-1550745165-9bc0b252726f", "photo-1563089145-599997674d42", "photo-1578632767115-351597cf2477", "photo-1607604276583-eef5d076aa5f", "photo-1618005182384-a83a8bd57fbe", "photo-1627856013091-fed6e4e30025"]);
    const themes = {
    "dark": "1448375240586-882707db888b",
    "amoled": "1519681393784-d120267933ba",
    "midnight": "1534447677768-be436bb09401",
    "sky": "1507525428034-b723cf961d3e",
    "mint": "1511497584788-876760111969",
    "violet": "1531366936337-7c912a4589a7",
    "blossom": "1522383225653-ed111181a951",
    "sakura": "1522383225653-ed111181a951",
    "terminal": "1526374965328-7f61d4dc18c5",
    "sand": "1500534314209-a25ddb2bd429",
    "aqua": "1501785888041-af3ef285b470",
    "sunset": "1508739773434-c26b3d09e071",
    "slate": "1470071459604-3b5ec3a7fe05",
    "neutral": "1464822759023-fed622ff2c3b",
    "crimson": "1532767153582-b1a0e5145009",
    "dracula": "1563089145-599997674d42",
    "nord": "1470770841072-f978cf4d019e",
    "rose": "1522383225653-ed111181a951",
    "emerald": "1448375240586-882707db888b",
    "amber": "1500534314209-a25ddb2bd429",
    "lavender": "1519681393784-d120267933ba",
    "ocean": "1518837695005-2083093ee35b"
};
    const localPath = id => `assets/backgrounds/${id}.webp`;
    const localizeLegacyPath = value => {
        const match = value.match(/^assets\/backgrounds\/(photo-[\w-]+)\.jpe?g$/i);
        return match && photos.has(match[1]) ? localPath(match[1]) : value;
    };
    function resolveBackground(value) {
        if (typeof value !== 'string') return '';
        const original = value.trim();
        if (!/^https?:/i.test(original)) return localizeLegacyPath(original);
        try {
            let url = new URL(original);
            if (url.hostname === 'wsrv.nl' || url.hostname === 'www.wsrv.nl') {
                url = new URL(url.searchParams.get('url') || original);
            }
            if (url.hostname !== 'images.unsplash.com') return original;
            let id = url.pathname.slice(1);
            // This old built-in forest URL is a permanent 404.
            if (id === 'photo-1511497584788-876761c1298b') id = 'photo-1511497584788-876760111969';
            return photos.has(id) ? localPath(id) : original;
        } catch { return original; }
    }
    window.NeDotifyAssets = Object.freeze({
        resolveBackground,
        themeBackgroundPath: id => themes[id] ? localPath(`photo-${themes[id]}`) : '',
        backgroundPaths: Object.freeze([...photos].map(localPath))
    });
})();
