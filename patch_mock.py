import re

with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/js/artist_profile.js', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('const MOCK_ARTISTS = {', '// TODO: Replace this mock data with backend API calls once the backend implements artist profiles\nconst MOCK_ARTISTS = {')

with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/js/artist_profile.js', 'w', encoding='utf-8') as f:
    f.write(content)
