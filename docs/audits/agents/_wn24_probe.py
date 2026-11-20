import sys, os, json, tempfile
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from services.catalog_service import credited_to
from services.music_matching import artist_matches, credits

def show(label, val):
    print(f"{label}: {val!r}")

print("=== credited_to / artist_matches asymmetry ===")
cases = [
    ("simple same name",        {'artists': [{'name': 'Artist'}]},            'Artist',            ''),
    ("same name with &",        {'artists': [{'name': 'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire',''),
    ("same name with comma",    {'artists': [{'name': 'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire',''),
    ("feat in name",            {'artists': [{'name': 'Artist feat. Guest'}]}, 'Artist feat. Guest',''),
    ("wanted collab vs offered",{'artists': [{'name': 'Artist'},{'name':'Guest'}]}, 'Artist feat. Guest',''),
    ("wanted list vs offered",  {'artists': [{'name': 'Artist feat. Guest'}]}, 'Artist feat. Guest',''),
    ("collab offered",          {'artists': [{'name': 'Artist & Other'}]},    'Artist',            ''),
    ("band with comma",         {'artists': [{'name': 'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire','UCx'),
    ("x artist",                {'artists': [{'name': 'Artist X'}]},          'X',                 ''),
]
for label, item, name, ch in cases:
    print(f"{label:28s} credited_to={credited_to(item, name, ch)!s:6s} "
          f"artist_matches={artist_matches(name, item['artists'])}")

print()
print("credits('Earth, Wind & Fire') =", credits('Earth, Wind & Fire'))
print("credits([{'name':'Earth, Wind & Fire'}]) =", credits([{'name':'Earth, Wind & Fire'}]))
print("credits('Artist feat. Guest') =", credits('Artist feat. Guest'))
print("credits([{'name':'Artist feat. Guest'}]) =", credits([{'name':'Artist feat. Guest'}]))

print()
print("=== catalog album_details artist gate (simulated) ===")
people = [{'name': 'Earth, Wind & Fire'}]
artist = 'Earth, Wind & Fire'
print("artist_matches(album.artist, yt people) ->", artist_matches(artist, people))
print("=> album rejected?", bool(artist and not artist_matches(artist, people)))
