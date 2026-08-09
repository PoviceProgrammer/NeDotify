import json

with open(r"C:\Users\valee\.gemini\antigravity\brain\4b14d8dd-c431-49a6-829f-e0678c651b0d\.system_generated\logs\transcript_full.jsonl", "r", encoding="utf-8") as f:
    for line in reversed(list(f)):
        try:
            data = json.loads(line)
            if data.get("type") == "USER_INPUT":
                with open("prompt10.txt", "w", encoding="utf-8") as out:
                    out.write(data["content"])
                break
        except: pass
