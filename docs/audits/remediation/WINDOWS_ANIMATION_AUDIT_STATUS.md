# Аудит анимаций Windows — состояние ремедиации

Дата: 2026-11-18. Область: `NeDotify_Windows/ui/web_new_v2/` (desktop).
Android и Linux не трогались.

Отчёт аудита нашёл ~20 мест. Ниже — что закрыто, чем и что осталось.
Каждое утверждение проверяемо по коду или тесту; ничего «на веру».

## Принцип, который изменился

У `.track-item` больше нет `animation: fadeIn`. Она переигрывала при каждом
ререндере списка — порция потокового поиска, `queue_updated`, хвост «Моей
волны» — и именно это выглядело как мигание. Теперь вход новых строк делает
`NeDotifyMotion.reveal`, сдвиг — `settleList`, а переиспользованные узлы не
анимируются вовсе.

## Закрытые находки

| # | Находка | Что сделано | Тест |
|---|---|---|---|
| 1–2 | Поиск: полная перерисовка + переигрывание fadeIn на каждый чанк | `rankSearchResults` вызывается один раз по `__completion__`; `renderSearchResultsBatch` дописывает только дельту и подрезает хвост; `reveal` — на новые строки и на смену контекста | `tests/test_smart_search_ui.py`, `tests/test_fixes_group2.py` |
| 3 | Обзор поиска перерисовывался на каждый чанк | Сигнатура `context|count|keys`; `reveal` только при новой связке запрос/тип | — |
| 4 | Спиннер мигал на каждый keystroke | `showLoading()` переехал внутрь 200-мс дебаунса | — |
| 5 | `audioBufferToPeaks` — синхронный обход всех сэмплов | Добавлен `audioBufferToPeaksAsync` (нарезка по 1 млн сэмплов, `scheduler.yield()` → `MessageChannel`, проверка отмены); `computePeaks` использует его. Синхронный вариант сохранён — на нём держится тест | `tests/test_waveform_peaks.py` |
| 6–7 | Очередь: полная пересборка + конфликт fadeIn/settleList + замер по незакрытой анимации | `renderQueue` переиспользует узлы по `entry_id` (`queueRowKey`/`queueRowShape`/`buildQueueRow`), reconciliation по курсору; маркер `playing` применяется на месте через `applyQueueRowState`; `listPositions` отменяет незакрытую анимацию строки до замера | `tests/test_queue_row_reuse.py` (новый) |
| 8 | «Моя волна»: rebuild 60 строк на каждой смене трека | Пропуск `replaceChildren` при неизменной сигнатуре списка | `tests/test_personal_wave_ui.py` |
| 9 | У `#app-tooltip` нет ни одного CSS-правила | Правило восстановлено: `position:fixed`, `opacity`/`translate`-переход, reduced-motion и battery-saver варианты | `tests/test_visual_guard_css_decls.py` |
| 10–11 | Главная: тройной рендер Quick Access, второй flash от backfill | Один `renderQuickAccess` после загрузки данных; сигнатурные гарды; `patchFeedCovers` правит `img.src` живых карточек | — |
| 12 | Атмосфера сбрасывала палитру при пустом списке обложек | Ранний выход, предыдущие цвета сохраняются | — |
| 13 | rAF-цикл караоке крутился на скрытом оверлее | `containerIsVisible` учитывает `.active/.visible`; rAF стартует при открытии; красится только видимый лист | `tests/test_lyrics_word_ui.py` |
| 14 | Настройки текста: инлайн-стили на каждую строку + синхронный перезамер на каждый `input` | Цикл записи `fontSize`/`fontWeight`/`lineHeight` на все `.lyric-line` удалён: типографика идёт только через `--lyrics-*`, а `font-size` в CSS и так `!important`, то есть инлайн-запись не могла сработать. Перезамер кинетики коалесцирован в один rAF на кадр | `tests/test_lyrics_settings_layout.py` (новый) |
| 15 | Эквалайзер пересобирал DOM на каждый `input` | `renderBandSliders` выходит при том же режиме; `updateEqUI` не переписывает сфокусированный слайдер | — |
| 16 | CSS-автоскрытие тоста спорило с JS hover-pause | `toastOut ... 3.7s forwards` удалён; скрытие полностью на JS; тост офсета throttled до 700 мс | — |
| 17 | `contain-intrinsic-size` не совпадал с реальной высотой строк | Контекстные переопределения: `.search-hit-row` 76px, top-result 86px, строка очереди с рекомендацией 69px | — |
| 18 | `eqPulse` анимировал `height` | `transform: scaleY()`; контейнер держит 14px | `tests/test_visual_guard_css_decls.py` |
| доп. | Resize без дебаунса сбрасывал backing store canvas | `visualizer.js` и `atmosphere-engine.js` коалесят через rAF | `tests/test_visual_effects_lifecycle.py` |
| доп. | Бары визуализатора замирали недошедшими до покоя | Конечный settle-проход (≤40 кадров, `IDLE_*`), затем цикл паркуется | `tests/test_visual_effects_lifecycle.py` |
| доп. | Фильтр коллекций без дебаунса | 160 мс + сигнатурный гард сетки | — |
| доп. | `syncRepeatIcon` перерисовывал иконки всего документа | `renderIcons(btn)` | — |
| доп. | Прогресс пакетной загрузки через `width` | `transform: scaleX()` + `transform-origin:left` | — |
| доп. | `.track-item.playing { padding-left:16px }` давал рывок | `padding-left` в общий `transition`, с гардами reduced-motion/perf-low/battery | — |

