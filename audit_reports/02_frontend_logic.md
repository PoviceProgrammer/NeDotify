# Отчет аудита фронтенд-логики AURA Music (Frontend Logic Audit)

**Дата**: 2026-09-21  
**Компонент**: `ui/web_new_v2/js/` и взаимодействие с `core/api.py`  
**Аудитор**: Frontend Logic Auditor  
**Статус**: COMPLETED  
**Правило доказательности (R2)**: Все утверждения подтверждены точными ссылками на `file:line` и верифицированы статическим анализом и трассировкой выполнения.

---

## 1. Сводка результатов (Executive Summary)

В ходе глубокого аудита логики фронтенда (`ui/web_new_v2/js/`) и его сопряжения с бэкендом (`core/api.py`, `services/`) выявлено **12 подтвержденных дефектов**:

| Severity | Count | Findings |
|:---|:---:|:---|
| **P0** (Критический) | 0 | — |
| **P1** (Высокий) | 5 | Асинхронное эхо позиции вызывает дрожание кинетических текстов (DEF-FE-01); Рассинхронизация состояния плеера и фантомный звук при ошибках (DEF-FE-02); Утечка HLS-воркеров и гонка `_isTearingDown` при быстром переключении треков (DEF-FE-03); Отключенный эквалайзер и замерзший визуализатор (DEF-FE-05); Пакетное добавление в плейлист сбрасывает все выбранные треки кроме первого (DEF-FE-06) |
| **P2** (Средний) | 6 | Мертвый движок кроссфейда при наличии активных настроек (DEF-FE-04); Гонка очистки поисковой строки перезаписывает пустой экран устаревшими результатами (DEF-FE-07); Рендеринг сырого Python-исключения вместо текста песни (DEF-FE-08); Гонка устаревших текстов при быстром переключении треков (DEF-FE-09); Пропущенные и мертвые события в мосте `events.js` (DEF-FE-10); Заглушки в контекстном меню трека (DEF-FE-11) |
| **P3** (Низкий) | 1 | Мертвый fallback-селектор `#pb-volume-slider` в обработчиках горячих клавиш (DEF-FE-12) |

### Классификация DEAD_CONTROL
- **Подтип b (заглушка/no-op)**: DEF-FE-04 (кроссфейд), DEF-FE-05 (эквалайзер), DEF-FE-10 (`setting_changed`, `stop_track`), DEF-FE-11 (контекстное меню dislike/cache).
- **Подтип d (бэкенд отрабатывает, но в UI рассинхрон/потеря данных)**: DEF-FE-01 (эхо позиции), DEF-FE-02 (эхо состояния), DEF-FE-06 (потеря треков в batch playlist), DEF-FE-10 (`track_updated`, `api_error`).
- **Подтип e (утечка сокетов/воркеров/ресурсов)**: DEF-FE-03 (HLS instance leak).
- **Подтип f (падение/гонка/ошибочное поведение)**: DEF-FE-03 (`_isTearingDown` race), DEF-FE-07 (search clear race), DEF-FE-08 (exception as lyrics), DEF-FE-09 (lyrics race).
- **Подтип g (рассинхрон состояний UI vs Audio)**: DEF-FE-01 (jitter), DEF-FE-02 (phantom audio & inverted play/pause).

---

## 2. Детальные результаты аудита

---

### Направление 1: Плеер, HTML5 Audio и синхронизация событий

#### DEF-FE-01: Асинхронное эхо позиции из бэкенда вызывает дергание кинетических текстов (DEAD_CONTROL Подтипы g, d)
- **Файл и строки**: 
  - `ui/web_new_v2/js/player.js:464-471`
  - `core/api.py:869-881`
  - `ui/web_new_v2/js/events.js:47-64`
  - `ui/web_new_v2/js/lyrics.js:210-213`
