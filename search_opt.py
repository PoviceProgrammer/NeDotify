import re

with open('ui/web_new/index.html', 'r', encoding='utf-8') as f:
    for line in f:
        if 'id="opt-' in line:
            print(line.strip())