### Настройки текста: сохранение между запусками

Пункт 14 закрыл стоимость перерисовки, но кнопка «Оформление текста» всё ещё
не запоминала значения. Причина — не отсутствие функции, а рассинхронизация
контракта моста в обе стороны:

- `get_lyrics_display_settings` возвращает плоский camelCase-dict
  (`{fontSize, fontWeight, lineHeight, textAlign}`), а поповер применял его
  только при `res.success && res.settings` и читал `snake_case` — условие не
  совпадало никогда, поэтому при старте оставались `24px`;
- сохранение отправляло четыре позиционных числа в
  `save_lyrics_display_settings(self, settings: dict)`; `isinstance(settings,
  dict)` давал `False`, метод возвращал `False`, в SQLite не писалось ничего.

Теперь обе стороны нормализуют вход: JS принимает camelCase и snake_case,
плоский dict и обёртку `{success, settings}`, отправляет один dict; Python
принимает dict, JSON-строку и легаси-позиционные аргументы, клампит значения и
пишет те же camelCase-ключи, что читает `get_settings_by_category`. Бэкенд
возвращает только реально сохранённые ключи, а UI накладывает их поверх
`localStorage`, поэтому пустая база не затирает выбор пользователя. Ответ
бэкенда, пришедший после первого движения слайдера, игнорируется
(`userTouched`), а отложенная запись сбрасывается при закрытии поповера и на
`pagehide`.

Проверки: `tests/test_lyrics_display_settings_api.py` (форматы вызова и
клампинг), `tests/test_lyrics_settings_layout.py` (camelCase, dict-запрос,
merge с localStorage и защита от позднего ответа),
`tests/lyrics_settings_popover_browser.cjs` (кнопка в обычном и развёрнутом
плеере, оба оформления, два размера окна).

Отдельная причина «кнопка не работает в развёрнутом плеере»: поповер лежит
внутри `#app-container`, а у него `position: relative; z-index: 10` — это
контекст наложения. При развороте плеер переносится в `<body>` с `z-index: 80`
и рисуется поверх всего контейнера, поэтому поповер с `z-index: 10001`
открывался, но оказывался под плеером. Теперь при инициализации поповер
переносится в `<body>` (на верхний уровень), а высота для проверки
переворота берётся из `offsetHeight`, а не из константы 360 при реальных 502.

## Сознательно не изменено

Четыре layout-анимации оставлены как есть: перевод на `transform` требует
переверстки, а выигрыш мал.