- **Severity**: P1
- **Симптом**: Во время непрерывного плавного воспроизведения синхронизированный текст песни (kinetic lyrics) каждые 5 секунд резко дергается назад (на 100–300 мс), после чего перескакивает вперед.
- **Root Cause**:
  1. В `player.js:464` на каждое локальное событие HTML5 `<audio>` `timeupdate` (частота ~4 Гц) вызывается:
     ```javascript
     document.dispatchEvent(new CustomEvent('nedotify:position_changed', { 
         detail: { pos: currentPosMs, duration: currentDuration } 
     }));
     ```
  2. Каждые 5000 мс (`player.js:468-470`) текущая позиция отправляется в Python через bridge: `api('report_position', currentPosMs, currentDuration)`.
  3. В `core/api.py:876` бэкенд выполняет обратный эмит события `position_changed`:
     ```python
     self._emit("position_changed", {
         "pos": pos_sec,
         "duration": dur_sec,
         "position_ms": pos_ms,
         "duration_ms": duration
     })
     ```
  4. Мост pywebview с задержкой IPC (50–200 мс) доставляет это событие в `events.js:47-64`, где оно повторно и безусловно диспатчится в DOM:
     ```javascript
     document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: { pos: posMs, ... } }));
     ```
  5. Слушатель в `lyrics.js:210-213` принимает это запоздалое значение `posMs` и вызывает `updateLyricsPosition(posMs)`. В результате позиция текста скачет в прошлое, ломая плавный kinetic scrolling, а со следующим тиком `timeupdate` возвращается в настоящее время.
- **Proposed Fix**:
  В `events.js:47-64` не передиспатчить `nedotify:position_changed`, если в браузере активно играет локальный элемент HTML5 Audio (`window._getActiveAudio && !window._getActiveAudio().paused`), либо помечать события от бэкенда флагом `{ source: 'backend_echo' }`, который слушатель `lyrics.js` игнорирует при живом `<audio>`.
- **Verification / Regression Test**: Наблюдение за событием `nedotify:position_changed` в консоли браузера: проверять монотонность возрастания `detail.posMs`.

---

#### DEF-FE-02: Инверсия состояния Play/Pause и фантомный фоновый звук при ошибках (DEAD_CONTROL Подтипы g, d)
- **Файл и строки**:
  - `ui/web_new_v2/js/player.js:474-485, 1634-1702`
  - `core/api.py:827-835`
  - `ui/web_new_v2/js/events.js:41-45, 232, 265`
- **Severity**: P1
- **Симптом**:
  1. При быстром нажатии на паузу и воспроизведение кнопка плеера инвертируется (отображает "Pause", когда трек стоит на паузе, или наоборот).
  2. При возникновении ошибок бэкенда (`error`, `audio_error`) интерфейс переходит в состояние "остановлен" (кнопка показывает Play), однако аудио продолжает играть в фоне.
- **Root Cause**:
  1. Функция `onStateChanged(state)` (`player.js:1634-1702`) управляет **только** визуальным отображением (переменная `isPlaying`, иконки кнопок, анимация). Она **никогда не вызывает** `activeAudio.pause()` или `activeAudio.play()`.
  2. При старте/паузе аудио `player.js:474, 480` отправляет `report_state` в бэкенд, который эхом возвращает `state_changed` (`core/api.py:835`). При серии быстрых кликов эхо предыдущего состояния приходит позже локального действия пользователя и перезаписывает `isPlaying` в противоположное состояние по отношению к `activeAudio.paused`.
  3. В `events.js:232` и `events.js:265` при событиях `error` и `audio_error` вызывается `onStateChanged('stopped')`. Так как `activeAudio.pause()` не вызывается, если звук уже воспроизводился (например, вторичная ошибка стрима или ошибка другого фонового сервиса), аудио продолжает физически звучать, пока UI показывает статус остановки.
- **Proposed Fix**:
  - В `player.js:onStateChanged(state)`: при переходе в `state === 'stopped'` явно вызывать `if (activeAudio && !activeAudio.paused) activeAudio.pause();`.
  - При обработке события `state_changed` из бэкенда проверять согласованность с физическим состоянием `activeAudio.paused` перед перезаписью UI.
- **Verification / Regression Test**: Имитация вызова `window.onPythonEvent('audio_error', {message: 'test'})` во время воспроизведения: убедиться, что аудио физически встало на паузу.

---

#### DEF-FE-03: Утечка HLS-воркеров и гонка `_isTearingDown` при быстром переключении треков (DEAD_CONTROL Подтипы e, f)
- **Файл и строки**:
  - `ui/web_new_v2/js/player.js:76-105, 500-511, 578-587`
