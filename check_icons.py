import re

with open('ui/web_new/js/lucide.min.js', 'r', encoding='utf-8') as f:
    content = f.read()

keys = re.findall(r"'([a-z0-9-]+)':", content)
print("Total icons:", len(keys))
print("Icons containing 'top', 'bottom', 'left', 'right', 'square', 'move', 'arrow', 'layout', 'align':")
matching = [k for k in keys if any(x in k for x in ['top', 'bottom', 'left', 'right', 'square', 'move', 'arrow', 'layout', 'align', 'expand', 'maximize'])]
print(matching)