- `#pp-btn-play` — `transition: width 220ms` (морф кнопки play/pause).
- Сайдбар — `width`/`min-width`/`padding` 260 мс (сворачивание рейла).
- `#mini-player-overlay` — `width`/`height` 260 мс. В нативном режиме
  (`body.mini-player-native`) переход уже отключён: WinForms сам анимирует
  границы окна.
- Орбита онбординга — `width`/`height` .7s.

## Проверка

- `python -m pytest tests -q` → 2966 passed, 9 skipped (8 из них — новые
  проверки настроек текста).
  (`tests/test_engine_resolve.py::test_int_source_id_must_resolve_instead_of_raising`
  изредка падает только в полном прогоне и проходит в одиночном — зависимость от
  порядка в `audio/engine.py`, к фронтенду отношения не имеет; воспроизводится и
  на чистом `HEAD`.)
- `node --check` по всем изменённым JS-файлам — чисто.
- `tools/visual_guard/run_guard.py --write-css-baseline` → 587 деклараций,
  self-check ok (база перегенерирована намеренно: fadeIn и `toastOut` удалены).

### Браузерные наборы (Chromium через `playwright-core` 1.64)

Прошли, включая сценарии, которые правки и задевали:

| Набор | Что подтвердил |
|---|---|
| `ui_motion_browser.cjs` | вход/выход модалок, закрытие без блокировки, очистка снимков, **content reveal и reorder очереди** (`settleList`), reduced motion — оба оформления |
| `queue_panel_browser.cjs` | очередь, история, управление, Escape — оба оформления |
| `player_status_bar_browser.cjs` | строка статуса и fullscreen: current/macos × light/dark |
| `toast_layout_browser.cjs` | компактное уведомление, стек, верхний баннер |
| `settings_sliders_browser.cjs` | слайдеры шрифта/прозрачности, откат значений |
| `audio_tools_browser.cjs` | геометрия вкладок, драг всех четырёх слайдеров, EQ |
| `download_manager_browser.cjs`, `library_layout_browser.cjs`, `update_banner_browser.cjs` | менеджер загрузок, раскладка библиотеки, баннер обновления |

Падают, но **не из-за этой работы** (проверено на чистом worktree `HEAD 4a147da`):

- `dialog_lifecycle_browser.cjs` — `Failed to fetch ... /js/smart-playlists`
  (запрос несуществующего модуля). Падает и на `HEAD`.
- `home_artist_avatars_browser.cjs` — `EncodingError: источник изображения не
  декодируется`. Падает и на `HEAD`.
- `atmosphere_settings_browser.cjs`, `settings_audit_browser.cjs` — падают и на `HEAD`.
- `windows_refresh_browser.cjs` — шаг ждёт `.toast-action`, а `notifications.js`
  кнопок действия не создаёт (файл не менялся ни здесь, ни относительно `HEAD`).
- `player_progress_browser.cjs` — ожидает слайдер по центру бара. В рабочем дереве
  лежит **незакоммиченная переверстка player-bar** (высоты 84/80/68 → 96/88/108 px,
  перенос прогресс-строки в `.pb-controls`); на чистом `HEAD` набор проходит.
  К анимационному аудиту не относится: из правок этой работы в `player-bar.css`
  только `contain-intrinsic-size: auto 69px` для строк очереди с рекомендацией.

## Что осталось непроверенным

- Переиспользование строк очереди и `settleList` в WebView2: набор Chromium
  проходит, но приоритет WAAPI против CSS-анимаций на `opacity` в WebView2 стоит
  посмотреть глазами (строки не мигают, а плавно встают на новые позиции).
- Фактическая стоимость blur-слоёв атмосферы — статически оценивается как
  дорогая, измерять нужно трассировкой.

## Второй проход: «дёрганье» из-за каскада и новые эффекты

Аудит нашёл места, где анимация *есть*, но не играет. Причина у большинства
одна: правило `button, .icon-btn, .play-btn { transition: ... !important }`
в `base.css` перекрывало `transition` компонента. Список свойств там был
`transform, opacity, background`, поэтому кнопка, которой нужен `width` или
`border-radius` (морф play/pause), меняла их скачком, а боковое меню теряло
переход цвета — пункт «перещёлкивался».

