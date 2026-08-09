import json

with open('C:/Users/valee/.gemini/antigravity/brain/87363e1a-d5dd-4f22-8ed3-11e6a5252928/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    lines = f.readlines()

inputs = []
for line in lines:
    try:
        obj = json.loads(line)
        if obj.get('type') == 'USER_INPUT':
            inputs.append(obj.get('content', ''))
    except Exception as e:
        pass

with open('user_prompts_full.md', 'w', encoding='utf-8') as f:
    for inp in inputs:
        if 'PRIORITY' in inp:
            f.write('\n=== USER_INPUT ===\n' + inp + '\n')
