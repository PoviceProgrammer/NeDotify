import re

with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/js/main.js', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('updateBatteryStatus(); // Initial call\n                });', 'updateBatteryStatus(); // Initial call\n                }).catch(err => { console.log(\'Battery API not available:\', err); });')

with open('c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/js/main.js', 'w', encoding='utf-8') as f:
    f.write(content)
