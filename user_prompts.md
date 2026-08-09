
=== USER_INPUT ===
<USER_REQUEST>
# РОЛЬ И КОНТЕКСТ
Ты — Staff Release Engineer и Security Architect для десктопного музыкального приложения AURA Music (Python/PyWebView/JS). 
Текущая оценка готовности к релизу: 68/100. Цель: 90+/100.
У тебя ОДИН заход. Никаких "предложи сделать" — только ГОТОВЫЙ КОД, патчи, миграции и чёткие diff-блоки.
Если не уверен в точных номерах строк — пиши "// TODO: verify line X", но логику выдавай полностью.

================================================================
# PRIORITY 0: RELEASE BLOCKERS (Критично, ломают UX у 100% юзеров)
================================================================

## 0.1 License Server Co-launch (main.py, core/api.py)
ПРОБЛЕМА: ui/web_new/js/main.js:191-201 блокирует ВЕСЬ UI при невалидном ключе. Сервер лицензий (vk_bot.py на 127.0.0.1:5000) не стартует из main.py. Новый юзер без ключа не попадает в приложение.
ЗАДАЧА:
1. Написать `core/license_server.py` — встроенный Flask/WSGI сервер в отдельном daemon-потоке (threading.Thread с daemon=True), который стартует вместе с AppCore. Он должен держать endpoint `/api/validate_key` и отдавать подписи.
2. Добавить в main.py graceful fallback: если сервер не поднялся — запускаем VK-бот как subprocess.Popen.
3. Реализовать OFFLINE GRACE PERIOD (7 дней): в core/api.py:1198 добавить проверку локальной SQLite таблицы `license_cache` (ключ, timestamp, signature). Если нет сети — пускаем юзера, если прошло < 7 дней с последней валид
<truncated 7353 bytes>
о отключить переключатель в UI с пометкой "только при запуске".

================================================================
# PRIORITY 3: CLEANUP (Обязательно перед релизом)
================================================================

## 3.1 Удалить из репозитория (список файлов):
- Вся папка `scripts/` (bash-патчеры, устаревший мусор)
- `check_*.py` в корне
- `regex_keydown.py`, `remove_keydown.py`
- Папка `ui/web/` (полный дубликат web_new, активна только web_new)
- Добавить в .gitignore: `.env`, `*.pyc`, `__pycache__/`, `.venv/`, `*.db` (если БД локальная)

## 3.2 Security Hardening
- Добавить User Agreement checkbox перед первым использованием cookiesfrombrowser (implicit PII).
- HMAC-ключ NEDOTIFY_SECRET_SIGNATURE_KEY вынести на серверную сторону (если архитектура позволяет). Если нет — хотя бы обфусцировать через base64 + XOR в коде (не панацея, но поднимет порог входа).

================================================================
# ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)
================================================================

Для каждого затронутого файла выдай:

### 📄 `путь/к/файлу.py`
```diff
- удаляемая строка
+ добавляемая строка
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-08-06T13:23:51+03:00.
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from Gemini 3.6 Flash (High) to Claude Opus 4.6 (Thinking). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>

=== USER_INPUT ===
<USER_REQUEST>
/teamwork-preview # РОЛЬ И КОНТЕКСТ
Ты — Staff Release Engineer и Security Architect для десктопного музыкального приложения AURA Music (Python/PyWebView/JS). 
Текущая оценка готовности к релизу: 68/100. Цель: 90+/100.
У тебя ОДИН заход. Никаких "предложи сделать" — только ГОТОВЫЙ КОД, патчи, миграции и чёткие diff-блоки.
Если не уверен в точных номерах строк — пиши "// TODO: verify line X", но логику выдавай полностью.

================================================================
# PRIORITY 0: RELEASE BLOCKERS (Критично, ломают UX у 100% юзеров)
================================================================

## 0.1 License Server Co-launch (main.py, core/api.py)
ПРОБЛЕМА: ui/web_new/js/main.js:191-201 блокирует ВЕСЬ UI при невалидном ключе. Сервер лицензий (vk_bot.py на 127.0.0.1:5000) не стартует из main.py. Новый юзер без ключа не попадает в приложение.
ЗАДАЧА:
1. Написать `core/license_server.py` — встроенный Flask/WSGI сервер в отдельном daemon-потоке (threading.Thread с daemon=True), который стартует вместе с AppCore. Он должен держать endpoint `/api/validate_key` и отдавать подписи.
2. Добавить в main.py graceful fallback: если сервер не поднялся — запускаем VK-бот как subprocess.Popen.
3. Реализовать OFFLINE GRACE PERIOD (7 дней): в core/api.py:1198 добавить проверку локальной SQLite таблицы `license_cache` (ключ, timestamp, signature). Если нет сети — пускаем юзера, если прошло < 7 дней с послед
<truncated 18615 bytes>
human judgment
- [ ] Requirements scoped by user needs, not by what the agent "should" do
- [ ] Infrastructure constraints clearly state what's controlled and why
- [ ] A skilled engineer would NOT feel over-constrained
- [ ] An agent could NOT trivially self-certify a half-baked result

Present final prompt to user. Ask for approval.
Set artifact status to: Ready for launch — awaiting user approval.

Once approved → execute the **Delegation Protocol** (final section).

## Anti-Patterns

| ❌ Anti-pattern | Why |
|----------------|-----|
| Pass artifact file path as prompt source | Artifact may change after launch; always copy text |
| Invoke the teamwork subagent before explicit user approval | User must confirm readiness |
| Skip creating the artifact | Artifact is the user's window into the prompt |
| Lose the draft on iteration | If user wants changes after Step 8, update and re-present |
| Add implementation hints by default | Narrows agent team's solution space. If user explicitly wants to constrain (e.g., "use Python"), include as a requirement but flag the trade-off |

## Iterate After First Run

Prompt crafting is iterative. If the first run falls short, tighten
    acceptance criteria or add better verification — prefer this over
    adding implementation hints. Re-run with the updated prompt.

## Delegation Protocol

When the user approves ("go", "looks good", "launch", "run it", or
    similar):

1. Extract the complete prompt text from prompt_draft.md.
2. Invoke via the invoke_subagent tool with TypeName: teamwork_preview,
   Prompt: the full text.
   (teamwork_preview is hidden from the subagents list but can be invoked.)

Set artifact status to: Launched.
</TEAMWORK>
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from Gemini 3.1 Pro (High) to Gemini 3.6 Flash (High). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>