- **Severity**: P1
- **Симптом**: При быстром пролистывании треков (кнопка Next несколько раз подряд с интервалом <600 мс) следующий трек может самопроизвольно прерваться или пропуститься с ошибкой `handleStreamError`, а в фоне сохраняются сетевые подключения и воркеры HLS.
- **Root Cause**:
  1. В `playTrack` (`player.js:578-587`) для `oldAudio` вызывается `pause()`, `currentTime = 0`, `removeAttribute('src')`, `src = ''`, `load()`. Однако `oldAudio._hlsInstance` **не уничтожается** (`destroy()` вызывается только для `newAudio` в `loadAudioSource:78`). Если `oldAudio` воспроизводил HLS-поток, его воркер продолжает загружать чанки в фоне.
  2. В строке 586 установлен таймер сброса флага: `setTimeout(() => { oldAudio._isTearingDown = false; }, 600);`.
  3. Если пользователь нажимает Next дважды за 300 мс:
     - Трек 1 был на `audioA`, переключились на Трек 2 (`audioB`). Для `audioA` запущен таймер на 600 мс.
     - Через 300 мс переключаемся на Трек 3 (`audioA` снова становится `activeAudio`).
     - Еще через 300 мс (сумма 600 мс) срабатывает таймер от первого переключения и сбрасывает `audioA._isTearingDown = false`.
     - Асинхронная отмена сети браузера по первому треку генерирует событие `error` на `audioA`.
     - Слушатель `audio.addEventListener('error')` (`player.js:507-510`) видит: `audio === activeAudio` (истина, это `audioA`!), `_isTearingDown === false` (таймер уже сбросил его!), `audio.src` заполнен новым треком.
     - Ошибка отмены старого трека ошибочно трактуется как краш нового Трека 3 и запускает `handleStreamError(audio, 'error_event')`, срывая воспроизведение.
- **Proposed Fix**:
  - При очистке `oldAudio` в строке 581 явно вызывать: `if (oldAudio._hlsInstance) { try { oldAudio._hlsInstance.destroy(); } catch(e){} oldAudio._hlsInstance = null; }`.
  - Заменить таймаут со сбросом булева флага на инкрементный токен эпохи (`audio._teardownToken = (audio._teardownToken || 0) + 1`), чтобы таймер от старого переключения не мог снять защиту с активного трека.
- **Verification / Regression Test**: Стресс-тест быстрых вызовов `playTrack` с интервалом 100 мс: ни один валидный трек не должен прерываться ошибкой `handleStreamError`.

---

#### DEF-FE-04: Мертвый движок кроссфейда при наличии активных настроек в UI (DEAD_CONTROL Подтипы b, d)
- **Файл и строки**:
  - `ui/web_new_v2/js/player.js:68, 533, 544-547, 578-587`
  - `ui/web_new_v2/js/settings.js:103-111, 810-820`
  - `ui/web_new_v2/js/onboarding.js:156`
- **Severity**: P2
- **Симптом**: В настройках (Настройки -> Аудио -> Плавный переход) и в мастере онбординга присутствуют переключатель `toggle-crossfade` и слайдер длительности `slider-crossfade-sec`. Однако кроссфейд не работает: звук предыдущего трека обрывается мгновенно.
- **Root Cause**:
  1. В `player.js:533` объявлена переменная `let currentFadeInterval = null;`. В строках 544–547 она сбрасывается (`clearInterval(currentFadeInterval)`). Но она **нигде в коде не устанавливается**.
  2. В `playTrack` (`player.js:578-586`) старый трек останавливается безусловно и мгновенно:
     ```javascript
     if (oldAudio) {
         disarmStallFallback(oldAudio);
         oldAudio._isTearingDown = true;
         try { oldAudio.pause(); } catch(e) {}
         oldAudio.src = '';
     ```
  3. Двухэлементная архитектура (`audioA` и `audioB`) присутствует, но алгоритм плавного затухания/нарастания громкости между элементами не реализован.
- **Proposed Fix**: Реализовать расчет и запуск кроссфейда по таймеру/WebAudio gain при включенной опции `settings.audio.crossfade_enabled`, либо пометить функцию как DEFERRED и скрыть контрол из настроек до реализации.
- **Verification / Regression Test**: Проверка плавного перехода громкости в течение заданного количества секунд при смене трека.

---

#### DEF-FE-05: Отключенный эквалайзер и замерзший аудио-визуализатор (DEAD_CONTROL Подтипы b, d)
- **Файл и строки**:
  - `ui/web_new_v2/js/player.js:275-290, 318-328`
  - `ui/web_new_v2/js/equalizer.js:134-145`
  - `ui/web_new_v2/js/visualizer.js:184-220`
