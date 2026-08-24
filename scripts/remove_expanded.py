import re
with open('ui/web_new/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('repeat(3, 1fr)', 'repeat(2, 1fr)')

# Remove expanded block in Settings
pattern = re.compile(r'<div class="opt-card" data-val="expanded".*?</div>\s*</div>', re.DOTALL)
text = pattern.sub('</div>', text)

with open('ui/web_new/index.html', 'w', encoding='utf-8') as f:
    f.write(text)
