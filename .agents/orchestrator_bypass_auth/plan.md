# Implementation Plan: Auth & Bypass for Yandex Music, YouTube, SoundCloud

## Phase 1: Explore & Design
- **Subagent**: `teamwork_preview_explorer` (Explorer)
- **Objective**: Inspect the target files in AURA Music to see how settings are stored, how HTML/JS rendering for settings works, how service classes are initialized in `core/app.py` and structured in `services/`, and how events/callbacks are emitted to the frontend.
- **Verification**: Review findings, file paths, and current implementations.

## Phase 2: Schema & Backend Settings Setup
- **Subagent**: `teamwork_preview_worker` (Worker)
- **Objective**:
  - Update `core/settings.py` with `auth.cookies_file_path`, `auth.browser_cookies`, and `auth.yandex_token`.
  - Update service initialization in `core/app.py` to pass the settings instance to services.
- **Verification**: Verify code compilability, run pytest/unit tests.

## Phase 3: Frontend UI & settings.js Implementation
- **Subagent**: `teamwork_preview_worker` (Worker)
- **Objective**:
  - Create the UI controls in `ui/web_new/index.html` (under a new "Авторизация и Обход блокировок" section).
  - Update `ui/web_new/js/settings.js` to load, display, and save these settings correctly.
  - Implement warning message handling when `yandex_auth_error` is triggered.
- **Verification**: UI elements rendered correctly, no console errors.

## Phase 4: Yandex Music Auth & Fallback
- **Subagent**: `teamwork_preview_worker` (Worker)
- **Objective**:
  - Update `services/yandex_service.py` to read `yandex_token`.
  - Handle token initialization failures cleanly: do not crash, fallback to anonymous (30-sec limit), and notify the frontend.
- **Verification**: Unit tests and E2E simulation.

## Phase 5: YouTube & SoundCloud Cookies & yt-dlp Error Interception
- **Subagent**: `teamwork_preview_worker` (Worker)
- **Objective**:
  - Handle constructors accepting settings.
  - Implement cookie cascading in `ydl_opts` (path existence check vs browser cookies option).
  - Wrap extractor functions, intercept `DownloadError`, and notify user with a clean message via `error_callback`.
  - Add extractor_args for YouTube.
- **Verification**: Compile and test.

## Phase 6: E2E Verification & Review
- **Subagents**: `teamwork_preview_reviewer` (Reviewer) and `teamwork_preview_challenger` (Challenger)
- **Objective**:
  - Perform unit tests.
  - Run integration checks, verify that changes do not break other flows.
  - Use `teamwork_preview_auditor` to audit the changes.
