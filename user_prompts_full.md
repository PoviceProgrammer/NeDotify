
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
3. Реализовать OFFLINE GRACE PERIOD (7 дней): в core/api.py:1198 добавить проверку локальной SQLite таблицы `license_cache` (ключ, timestamp, signature). Если нет сети — пускаем юзера, если прошло < 7 дней с последней валидации.
4. Убрать жёсткую блокировку UI в main.js:191-201 — при неудачной валидации показывать overlay, но давать доступ к офлайн-библиотеке и настройкам.

## 0.2 Space Key Double-Toggle (hotkeys.js + settings.js)
ПРОБЛЕМА: hotkeys.js:9-13 хардкодит Space→togglePlayPause(). settings.js:766 дефолт play_pause='Space' вызывает triggerKeybindAction→клик #pb-btn-play→togglePlayPause(). ДВА обработчика = двойной toggle = ноль.
ЗАДАЧА:
1. В hotkeys.js:9-13 удалить хардкод Space. Сделать единый `dispatchHotkey(action)` который ВСЕГДА идёт через settings.js:766 (keybinds map).
2. В settings.js:750-769 синхронизировать названия: переименовать категорию 'keybinds' → 'hotkeys' ИЛИ читать из 'keybinds' в hotkeys.js. Выбери ОДИН источник правды и приведи к нему всё приложение.
3. Реализовать volume_up/volume_down/mute по-настоящему (сейчас hotkeys.js:72-81 — только toast). Вызывать `window.pywebview.api.set_volume(current + delta)`.

## 0.3 Secrets Migration (.env → %APPDATA%)
ПРОБЛЕМА: .env с VK_TOKEN/ADMIN_ID лежит в корне проекта на OneDrive. Утечка при любом пуше.
ЗАДАЧА:
1. Написать `scripts/migrate_secrets.py` — скрипт, который при первом запуске:
   - Читает .env из корня проекта
   - Переносит его в `{APPDATA}/AURA Music/.env` (Windows) / `~/.config/aura-music/.env` (Linux/Mac)
   - Удаляет оригинальный .env из корня
   - Добавляет `.env` в .gitignore (если его там нет)
2. Обновить main.py чтобы он читал .env из новой локации (python-dotenv с dotenv_path).
3. В core/api.py:1149 и :1194 вынести NEDOTIFY_SECRET_SIGNATURE_KEY_2026 в .env, а в коде оставить только чтение через os.environ.

================================================================
# PRIORITY 1: SETTINGS PANEL BUGS (10+ кнопок)
================================================================

## 1.1 API Methods Missing (contextmenu.js, lyrics.js, hotkeys.js)
ДОБАВИТЬ В core/api.py:
- `def add_to_queue(self, track_id):` — для contextmenu.js:43 "Играть следующим"
- `def get_setting(self, key):` — для lyrics.js:160 (восстановление смещения)
- `def get_lyrics_offset(self, track_id):` / `def set_lyrics_offset(self, track_id, offset):`

## 1.2 Missing HTML Elements (settings.js)
ДОБАВИТЬ В ui/web_new/index.html:
- `#pp-btn-lyrics` — кнопка "Открыть текст" (полноэкранный lyrics overlay)
- `#workshop-search-input` — поиск по мастерской (settings.js:2044)
- `#opt-perf-preset`, `#slider-fps-visualizer`, `#slider-fps-particles` — ЛИБО добавить в HTML, ЛИБО удалить мёртвую логику из settings.js:900-929 (предпочтительнее удалить, так как эта секция не используется).

## 1.3 Light Theme & Theme Mode (themes.css, settings.js)
- ДОБАВИТЬ в themes.css блок `[data-theme="light"]` с реальными светлыми цветами (не янтарным дубликатом).
- В settings.js:applySettingsFromBackend ДОБАВИТЬ ветку для `theme_mode` ('dark'/'light'/'system'), чтобы при старте восстанавливался режим, а не сбрасывался в тёмный.
- Системный режим: использовать `window.matchMedia('(prefers-color-scheme: dark)')`.

## 1.4 Workshop UTF-8 Fix (кракозябры)
settings.js:2089 выводит "РРёС‡РµРіРѕ не найденРѕ". Это UTF-8 текст, прочитанный как CP1251.
РЕШЕНИЕ: В settings.js явно установить `responseType` и `Content-Type: application/json; charset=utf-8` для API-запросов воркшопа. Проверить бэкенд-эндпоинт на предмет `json.dumps(..., ensure_ascii=False)`.

