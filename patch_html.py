with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

old = '<div class="setting-sublabel">Секрет клиента для API YouTube Data v3</div>'
new = '<div class="setting-sublabel">Секрет клиента для API YouTube Data v3 <span style="opacity:0.75;font-size:11px;">(⚠️ Client Secret не отправляется с фронтенда)</span></div>'

if old in content:
    content = content.replace(old, new)
    with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Pattern not found")
