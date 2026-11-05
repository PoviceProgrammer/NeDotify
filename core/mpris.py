"""MPRIS 2.2 interfaces (positions are microseconds on D-Bus).

The frontend owns audible HTML5 transport. Remote controls use its registered
system-media events instead of starting a second Python audio player.
"""
from dbus_next import Variant
from dbus_next.constants import PropertyAccess
from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface, dbus_property, method, signal


def create_interfaces(desktop):
    class Root(ServiceInterface):
        def __init__(self):
            super().__init__('org.mpris.MediaPlayer2')

        @method()
        def Raise(self):
            desktop.dispatch('raise')

        @method()
        def Quit(self):
            desktop.dispatch('quit')

        @dbus_property(access=PropertyAccess.READ)
        def CanQuit(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanRaise(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def HasTrackList(self) -> 'b':
            return False

        @dbus_property(access=PropertyAccess.READ)
        def Identity(self) -> 's':
            return 'NeDotify'

        @dbus_property(access=PropertyAccess.READ)
        def DesktopEntry(self) -> 's':
            return 'nedotify'

        @dbus_property(access=PropertyAccess.READ)
        def SupportedUriSchemes(self) -> 'as':
            # OpenUri is not advertised: tracks enter through the audited
            # provider resolver/library rather than arbitrary filesystem URIs.
            return []

        @dbus_property(access=PropertyAccess.READ)
        def SupportedMimeTypes(self) -> 'as':
            return []

    class Player(ServiceInterface):
        def __init__(self):
            super().__init__('org.mpris.MediaPlayer2.Player')

        @method()
        def Next(self):
            desktop.dispatch('next')

        @method()
        def Previous(self):
            desktop.dispatch('prev')

        @method()
        def Pause(self):
            desktop.dispatch('pause')

        @method()
        def PlayPause(self):
            desktop.dispatch('toggle_play')

        @method()
        def Stop(self):
            desktop.dispatch('stop')

        @method()
        def Play(self):
            desktop.dispatch('play')

        @method()
        def Seek(self, Offset: 'x'):
            snapshot = desktop.snapshot()
            target = max(0, snapshot['position'] + Offset)
            if snapshot['duration']:
                target = min(target, snapshot['duration'])
            desktop.dispatch('seek', target / 1000)
            self.Seeked(target)

        @method()
        def SetPosition(self, TrackId: 'o', Position: 'x'):
            snapshot = desktop.snapshot()
            if TrackId != snapshot['track_id'] or Position < 0:
                return
            if snapshot['duration'] and Position > snapshot['duration']:
                return
            desktop.dispatch('seek', Position / 1000)
            self.Seeked(Position)

        @method()
        def OpenUri(self, Uri: 's'):
            raise DBusError('org.mpris.MediaPlayer2.Player.Error.NotSupported', 'Import tracks in the NeDotify library')

        @signal()
        def Seeked(self, Position: 'x') -> 'x':
            return Position

        @dbus_property(access=PropertyAccess.READ)
        def PlaybackStatus(self) -> 's':
            return desktop.snapshot()['state']

        @dbus_property()
        def LoopStatus(self) -> 's':
            return {'off': 'None', 'all': 'Playlist', 'one': 'Track'}.get(desktop.snapshot()['repeat'], 'None')

        @LoopStatus.setter
        def LoopStatus(self, value: 's'):
            if value not in ('None', 'Playlist', 'Track'):
                raise DBusError('org.freedesktop.DBus.Error.InvalidArgs', 'Invalid loop mode')
            for _ in range(3):
                if self.LoopStatus == value:
                    break
                desktop.api.toggle_repeat()

        @dbus_property()
        def Rate(self) -> 'd':
            return 1.0

        @Rate.setter
        def Rate(self, value: 'd'):
            if value != 1.0:
                raise DBusError('org.freedesktop.DBus.Error.NotSupported', 'Playback rate is fixed at 1.0')

        @dbus_property()
        def Shuffle(self) -> 'b':
            return desktop.snapshot()['shuffle']

        @Shuffle.setter
        def Shuffle(self, value: 'b'):
            if self.Shuffle != value:
                desktop.api.toggle_shuffle()

        @dbus_property(access=PropertyAccess.READ)
        def Metadata(self) -> 'a{sv}':
            snapshot = desktop.snapshot()
            track = snapshot['track']
            if not track:
                return {'mpris:trackid': Variant('o', '/org/mpris/MediaPlayer2/TrackList/NoTrack')}
            data = {'mpris:trackid': Variant('o', snapshot['track_id']),
                    'mpris:length': Variant('x', snapshot['duration']),
                    'xesam:title': Variant('s', str(track.get('title') or '')),
                    'xesam:artist': Variant('as', [str(track.get('artist') or '')]),
                    'xesam:album': Variant('s', str(track.get('album') or ''))}
            cover = track.get('cover_url')
            if isinstance(cover, str) and cover.startswith(('https://', 'http://')) and '127.0.0.1' not in cover:
                data['mpris:artUrl'] = Variant('s', cover)
            return data

        @dbus_property()
        def Volume(self) -> 'd':
            return float(desktop.snapshot()['volume'])

        @Volume.setter
        def Volume(self, value: 'd'):
            import math
            if not math.isfinite(value):
                raise DBusError('org.freedesktop.DBus.Error.InvalidArgs', 'Invalid volume')
            desktop.dispatch('volume', round(max(0.0, min(1.0, value)) * 100))

        @dbus_property(access=PropertyAccess.READ)
        def Position(self) -> 'x':
            return desktop.snapshot()['position']

        @dbus_property(access=PropertyAccess.READ)
        def MinimumRate(self) -> 'd':
            return 1.0

        @dbus_property(access=PropertyAccess.READ)
        def MaximumRate(self) -> 'd':
            return 1.0

        @dbus_property(access=PropertyAccess.READ)
        def CanGoNext(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanGoPrevious(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanPlay(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanPause(self) -> 'b':
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanSeek(self) -> 'b':
            return bool(desktop.snapshot()['duration'])

        @dbus_property(access=PropertyAccess.READ)
        def CanControl(self) -> 'b':
            return True

        def properties(self):
            return {name: getattr(self, name) for name in (
                'PlaybackStatus', 'Metadata', 'LoopStatus', 'Shuffle', 'Volume', 'CanSeek')}

    return Root(), Player()