## 1.5 Onboarding Presets Persistence (onboarding.js)
Пресеты "Красота/Скорость" живут только в session.
РЕШЕНИЕ: При выборе пресета в onboarding.js вызывать `window.pywebview.api.save_settings(preset_dict)` чтобы записать в SQLite. При старте читать эти настройки.

## 1.6 Storage Refresh (settings.js:162-167)
После очистки кэша цифры не обновляются.
РЕШЕНИЕ: После `api.clear_storage()` сразу вызывать `api.get_storage_info()` и пушить данные в UI, а не ждать внешнего события.

================================================================
# PRIORITY 2: GENERAL BUGS & PERFORMANCE
================================================================

## 2.1 Critical Python Bugs
- api.py:43 `self.core` → `self._core` (AttributeError fix).
- main.py:91 `session.save_session(volume=70)` — заменить хардкод на `volume=self.current_volume` или чтение из audio_engine.
- search.js:116-141 — починить фильтры "Плейлисты" и "Альбомы" (сейчас всегда возвращают треки). Добавить параметр `type` в API-запрос.

## 2.2 Security Vulnerabilities (КРИТИЧНО)
- zapret_service.py:92-99 `subprocess.Popen(... shell=True)` с custom_args — **КОМАНДНАЯ ИНЪЕКЦИЯ**. Переписать на `shell=False` с передачей аргументов списком. 
- zapret_service.py:41 `taskkill /F /IM winws.exe` — убивает ВСЕ процессы winws.exe. Заменить на `process.terminate()` конкретного Popen объекта, сохранив его handle при запуске.
- yt-dlp `nocheckcertificate=True` — УБРАТЬ. Включить TLS-проверки, добавить fallback на кастомные CA если нужно.
- CORS `*` в proxy.py — ограничить до `file://` и `http://localhost:*`.
- SSRF в импорте плейлистов (api.py:518-520) — добавить whitelist доменов (youtube.com, music.youtube.com, spotify.com, soundcloud.com) и blocklist приватных IP (127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16, 169.254.0.0/16).

## 2.3 UI/UX Polish
- "ФОНОВОЕ ЗОБРАЖЕНИЕ" → "ФОНОВОЕ ИЗОБРАЖЕНИЕ" (опечатка).
- Убрать дублирующиеся id lyrics-overlay/lyrics-content (вторая пара мертва).
- Кнопка "Информация" в контекст-меню: заменить `\\n` на реальный `\n` в выводе.
- Полупрозрачность окна в runtime (main.py:57-69) — если PyWebView не поддерживает runtime transparency, честно отключить переключатель в UI с пометкой "только при запуске".

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
3. Реализовать OFFLINE GRACE PERIOD (7 дней): в core/api.py:1198 добавить проверку локальной SQLite таблицы `license_cache` (ключ, timestamp, signature). Если нет сети — пускаем юзера, если прошло < 7 дней с последней валидации.
4. Убрать жёсткую блокировку UI в main.js:191-201 — при неудачной валидации показывать overlay, но давать доступ к офлайн-библиотеке и настройкам.

## 0.2 Space Key Double-Toggle (hotkeys.js + settings.js)
ПРОБЛЕМА: hotkeys.js:9-13 хардкодит Space→togglePlayPause(). settings.js:766 дефолт play_pause='Space' вызывает triggerKeybindAction→клик #pb-btn-play→togglePlayPause(). ДВА обработчика = двойной toggle = ноль.
ЗАДАЧА:
1. В hotkeys.js:9-13 удалить хардкод Space. Сделать единый `dispatchHotkey(action)` который ВСЕГДА идёт через settings.js:766 (keybinds map).
2. В settings.js:750-769 синхронизировать названия: переименовать категорию 'keybinds' → 'hotkeys' ИЛИ читать из 'keybinds' в hotkeys.js. Выбери ОДИН источник правды и приведи к нему всё приложение.
3. Реализовать volume_up/volume_down/mute по-настоящему (сейчас hotkeys.js:72-81 — только toast). Вызывать `window.pywebview.api.set_volume(current + delta)`.

## 0.3 Secrets Migration (.env → %APPDATA%)
ПРОБЛЕМА: .env с VK_TOKEN/ADMIN_ID лежит в корне проекта на OneDrive. Утечка при любом пуше.
ЗАДАЧА:
1. Написать `scripts/migrate_secrets.py` — скрипт, который при первом запуске:
   - Читает .env из корня проекта
   - Переносит его в `{APPDATA}/AURA Music/.env` (Windows) / `~/.config/aura-music/.env` (Linux/Mac)
   - Удаляет оригинальный .env из корня
   - Добавляет `.env` в .gitignore (если его там нет)