- **Severity**: P1
- **Симптом**:
  1. Перемещение ползунков 10-полосного эквалайзера и предусилителя не оказывает никакого влияния на звук.
  2. Визуализатор спектра (полосы в плеере) полностью замерз в нижнем положении (ровная горизонтальная линия `target = 0.04`) и не анимируется под музыку.
- **Root Cause**:
  1. В `player.js:278-279` вызовы `audioCtx.createMediaElementSource(audioA)` и `(audioB)` закомментированы из-за бага WebKitGTK (при подключении через AudioContext звук глушился в ALSA/PulseAudio). Звук выводится напрямую через движок GStreamer элемента `<audio>`.
  2. Цепочка WebAudio узлов (`preampNode -> 10 фильтров Biquad -> compressorNode -> analyserNode -> masterGainNode`) физически не имеет источника сигнала. Вся обработка эквалайзера в `equalizer.js` выполняется над абсолютной тишиной.
  3. В `player.js:318-328`:
     ```javascript
     export function getAudioFrequencyData(dataArray) {
         ...
         if (analyserNode && dataArray) {
             analyserNode.getByteFrequencyData(dataArray);
             return true;
         }
         return false;
     }
     ```
     Поскольку `analyserNode` инициализирован, функция всегда заполняет массив нулями и возвращает `true`.
  4. В `visualizer.js:184-220`:
     ```javascript
     let hasRealData = false;
     if (playing) {
         hasRealData = getAudioFrequencyData(freqData);
     }
     for (let i = 0; i < BAR_COUNT; i++) {
         if (playing) {
             let target = 0;
             if (hasRealData) {
                 const val = freqData[freqIdx] || 0;
                 target = (val / 255.0) * Math.max(0.3, volScale); // ВСЕГДА 0!
             } else {
                 // Сюда код НИКОГДА не попадает! (генератор псевдо-спектра заблокирован)
                 ...
             }
             bar.target = Math.max(0.04, Math.min(1, target)); // ВСЕГДА 0.04
     ```
     Возврат `true` из `getAudioFrequencyData` блокирует ветку `else` с процедурной анимацией спектра. В итоге визуализатор висит неподвижно на минимальном значении 0.04.
- **Proposed Fix**:
  - В `player.js:325`: проверять наличие реального ненулевого сигнала (`dataArray.some(v => v > 0)`), и если все байты равны 0 (или нет подключенного `srcA/srcB`), возвращать `false`.
  - В `visualizer.js:186`: `hasRealData = getAudioFrequencyData(freqData) && freqData.some(v => v > 0);`. Это немедленно активирует процедурный генератор визуализатора под музыку.
  - По эквалайзеру: зафиксировать как DEFERRED архитектурное ограничение Linux WebKitGTK либо реализовать программный fallback.
- **Verification / Regression Test**: Проверка функции `visualizer.js`: при воспроизведении трека полосы должны динамически двигаться, а не стоять на отметке 0.04.

---

### Направление 2: Библиотека, Плейлисты и контекстные меню

#### DEF-FE-06: Пакетное добавление в плейлист сбрасывает все выбранные треки кроме первого (DEAD_CONTROL Подтипы d, PARTIAL)
- **Файл и строки**:
  - `ui/web_new_v2/js/utils.js:1088-1098`
  - `ui/web_new_v2/js/library.js:927-957`
- **Severity**: P1
- **Симптом**: При выделении нескольких треков через чекбоксы в библиотеке и нажатии кнопки "В плейлист" на плавающей панели действий (batch action bar), в выбранный плейлист добавляется только самый первый трек (`tracks[0]`). Все остальные выбранные треки молча теряются.
- **Root Cause**:
  1. В `utils.js:1088-1098` обработчик клика передает массив треков 4-м аргументом:
     ```javascript
     const tracks = Array.from(selectedTracksMap.values());
     window.NeDotify.openPlaylistMenu(tracks[0], e.clientX, e.clientY, tracks);
     ```
  2. В `library.js:927` сигнатура метода объявлена с тремя аргументами: `export function openPlaylistMenu(track, x, y)`. Четвертый аргумент игнорируется.
  3. В `library.js:928` сохраняется только один трек: `currentContextTrack = track;`.
  4. При клике на плейлист в меню (`library.js:954`) выполняется:
     ```javascript
     await window.pywebview.api.add_to_playlist(plId, currentContextTrack);
     ```
     В бэкенд уходит только первый трек.
