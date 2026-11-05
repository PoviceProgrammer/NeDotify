// Compatibility names also stay coherent during an optimistic UI update.
// The backend owns durable aliasing; a single bridge call persists the group.
const groups = [
    [['audio', 'crossfade_duration_sec'], ['audio', 'crossfade_duration']],
    [['atmosphere', 'enabled'], ['ui', 'particles_enabled'], ['optimization', 'resource_particles']],
    [['ui', 'cover_visualizer'], ['optimization', 'resource_visualizers']],
    [['general', 'autostart'], ['app', 'autostart']],
    [['theme', 'theme_mode'], ['theme', 'mode']],
    ...['theme', 'name', 'accent_color', 'transparency_enabled', 'transparency_level',
        'glass_blur', 'glass_color_intensity', 'custom_themes', 'font_family']
        .map(key => [['theme', key], ['interface', key]]),
];

export function settingAliases(category, key) {
    return groups.find(group => group.some(([cat, name]) => cat === category && name === key)) || [[category, key]];
}