2. Обновить main.py чтобы он читал .env из новой локации (python-dotenv с dotenv_path).
3. В core/api.py:1149 и :1194 вынести NEDOTIFY_SECRET_SIGNATURE_KEY_2026 в .env, а в коде оставить только чтение через os.environ.

================================================================
# PRIORITY 1: SETTINGS PANEL BUGS (10+ кнопок)
================================================================

## 1.1 API Methods Missing (contextmenu.js, lyrics.js, hotkeys.js)
ДОБАВИТЬ В core/api.py:
- `def add_to_queue(self, track_id):` — для contextmenu.js:43 "Играть следующим"
- `def get_setting(self, key):` — для lyrics.js:160 (восстановление смещения)
- `def get_lyrics_offset(self, track_id):` / `def set_lyrics_offset(self, track_id, offset):`

## 1.2 Missing HTML Elements (settings.js)
ДОБАВИТЬ В ui/web_new/index.html:
- `#pp-btn-lyrics` — кнопка "Открыть текст" (полноэкранный lyrics overlay)
- `#workshop-search-input` — поиск по мастерской (settings.js:2044)
- `#opt-perf-preset`, `#slider-fps-visualizer`, `#slider-fps-particles` — ЛИБО добавить в HTML, ЛИБО удалить мёртвую логику из settings.js:900-929 (предпочтительнее удалить, так как эта секция не используется).

## 1.3 Light Theme & Theme Mode (themes.css, settings.js)
- ДОБАВИТЬ в themes.css блок `[data-theme="light"]` с реальными светлыми цветами (не янтарным дубликатом).
- В settings.js:applySettingsFromBackend ДОБАВИТЬ ветку для `theme_mode` ('dark'/'light'/'system'), чтобы при старте восстанавливался режим, а не сбрасывался в тёмный.
- Системный режим: использовать `window.matchMedia('(prefers-color-scheme: dark)')`.

## 1.4 Workshop UTF-8 Fix (кракозябры)
settings.js:2089 выводит "РРёС‡РµРіРѕ не найденРѕ". Это UTF-8 текст, прочитанный как CP1251.
РЕШЕНИЕ: В settings.js явно установить `responseType` и `Content-Type: application/json; charset=utf-8` для API-запросов воркшопа. Проверить бэкенд-эндпоинт на предмет `json.dumps(..., ensure_ascii=False)`.

## 1.5 Onboarding Presets Persistence (onboarding.js)
Пресеты "Красота/Скорость" живут только в session.
РЕШЕНИЕ: При выборе пресета в onboarding.js вызывать `window.pywebview.api.save_settings(preset_dict)` чтобы записать в SQLite. При старте читать эти настройки.

## 1.6 Storage Refresh (settings.js:162-167)
После очистки кэша цифры не обновляются.
РЕШЕНИЕ: После `api.clear_storage()` сразу вызывать `api.get_storage_info()` и пушить данные в UI, а не ждать внешнего события.

================================================================
# PRIORITY 2: GENERAL BUGS & PERFORMANCE
================================================================

## 2.1 Critical Python Bugs
- api.py:43 `self.core` → `self._core` (AttributeError fix).
- main.py:91 `session.save_session(volume=70)` — заменить хардкод на `volume=self.current_volume` или чтение из audio_engine.
- search.js:116-141 — починить фильтры "Плейлисты" и "Альбомы" (сейчас всегда возвращают треки). Добавить параметр `type` в API-запрос.

## 2.2 Security Vulnerabilities (КРИТИЧНО)
- zapret_service.py:92-99 `subprocess.Popen(... shell=True)` с custom_args — **КОМАНДНАЯ ИНЪЕКЦИЯ**. Переписать на `shell=False` с передачей аргументов списком. 
- zapret_service.py:41 `taskkill /F /IM winws.exe` — убивает ВСЕ процессы winws.exe. Заменить на `process.terminate()` конкретного Popen объекта, сохранив его handle при запуске.
- yt-dlp `nocheckcertificate=True` — УБРАТЬ. Включить TLS-проверки, добавить fallback на кастомные CA если нужно.
- CORS `*` в proxy.py — ограничить до `file://` и `http://localhost:*`.
- SSRF в импорте плейлистов (api.py:518-520) — добавить whitelist доменов (youtube.com, music.youtube.com, spotify.com, soundcloud.com) и blocklist приватных IP (127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16, 169.254.0.0/16).