- **Proposed Fix**:
  Обновить сигнатуру `openPlaylistMenu(track, x, y, multiTracks = null)`. Сохранять массив `currentContextTracks = multiTracks && multiTracks.length > 0 ? multiTracks : [track];`. При клике на пункт плейлиста отправлять все выбранные треки в цикле или одним вызовом.
- **Verification / Regression Test**: Выбрать 3 трека, нажать "В плейлист", убедиться, что все 3 трека появились в выбранном плейлисте.

---

#### DEF-FE-11: Мертвые кнопки-заглушки в контекстном меню трека (DEAD_CONTROL Подтип b)
- **Файл и строки**:
  - `ui/web_new_v2/js/utils.js:754-756, 772-774`
- **Severity**: P2
- **Симптом**: В контекстном меню любого трека пункты "Не интересно" (Dislike) и "Кэшировать" выводят всплывающее сообщение "Функция пока недоступна" и не выполняют никаких действий.
- **Root Cause**: В обработчике `context-menu-item`:
  ```javascript
  case 'dislike':
      showToast(`Функция пока недоступна (Не интересно)`, 'info');
      break;
  case 'cache':
      showToast(`Функция пока недоступна (Кэшировать)`, 'info');
      break;
  ```
  Код обработчиков является жестко зашитой заглушкой.
- **Proposed Fix**: Либо скрыть данные пункты из меню (`display: none`), либо связать с соответствующими бэкенд-методами (если они поддержаны).

---

### Направление 3: Поиск и Тексты песен (Lyrics)

#### DEF-FE-07: Гонка очистки поисковой строки перезаписывает пустой экран устаревшими результатами (DEAD_CONTROL Подтип f)
- **Файл и строки**:
  - `ui/web_new_v2/js/search.js:84-93, 250-256`
- **Severity**: P2
- **Симптом**: Если пользователь ввел поисковый запрос, а затем нажал на кнопку очистки строки (крестик `#search-clear`), поле очищается и появляется placeholder. Однако через 1–2 секунды с бэкенда приходят запоздалые результаты отмененного поиска и самопроизвольно заполняют страницу результатами.
- **Root Cause**:
  1. При клике на крестик (`search.js:90`) переменная запроса обнуляется: `currentSearchQuery = '';`.
  2. При получении события `search_results` (`search.js:254`) выполняется проверка актуальности:
     ```javascript
     if (data.query && currentSearchQuery && data.query.trim().toLowerCase() !== currentSearchQuery.trim().toLowerCase()) {
         return; // Stale result — ignore
     }
     ```
  3. Поскольку `currentSearchQuery` пустая (`''` ложно в JS), условие `data.query && currentSearchQuery && ...` вычисляется в `false`. Выход из функции не происходит.
  4. Функция продолжает выполнение (`search.js:265`), наполняет `allResults` треками отмененного запроса и рендерит их в DOM (`renderResults(allResults)`).
- **Proposed Fix**:
  Изменить условие валидации на:
  ```javascript
  if (!currentSearchQuery || (data.query && data.query.trim().toLowerCase() !== currentSearchQuery.trim().toLowerCase())) {
      return;
  }
  ```
  Если `currentSearchQuery` пустая, любые пришедшие результаты считаются неактуальными.
- **Verification / Regression Test**: Ввести запрос "rock", быстро нажать на крестик очистки и подождать 3 секунды: страница поиска должна оставаться чистой.

---

#### DEF-FE-08: Рендеринг сырого Python-исключения вместо текста песни в контейнере Lyrics (DEAD_CONTROL Подтипы d, f)
- **Файл и строки**:
  - `core/api.py:2468`
  - `ui/web_new_v2/js/lyrics.js:333-337, 400-410`
