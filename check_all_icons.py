import re

with open('ui/web_new/js/lucide.min.js', 'r', encoding='utf-8') as f:
    content = f.read()

keys = re.findall(r"'([a-z0-9-]+)':", content)
print("All 68 icons in lucide.min.js:")
print(keys)