| Что | Что сделано | Тест |
|---|---|---|
| Базовый переход кнопок глушил свойства компонентов | В `!important`-правило добавлены `background-color`, `color`, `border-color`, `box-shadow`; собственные свойства компоненты дописывают в своё `!important`-правило | `tests/test_frontend_css_wiring.py` |
| Боковое меню: активный пункт менял фон/цвет без перехода | `padding`, `gap`, `width`, фон, цвет, рамка, тень и `transform` — в один переход 220–260 мс с `!important`, чтобы базовое правило не отменяло список | `tests/test_frontend_css_wiring.py` |
| `#pp-btn-play` дёргался на наведении | `transform` и `box-shadow` добавлены в его `!important`-переход | `tests/ui_motion_browser.cjs` |
| Контекстное меню появлялось и исчезало в один кадр | `@starting-style` + discrete `display` с `allow-discrete`; закрытое состояние сразу `pointer-events: none`, поэтому меню не съедает следующий клик | `tests/ui_motion_browser.cjs` |
| Окно настроек открывалось без анимации (`transition: none` в двух местах) | `transition` убран из `base.css`; пакет настроек задаёт только состояния, время перехода живёт в `ui-motion.css`: оверлей `opacity`/`visibility`, карточка `translateY(10px) scale(.992)` | `tests/test_frontend_css_wiring.py` |
| Переключение разделов настроек | `NeDotifyMotion.swap` — scoped View Transition; старый `panelTabSlide` отключён, чтобы движение не удваивалось | `tests/ui_motion_browser.cjs` |
| Список загрузок раскрывался рывком | Body обёрнут в `.download-manager-body/-inner`, переход `grid-template-rows: 0fr → 1fr` 260 мс вместе с `opacity` и discrete `visibility` | `tests/download_manager_browser.cjs` |
| Счётчик очереди загрузок менялся без анимации | Текст обновляется только при реальном изменении и проявляется через `reveal` | `tests/download_manager_browser.cjs` |
| Поиск: шапка прыгала, результаты появлялись мгновенно, фильтры без отклика | `margin` 220 мс, `@starting-style` для блока результатов, переходы фильтров и подъём карточек артистов | `tests/ui_motion_browser.cjs` |
| Профиль и библиотека: карточки без отклика на наведение | Подъём на 2px + тень, обложка `scale(1.04)`; вспышка «сброшено в плейлист» переехала на keyframe `playlistDropFlash` | `tests/library_layout_browser.cjs` |
| Плеер пересобирал иконку сердца на каждой смене трека | `updateLikeButtons` пишет DOM только при смене состояния; пульс больше не переигрывается | `tests/player_artwork_browser.cjs` |
| Обложка менялась мгновенно | Новый `NeDotifyMotion.cover` — `opacity` .35 → 1 и `scale(1.015)` → 1 за 220 мс, только на смене трека | `tests/player_artwork_browser.cjs` |
| Онбординг: быстрые повторные клики наслаивали keyframes | Одна WAAPI-анимация на узел через `WeakMap` (`perNode`) | — |
| Плитки стиля интерфейса и режимы рекомендаций без отклика | Переходы цвета, тени и подъём выбранной плитки | `tests/settings_sliders_browser.cjs` |

Проверки: `tests/test_frontend_css_wiring.py`,
`tests/test_visual_guard_css_decls.py`, `tests/test_visual_effects_lifecycle.py`
— 71 passed. Подмножество по затронутым темам — 696 passed. Браузерные наборы
`ui_motion_browser`, `download_manager_browser`, `settings_sliders_browser`,
`player_artwork_browser`, `library_layout_browser` — прошли.
`tools/visual_guard/run_guard.py --write-css-baseline` → 614 деклараций,
self-check ok (база перегенерирована намеренно: добавлены новые переходы).
Пиксельные гольдены не собраны (`empty_baseline`), поэтому `--compare`
завершается FAIL по пикселям — это не регрессия CSS, декларации сравнялись
(0 changed, 0 added).