- **Severity**: P2
- **Симптом**: Если сервис текстов песен не смог получить текст или произошла сетевая ошибка, на экране текстов вместо аккуратного сообщения "Текст песни не найден" крупным шрифтом рендерится техническое сообщение вида: `Could not fetch lyrics: ConnectionError(...)` в качестве строк песни.
- **Root Cause**:
  1. В `core/api.py:2468` при ошибке поиска бэкенд возвращает словарь:
     ```python
     data = {"synced": False, "lyrics": f"Could not fetch lyrics: {e}"}
     ```
  2. Во фронтенде в `lyrics.js:335` нормализатор данных считывает поле:
     ```javascript
     plainLyrics: data.plainLyrics || data.plain_lyrics || data.lyrics ...
     ```
     Строка ошибки записывается в `normalizedData.plainLyrics`.
  3. Проверка на пустоту текста (`lyrics.js:343`) считает эту строку валидным текстом песни и передает ее в `renderPlainLyrics()`.
  4. Строка ошибки оборачивается в `<div class="lyric-line lyric-plain">` и выводится пользователю.
- **Proposed Fix**:
  - В `core/api.py:2468`: передавать `{"synced": False, "lyrics": None, "error": str(e)}`.
  - В `lyrics.js:335`: фильтровать строки ошибок: `if (typeof data.lyrics === 'string' && data.lyrics.startsWith('Could not fetch lyrics:')) normalizedData.plainLyrics = null;`.
- **Verification / Regression Test**: Запросить текст для несуществующего трека без интернета: на экране должно отображаться "Текст песни не найден", а не строка `Could not fetch lyrics: ...`.

---

#### DEF-FE-09: Гонка текстов при быстром переключении треков (DEAD_CONTROL Подтип d)
- **Файл и строки**:
  - `ui/web_new_v2/js/lyrics.js:203-205, 215-217, 320-330`
- **Severity**: P2
- **Симптом**: При быстром переключении с Трека 1 на Трек 2, если запрос текста для Трека 1 выполнялся медленно, его текст может внезапно перезаписать текст Трека 2 на экране.
- **Root Cause**:
  Слушатель события `nedotify:lyrics_ready` (`lyrics.js:215-217`) принимает `e.detail` и сразу вызывает `renderLyrics(e.detail)`. В `renderLyrics` отсутствует проверка соответствия идентификатора или названия трека в `data` текущему воспроизводимому треку (`currentTrack`).
- **Proposed Fix**: Добавить в событие `lyrics_ready` идентификатор или метаданные трека (`track_id` / `title`) и в `renderLyrics(data)` проверять соответствие с `currentTrack`.
- **Verification / Regression Test**: Проверить последовательную загрузку текстов двух разных треков с искусственной задержкой первого ответа.

---

### Направление 4: Мост событий и обработчики `events.js`

#### DEF-FE-10: Пропущенные, заглушенные и фиктивные события в `events.js` (DEAD_CONTROL Подтипы d, b)
- **Файл и строки**:
  - `core/api.py:182, 1166, 1284, 3100`
  - `ui/web_new_v2/js/events.js:82, 144, 218-220, 292-294`
- **Severity**: P2
- **Симптом**:
  1. Ошибки bridge-вызовов (`api_error`) не отображаются пользователю;
  2. Редактирование тегов трека (`track_updated`) не обновляет карточки треков в реальном времени;
  3. Изменения настроек с бэкенда (`setting_changed`) игнорируются;
  4. Присутствуют обработчики несуществующих событий бэкенда (`yt_playlist_ready`, `mood_playlists_ready`).
- **Root Cause**:
  1. Событие `api_error` (`core/api.py:182`) отсутствует в `switch (eventName)` в `events.js`, уходит в `default:` и пишется только в консоль.
  2. Событие `track_updated` (`core/api.py:3100`) отсутствует в `events.js`.
  3. Событие `setting_changed` (`events.js:218-220`) содержит пустой `break;`.
  4. Метод `stop_track` на бэкенде (`core/api.py:1166`) содержит пустой `pass`.
  5. События `yt_playlist_ready` (`events.js:82`) и `mood_playlists_ready` (`events.js:144`) прописаны во фронтенде, но бэкенд их нигде не эмитит (мертвый код).
- **Proposed Fix**: Добавить обработчики `api_error` (вызов тоста) и `track_updated` (обновление UI активного трека), заполнить тело `setting_changed`, удалить неиспользуемые слушатели.

---

#### DEF-FE-12: Мертвый fallback-селектор `#pb-volume-slider` в горячих клавишах (DEAD_CONTROL Подтип a)
- **Файл и строки**:
  - `ui/web_new_v2/js/hotkeys.js:235-240, 247-252`