## 2.3 UI/UX Polish
- "ФОНОВОЕ ЗОБРАЖЕНИЕ" → "ФОНОВОЕ ИЗОБРАЖЕНИЕ" (опечатка).
- Убрать дублирующиеся id lyrics-overlay/lyrics-content (вторая пара мертва).
- Кнопка "Информация" в контекст-меню: заменить `\\n` на реальный `\n` в выводе.
- Полупрозрачность окна в runtime (main.py:57-69) — если PyWebView не поддерживает runtime transparency, честно отключить переключатель в UI с пометкой "только при запуске".

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
The current local time is: 2026-08-06T13:27:57+03:00.

The user has mentioned some items in the form @[ITEM]. Here is extra information about the items that were mentioned by the user, in the order that they appear:

/teamwork-preview is a [Slash Command]:
<TEAMWORK>
The user has added the 'teamwork_preview' subagent, for use in multi-agent teamwork systems.
The user wants to use the teamwork multi-agent system for a project.
Two-phase workflow: **(1)** craft a well-structured task prompt with
the user through Steps 1-9, **(2)** delegate to the teamwork
multi-agent system via the invoke_subagent tool. Both phases are required —
crafting without delegation is incomplete.

## Artifact-Based Workflow

Maintain a **prompt draft artifact** (prompt_draft.md) throughout the
process. It serves as both a live display for the user and a step
tracker for you. **Create it immediately** with this scaffold:

```markdown
# Teamwork Project Prompt — Draft

> Status: Step 1 — Eliciting project idea
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

[Project description — 1-2 sentences]

Working directory: [TBD]

## Requirements

### R1. [TBD]

### R2. [TBD]

## Acceptance Criteria

### [TBD]
- [ ] [TBD]

---
*Next: when approved → delegate via invoke_subagent (see Delegation Protocol)*
```

Update the artifact after every step.

## Core Principles

| # | Principle | Rule |
|---|-----------|------|
| 1 | **Specify What, Not How** | Define requirements and acceptance criteria. Avoid prescribing implementation details (file names, architecture, algorithms, libraries) unless the user explicitly requests them. |
| 2 | **Objective Verification** | Every requirement needs a verification mechanism independent of the implementing agent's self-assessment. Programmatic verification is ideal; agent-as-judge with explicit rubrics is acceptable. |
| 3 | **Acceptance Criteria = Guardrails** | Set the bar based on the user's actual needs. Purpose: prevent self-certification of poor work. If the first run falls short, tighten criteria and re-run. |
| 4 | **Minimal Requirements** | Only specify what the user cares about. Let teamwork infer the rest. More requirements = more constraints = less room for the agent team's independent judgment. |

## Workflow

Work through Steps 1-9 interactively. **Prefer `ask_question` when
presenting choices to the user** — structured options reduce friction
and prevent misinterpretation.

**Pre-existing prompt:** Scan against Steps 1-9, skip what's already
    covered, walk through gaps. Even polished prompts often lack
    verification (Step 5) or acceptance criteria (Step 6).

**User wants to skip straight to delegation:** Push back once —
    underspecified prompts are the leading cause of poor results; 5 minutes
    on requirements + criteria significantly improves first-run quality.
    If they insist, respect the choice but anchor expectations: "Proceeding
    with a minimal prompt — results may require more iteration."

### Step 1: Elicit the Idea

Ask: What do you want to build? What is the purpose (demo, production,
    eval, exploration)? Who is the audience?

Capture in 1-2 sentences → this becomes the prompt's opening.
Update artifact: replace [Project description], set status to Step 2.

### Step 2: Identify Ambiguity

Identify points with multiple reasonable interpretations. For each,
    present concrete choices:

```
Example: "Build a search engine"

Ambiguous: What data source?
→ Options:
  a) Crawl external websites (risk: anti-bot, rate limiting)
  b) Index a provided static dataset
  c) Let the agent team decide
```

Only ask about decisions that affect scope or verification. Don't ask
    about implementation details unless the user brings them up.

Key dimensions to probe:

| Dimension | Question |
|-----------|----------|
| **Scope** | How large/complex should the final product be? |
| **Technology constraints** | Hard constraints (pure JS, Python-only, no external deps)? |
| **Infrastructure** | Need network access, remote storage, job launching? → controlled APIs |
| **Quality bar** | Polished demo or proof-of-concept? |
| **Integrity** | How strict should integrity enforcement be? (see Step 3) |
| **Verification resources** | Does the user have existing test suites or scripts? (see Step 5) |

### Step 3: Determine Integrity Mode

Determine how strictly integrity enforcement should operate.
Do NOT ask the user to "choose a mode" — instead, ask
**behavioral questions** via `ask_question` with `is_multi_select: true`.
Present these options:

