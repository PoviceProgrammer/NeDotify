"""The explicit JavaScript bridge surface for the desktop UI."""
import logging

logger = logging.getLogger(__name__)

PUBLIC_METHODS = frozenset({
    'get_personal_wave',
    'replace_personal_wave_tail',
    'get_setup_status',
    'repair_setup_tools',
    'cancel_setup',
    'configure_setup',
    'check_for_updates',
    'check_setup_updates',
    'select_setup_directory',
    'cancel_download',
    'retry_download',
    'download_tracks',
    'download_playlist',
    'clear_listening_history',
    'import_music_folder',
    'add_to_playlist',
    'add_to_queue',
    'add_tracks_to_queue',
    'begin_window_drag',
    'begin_window_resize',
    'cancel_batch_download',
    'cancel_search',
    'check_zapret_update',
    'choose_cover_image',
    'clear_queue',
    'clear_storage_cache',
    'close',
    'close_window',
    'complete_onboarding',
    'create_local_playlist',
    'create_playlist',
    'delete_duplicate_track',
    'delete_playlist',
    'download_all_favorites',
    'download_track',
    'export_playlist',
    'fetch_missing_covers',
    'frontend_heartbeat',
    'find_duplicate_tracks',
    'get_album_details',
    'get_app_version',
    'get_artist_profile',
    'get_artist_tracks_page',
    'get_canonical_artist_names',
    'get_artists_avatars',
    'get_discord_rpc_status',
    'get_downloaded_tracks',
    'get_downloads',
    'get_equalizer',
    'get_favorites',
    'get_feed',
    'get_home_artists',
    'get_home_data',
    'get_home_mixes',
    'get_home_releases',
    'get_library',
    'get_library_summary',
    'get_listening_comparison',
    'get_lyrics',
    'get_lyrics_translation',
    'search_lyrics',
    'apply_lyrics_candidate',
    'save_custom_lyrics',
    'delete_custom_lyrics',
    'get_lyrics_display_settings',
    'save_lyrics_display_settings',
    'get_next_track',
    'get_offline_library',
    'get_playlist_tracks',
    'get_playlist_recommendations',
    'get_playlists',
    'get_popular_tracks',
    'get_profile_stats',
    'get_proxy_info',
    'get_queue',
    'get_recommendation_feedback',
    'get_recommendation_collection',
    'get_search_suggestions',
    'get_settings',
    'get_settings_by_category',
    'get_storage_info',
    'get_track_info',
    'get_volume',
    'get_track_wave',
    'get_waveform',
    'get_wrapped_stats',
    'get_zapret_status',
    'import_external_playlist',
    'is_muted',
    'maximize',
    'minimize',
    'minimize_window',
    'next_track',
    'open_local_file',
    'open_release_page',
    'pause_download',
    'play_next',
    'play_pause',
    'play_track',
    'prefetch_track',
    'prev_track',
    'recover_stream',
    'remove_artist_alias',
    'remove_artist_binding',
    'remove_from_queue',
    'remove_from_playlist',
    'rename_playlist',
    'reorder_queue',
    'report_listening_state',
    'report_recommendation_impression',
    'report_position',
    'report_state',
    'resume_download',
    'retry_failed_downloads',
    'save_setting',
    'search',
    'select_avatar',
    'set_artist_alias',
    'set_cache_quota',
    'set_equalizer',
    'set_mini_player_position',
    'set_recommendation_feedback',
    'set_recommendation_collection',
    'set_snap_button_rect',
    'set_volume',
    'toggle_discord_rpc',
    'toggle_favorite',
    'toggle_fullscreen',
    'toggle_mini_player',
    'toggle_mute',
    'toggle_repeat',
    'toggle_shuffle',
    'toggle_zapret',
    'ui_ready',
    'update_track_tags',
    'update_zapret',
})
_INTERNAL_METHODS = frozenset({'pywebviewMoveWindow', 'pywebviewEventHandler', 'pywebviewAsyncCallback'})


class BridgeApi:
    def __init__(self, api):
        self._methods = {name: getattr(api, name) for name in PUBLIC_METHODS if hasattr(api, name)}

    def __dir__(self):
        return sorted(self._methods)

    def __getattr__(self, name):
        try:
            return self._methods[name]
        except KeyError:
            raise AttributeError(name) from None


def install_bridge_guard():
    """Reject undeclared/nested calls before pywebview traverses Python objects."""
    import webview.util
    current = webview.util.js_bridge_call
    if getattr(current, '_nedotify_guard', False):
        return
    def guarded(window, func_name, param, value_id):
        if isinstance(getattr(window, '_js_api', None), BridgeApi):
            if func_name not in PUBLIC_METHODS and func_name not in _INTERNAL_METHODS:
                logger.warning('Rejected undeclared bridge method')
                return
        return current(window, func_name, param, value_id)
    guarded._nedotify_guard = True
    webview.util.js_bridge_call = guarded