- **Severity**: P3
- **Симптом**: Если метод `window.NeDotify.adjustVolume` еще не готов или недоступен, горячие клавиши громкости (`Ctrl+Up`, `Ctrl+Down`) молча не работают.
- **Root Cause**: Обработчики `volume_up` и `volume_down` содержат fallback:
  ```javascript
  const slider = document.getElementById('pb-volume-slider');
  ```
  Элемент с ID `#pb-volume-slider` присутствовал в старой версии `web_new`, но в `web_new_v2` полоса громкости реализована как кастомный трек `#pb-volume-track`. Селектор возвращает `null`.
- **Proposed Fix**: Использовать селектор `#pb-volume-track` или экспортировать функцию `setVolume` напрямую из `player.js`.

---

## 3. Матрица согласования событий (Backend Emitter vs Frontend Listener)

| Событие | Источник (Python) | Обработчик (JS) | Статус согласованности | Примечание / Дефект |
|:---|:---|:---|:---:|:---|
| `track_changed` | `core/api.py:847, 1071` | `events.js:35` | OK | Синхронизировано |
| `state_changed` | `core/api.py:835` | `events.js:41` | DEFECT | Асинхронное эхо ломает состояние (DEF-FE-02) |
| `position_changed` | `core/api.py:876` | `events.js:47` | DEFECT | Эхо с задержкой вызывает jitter текстов (DEF-FE-01) |
| `search_results` | `core/api.py:346` | `events.js:66` | DEFECT | Гонка при очистке поисковой строки (DEF-FE-07) |
| `search_completed` | `core/api.py:355` | `events.js:71` | OK | Синхронизировано |
| `lyrics_ready` | `core/api.py:2473` | `events.js:235` | DEFECT | Рендерит строку ошибки как текст (DEF-FE-08, 09) |
| `playlists_updated`| `core/api.py:2022` | `events.js:154` | PARTIAL | Несогласованный payload (DEF-BE-04) |
| `api_error` | `core/api.py:182` | `events.js:292` | DEAD | Событие падает в default (DEF-FE-10) |
| `track_updated` | `core/api.py:3100` | `events.js:292` | DEAD | Слушатель отсутствует (DEF-FE-10) |
| `setting_changed` | `core/api.py:1284` | `events.js:218` | DEAD | Пустой stub `break;` (DEF-FE-10) |
| `yt_playlist_ready`| Не эмитится | `events.js:82` | DEAD | Мертвый слушатель во фронтенде (DEF-FE-10) |
| `mood_playlists_ready`| Не эмитится | `events.js:144`| DEAD | Мертвый слушатель во фронтенде (DEF-FE-10) |
| `download_progress`| `core/downloader.py:228`| `events.js:125`| OK | Синхронизировано |
| `download_completed`| `core/downloader.py:237`| `events.js:129`| OK | Синхронизировано |
| `download_error` | `core/downloader.py:246`| `events.js:133`| OK | Синхронизировано |

---

## 4. Рекомендации по исправлению (Remediation Plan)

1. **Изоляция эхо-событий плеера (DEF-FE-01, DEF-FE-02)**:
   - В `player.js` разделить локальные UI-события от системных команд.
   - В `events.js` не ретранслировать события позиции и состояния в DOM, если они порождены локальным воспроизведением текущего окна.
   - В `onStateChanged('stopped')` гарантировать вызов `activeAudio.pause()`.

2. **Защита от утечек HLS и гонок жизненного цикла (DEF-FE-03)**:
   - В `playTrack` при переключении аудио гарантированно вызывать `destroy()` на `oldAudio._hlsInstance`.
   - Заменить статический таймаут 600 мс на токен поколения (epoch token) для флага `_isTearingDown`.

3. **Восстановление визуализатора и фиксация эквалайзера (DEF-FE-05)**:
   - В `visualizer.js` проверять `freqData.some(v => v > 0)` для переключения на синтетический спектр при отсутствии реального звукового входа.

4. **Исправление пакетных операций плейлистов (DEF-FE-06)**:
   - Передавать полный массив выбранных треков в `openPlaylistMenu` и выполнять добавление всех треков в выбранный плейлист.

5. **Стабилизация поиска и текстов (DEF-FE-07, DEF-FE-08, DEF-FE-09)**:
   - Проверять валидность `currentSearchQuery` при обработке результатов поиска.
   - Не передавать технические строки исключений в качестве текстов песен.
   - Сверять `track_id` входящих текстов песен с текущим треком перед рендерингом.