- Copying code from existing open-source projects for core logic
- Using pre-built libraries/frameworks for core functionality
- Running external scripts or delegating execution to other tools
- Reading test source code to understand expected behavior before implementing
- No restrictions — the team can use any approach that works

Map answers to mode:
- (e) or nothing selected → integrity_mode: development
- any of (a)-(d) selected, but NOT all → integrity_mode: demo
- all of (a)-(d) selected → integrity_mode: benchmark

Default: development. If the project is clearly a capability
showcase, suggest demo.

### Step 4: Draft Requirements

Write 2-5 requirement blocks (R1, R2, ...).

| Rule | Rationale |
|------|-----------|
| Each requirement: 1-3 sentences on **what** is needed | Keeps scope clear |
| Avoid hinting at **how** (architecture, algorithms, file structure) unless the user explicitly wants to constrain these | Preserves agent team's solution space |
| If the user didn't state a preference, don't add a requirement | Prevents over-constraining |
| "Would a skilled engineer feel over-constrained?" → if yes, cut it | Litmus test |

### Step 5: Design Verification

> **Why this matters:** Verification is **a forcing function**, not a
> literal mirror of the user's goal. Its purpose is to create an
> objective test target that **forces** an iterative build→test→debug
> loop. Without one, agents self-certify half-baked work and stop early.
>
> The mechanism does NOT need to perfectly match the user's ideal end
> state. It is a **means** — a trick to force real debugging. Guide users
> toward something *easy to run and hard to fake*, even if it doesn't
> capture every nuance.

For each requirement, design an **objective** verification mechanism:

| Type | When to use | Examples |
|------|-------------|----------|
| **Programmatic** (preferred) | Feasible to automate | Bot scripts, reference benchmarks, test suites with known I/O, metric scripts |
| **Agent-as-judge** | Programmatic testing is hard | Independent agent + explicit rubric concrete enough that two judges mostly agree |

**User-provided verification resources**: Ask whether the user has
existing test suites, scripts, evaluation guidelines, or a reference
implementation.

If yes, include them in the prompt as a Verification Resources
section. Even partial resources (e.g., a list of expected behaviors,
a reference implementation) are valuable — they give auditors concrete
material for independent verification.

**Verification anti-patterns:**

| ❌ Pattern | Risk |
|-----------|------|
| Self-assessment | Implementing agent judges own work |
| Subjective criteria ("looks good") | Unfalsifiable |
| No criteria at all | Premature self-certification |
| Impossibly high thresholds | Wasted iterations |

### Step 6: Set Acceptance Criteria

Convert verification mechanisms into concrete, checkable criteria.
    Calibrate to purpose:

| Purpose | Bar |
|---------|-----|
| Demo | Impressive but achievable in time budget |
| Production | Match target system quality standards |
| Eval | Precise and reproducible — measurement over polish |
| Exploration | Loose — prove feasibility only |

Common user adjustments: "too easy" → tighten; "too hard" → relax or
    make optional; "too prescriptive" → remove constraining criteria.

### Step 7: Infrastructure Constraints

If the project needs controlled infrastructure, add a requirement:

| Operation | Why control it |
|-----------|---------------|
| Remote file I/O (GCS, cloud storage) | Prevent writes to arbitrary paths |
| Job launching | Prevent expensive runaway jobs |
| Network access | Prevent hitting anti-bot protections or unintended services |

Pattern: "You must use the provided controlled API for X. You write the
    logic; the execution environment is managed externally."

Skip if no infrastructure is needed (e.g., pure HTML/JS games).

### Step 8: Choose Working Directory

Ask where project files should live. Default:
```
~/teamwork_projects/{PROJECT_NAME}
```

{PROJECT_NAME}: short, lowercase, underscore-separated (e.g.,
    c_compiler, search_engine, tetris_game).

Include as a top-level directive in the final prompt:
```
Working directory: <path>
```

### Step 9: Assemble and Validate

Ensure the artifact has this structure:

```
[1-2 sentence project description]

Working directory: <chosen path from Step 8>
Integrity mode: [development | demo | benchmark]

[Optional: reference material (paper URL, spec link)]

## Requirements

### R1. [Primary deliverable]
[What it does, not how to build it]

### R2. [Secondary requirement or constraint]
...

### R3. [Controlled infrastructure, if needed]
...

## Acceptance Criteria

### [Criterion category]
- [ ] [Objective, checkable condition]
...
```

**Validation checklist:**

- [ ] No implementation hints unless explicitly requested by the user
- [ ] Every acceptance criterion is objectively checkable without
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
