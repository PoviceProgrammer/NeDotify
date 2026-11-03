# Riff → NeDotify: первоначальная настройка

Изучен [Riff](https://github.com/rootscripts/riff/tree/fa33ad0ab566979a557e2418c45437e2b336a371), commit `fa33ad0ab566979a557e2418c45437e2b336a371` (2026-10-29, версия package.json 43.2.2).

Исходники, а не README:

- `src/renderer/welcome.html`: пять шагов, `themeState` и `toggles` как черновик, живой предпросмотр, `pendingImport`, обработчик `finishBtn`, блокировка повторного завершения.
- `src/main/main.js`: `createWindow`, `tutorialDone`, `welcome-finish`, сохранение завершения в основном процессе и передача `welcome-result` после загрузки приложения.
- `src/renderer/app.js`: `applyWelcomeResult` применяет выбранные параметры и инициирует импорт плейлиста.
- `src/main/preload.js`: узкие методы `welcomeFinish`, `onWelcomeResult`, `pickMedia`.
- `package.json`: Electron 41, обычные HTML/JS, `hls.js`, `tone`. Переносить Electron IPC в pywebview или добавлять Tone для мастера настройки не требуется.

Адаптировано в рабочий код NeDotify:

- Мастер разделён на шесть шагов: оформление, эффекты, звук, медиатека, источники и скачивание, итог. Доступны интерфейсы NeDotify/macOS, источники YouTube/SoundCloud, формат/качество скачивания и выбор локальной папки.
- Настройки до завершения остаются в черновике и показываются в итоговом списке. Перенос плейлиста начинается после подтверждённого сохранения. Добавление папки — отдельное явное действие, использующее существующий сканер и таблицу scan_folders.
- Один валидируемый `complete_onboarding` payload применяет реальные `interface`, `services`, `downloads`, `audio` настройки. Python подтверждает успех после синхронного сохранения; маркер завершения не устанавливается при ошибке записи.
- Повторное открытие гидратируется текущими настройками и отменяет старые подписки через AbortController. Один клик создаёт один вызов bridge.
- В отличие от ненадёжного локального маркера, постоянный Python storage определяет завершение. Старые локальные маркеры мигрируются, не отправляя существующих пользователей в мастер повторно.

Это самостоятельная адаптация механизмов и сценариев, без копирования несовместимого Electron-кода или ассетов. Riff распространяется по MIT, Copyright (c) 2026 rootscripts. Полный текст лицензии сохранён в [`licenses/riff-MIT.txt`](../licenses/riff-MIT.txt).

Проверка: `tests/test_onboarding.py`, `tests/test_onboarding_ui.py`, `tests/onboarding_preferences_browser.cjs`. Браузерный сценарий выполняет реальные обработчики NeDotify на реальном DOM, проверяет payload, импорт папки, повторное открытие и размер 600×650; сеть заменена bridge double. Нативное сканирование и воспроизведение проверяются отдельно основным агентом.


## Windows motion refresh — 2026-11-03

Checked upstream HEAD against the local reference: commit
`860b3276b74b3904ec6d3dcbdf3e12209022c18b`.
Read `src/renderer/welcome.html` (viewport resizing, directional pane transitions,
live theme preview and final preference handoff), plus
`src/renderer/app.js::applyWelcomeResult`. Electron dependencies were not added;
the Python onboarding persistence boundary and existing six steps remain.

References:
- [Riff welcome source](https://github.com/rootscripts/riff/blob/860b3276b74b3904ec6d3dcbdf3e12209022c18b/src/renderer/welcome.html)
- [Material shared-axis motion](https://m2.material.io/design/motion/the-motion-system.html)
- [Apple interactive onboarding guidance](https://developer.apple.com/design/human-interface-guidelines/onboarding)

Implemented a continuous six-scene preview, live theme/style/source/format
feedback, directional staggered form entrance and a smoothly interpolated
progress rail. The native progress element stays available to assistive tech.
Scene loops pause outside their relevant steps and while the document is hidden.
Session abort cancels Web Animations and unregisters session listeners; reduced
motion is respected. Both Windows skins use the same wizard.

Validation: 39 onboarding tests passed, including draft persistence, legacy
completion guards and animation cancellation on fast navigation/session abort.
Source inventory and scoped whitespace checks passed. No application window was
launched; visual appearance in a native window has not been rechecked.
