# docs/perf/prof_python_startup.md — профиль Python-старта и idle CPU, 2026-10-03

Измерение, **не** оптимизация. Ни один файл проекта не менялся: единственные
новые файлы — `tools/bench/pyprof_child.py`, `tools/bench/run_pyprof.py`,
`tools/bench/sleepscan.py`, `tools/bench/thread_lineage.py`,
`tools/bench/read_pyprof.py`, `tools/bench/query_pstats.py`,
`tools/bench/check_pstats_consistency.py`, `tools/bench/import_chains.py`,
`tools/bench/report_numbers.py` и артефакты в `tools/bench/results/`.

Как всё запускается (одна команда, ~8 минут):

```
.venv_win\Scripts\python.exe tools\bench\run_pyprof.py --reps 7 --idle-seconds 60 --settle 15 --pyspy-seconds 60
```

**Стенд.** 13th Gen Intel Core i5-13420H, 12 логических ядер, Windows.
CPython 3.14.7 в `.venv_win`. Снимок результатов: `2026-10-03T22:05:49+0300`.

**Изоляция профиля.** Весь проект строит состояние из
`os.path.expanduser("~") + "/.nedotify"`, а переменной-override нет. Поэтому
каждый дочерний процесс стартует с `USERPROFILE`, указывающим на свежий
scratch-каталог, и с пустыми `HOMEDRIVE`/`HOMEPATH` — иначе
`ntpath.expanduser` не увидит подмены. Проверено: после подмены приложение
создаёт `.nedotify/` целиком в scratch и не трогает настоящий профиль.
Проверку делает `pyprof_child._redirect_profile()`: она падает, если
`os.path.expanduser("~")` после подмены указывает не туда.

**GUI не запускался ни разу.** `webview.start()` лежит внутри `main()`;
`import main` исполняет только тело модуля (env + `from core.app import AppCore`),
а режимы `AppCore` вообще не вызывают `main()`. Мьютекс одиночного экземпляра
(`main.py:_acquire_instance_lock`) не запрашивался, так что уже работающий
экземпляр NeDotify не затронут.

---

## Сводная таблица

| Метрика | Медиана | n прогонов | Файл-подтверждение |
|---|---|---|---|
| Загрузка интерпретатора, `python -c pass` (wall, включая создание процесса) | **60.79 мс** | 7 | `profile_python_startup.json` → `measurement.interpreter_and_imports.interpreter_floor_ms` |
| Модули при загрузке интерпретатора (сумма self, `-X importtime -c pass`) | 10.47 мс | 1 | …`interpreter_floor_importtime` |
| `python -X importtime -c "import main"`, wall | **553.66 мс** | 7 | …`import_main_wall_ms` |
| … минус пол загрузки интерпретатора | 492.10 мс | 7 | …`import_main_wall_minus_floor_ms` |
| … CPU в телах модулей (сумма **self**) | **404.45 мс** | 7 | …`import_main_import_self_ms` |
| … кумулятивно по корню `main` | **388.70 мс** | 7 | …`import_main_root_cum_ms` |
| … остаток (`wall − floor − root_cum`), не атрибутирован дальше | 104.17 мс | 7 | арифметика из тех же полей |
| Импортировано модулей | 588 | — | …`representative_breakdown.n_modules` |
| `AppCore()` — внутренний таймер ребёнка | **46.12 мс** | 7 | …`appcore_init.child_reported_ms` |
| `AppCore()` — wall всего процесса (python + `import core.app` + конструктор) | 664.51 мс | 7 | …`appcore_init.process_wall_ms` |
| `AppCore()` под cProfile (профилируемое окно) | 76.94 мс | 1 | …`appcore_cprofile`; `profile_appcore_init.pstats` |
| Асинхронный `_get_ydl` после возврата конструктора | **110.72 мс** | 7 | …`appcore_breakdown.async_drain_after_constructor_ms` |
| Конструктор `AppCore()` суммарно (обёрнутый замер по шагам) | 49.09 мс | 7 | …`appcore_breakdown.total_constructor_ms` |
| … из них атрибутировано по шагам | 48.23 мс | 7 | …`appcore_breakdown.main_thread_steps_median_sum_ms` |
| … не атрибутировано | 0.86 мс | 7 | …`appcore_breakdown.unattributed_main_thread_ms` |
| Python-потоков после конструктора | 9 | 1 | …`appcore_init.threads` |
| OS-потоков живо сразу после конструктора (контроль без `AppCore` — 5) | 18 | 1 | …`idle_cpu.with_appcore.os_threads_created_during_build` |
| Idle CPU, окно 60.51 с, без измерительного хвоста | **0.2344 с = 0.3873 % одного ядра** | 1 | …`idle_cpu.with_appcore.idle_window_cpu_s_excl_harness` |
| Idle CPU, контроль без `AppCore`, окно 60.56 с | **0.0312 с = 0.0516 %** | 1 | …`idle_cpu.control_no_appcore.idle_window_cpu_s_excl_harness` |
| Idle CPU, приписываемый `AppCore` (разность) | 0.2032 с = 0.336 % одного ядра | выведено | разность двух строк выше |
| Пробуждений `watchdog_service.py:54` | 0.9932 Гц | 1 окно (75.51 с) | …`sleep_and_wait_sites` |
| Пробуждений `downloader.py:312` | 0.9800 Гц | 1 окно | там же |
| Пробуждений `lufs_scanner.py:70` | 0.0265 Гц | 1 окно | там же |
| Пробуждений `core/app.py:166` | 0 (0 ожидаемых за 60 с) | 1 окно | …`idle_cpu.with_appcore.wake_log` |
| Всего мест `sleep`/`wait` в коде | 47 (из них 3 живы в idle-окне) | — | …`sleep_and_wait_sites.n_sites` |
| py-spy | доступен, но **непригоден** для idle-атрибуции: 6 сэмплов на 60 с @100 Гц | 1 | `pyspy_idle.speedscope.json`, `pyspy_idle.svg` |

Методические оговорки, важные для всех чисел:

* Wall-время процесса измерено вокруг `subprocess.run`, т.е. включает
  `CreateProcess`. Пол загрузки интерпретатора измерен тем же способом, поэтому
  вычитание корректно.
* CPU-счётчик Windows имеет квант **15.625 мс**. Все «idle CPU» — целое число
  квантов; на окне 60 с погрешность суммы по потокам = ±15.6 мс на поток.
* Каждый прогон `AppCore()` и `import main` — **отдельный процесс** со свежим
  scratch-профилем. Разброс между прогонами существенный: `import main` даёт
  479…643 мс (sd 59.9), `AppCore()` — 38.3…58.7 мс (sd 9.3). Источники —
  состояние файлового кэша ОС и Defender, а также DNS (см. `getfqdn` ниже).
  Поэтому везде приведены медиана, min, max и sd, а не одно число.

---

## 1. Стоимость интерпретатора и импортов

Метод: `python -X importtime -c "import main"` и
`python -X importtime -c pass`, по 7 прогонов, `cwd` = корень репозитория,
stderr разбирается в дерево по отступам.

Все **времена** в этом разделе взяты из сохранённого прогона
(`profile_python_startup.json`). **Родство** модулей (кто что тянет) проверено
отдельно скриптом `tools/bench/import_chains.py`; родство стабильно между
прогонами, а вот абсолютные cum-значения в нём на 10–25 % выше (например
`asyncio` 22.1 мс против 23.72 мс в сохранённом прогоне) — поэтому числа
берутся только из JSON, а из цепочек — только стрелки.

### Про `self` против `cum`

`-X importtime` печатает две колонки:

* **self** — время исполнения тела самого модуля, **без** потомков. Суммируется
  по всем строкам и даёт реальную CPU в импортах (здесь: 404.45 мс).
* **cum** — время вместе со всеми вложенными импортами. Складывать `cum` по
  соседям нельзя (поддеревья пересекаются), поэтому в отчёте суммируются `cum`
  только **непересекающихся внешних** узлов.

`-X importtime` печает строку модуля **после** его потомков (post-order), поэтому
простая привязка «родитель = ближайшая предыдущая строка меньшей глубины»
даёт неверное дерево. `run_pyprof._link_parents()` разворачивает список
(обратный post-order = pre-order) и только потом применяет стековый алгоритм.

### Прямые импорты `main.py`

`main.py` на верхнем уровне импортирует `logging`, `multiprocessing`, `os`,
`sys`, `threading`, `socketserver`, `webview`, `bottle`, `logging.handlers`,
`core.app`, `core.api`. Кумулятивные затраты (представительный прогон):

| Прямой импорт `main` | cum, мс | self, мс |
|---|---:|---:|
| `core.app` (`main.py:147`) | **258.18** | 1.95 |
| `webview` (`main.py:19`) | **67.18** | 1.44 |
| `logging` (`main.py:7`) | **49.59** | 2.69 |
| `multiprocessing` (`main.py:8`) | 7.76 | 0.47 |
| `logging.handlers` (`main.py:97`) | 2.32 | 0.85 |
| `socketserver` (`main.py:13`) | 2.05 | 0.70 |

Сумма ≈ 387.1 мс при `root_cum` = 388.70 мс; на само тело `main.py` приходится
≈ 1.6 мс (создание каталога логов, `basicConfig`, патч `bottle.run`, DoH-патч,
`freeze_support`).

### Что именно тянет каждый дорогой импорт — измеренное родство

Родство подтверждено деревом `-X importtime`
(`tools/bench/import_chains.py`), числа взяты из сохранённого прогона:

```
main -> core.app -> services.vk_service -> yt_dlp            (103.05 мс, 70 модулей)
main -> core.app -> services.spotify_service -> requests      (77.37 мс, 18 модулей)
main -> core.app -> services.youtube_service -> ytmusicapi     (25.98 мс, 52 модуля)
main -> core.app -> services.lyrics_service                   (10.07 мс self)
main -> core.app -> core.services.discord_rpc -> pypresence   (3.13 мс)
main -> webview -> webview.http -> {bottle, wsgiref.simple_server -> http.server, ssl}
main -> logging -> {traceback -> _colorize -> dataclasses -> inspect, re}
main -> multiprocessing -> multiprocessing.reduction -> socket
```

Ключевые неочевидные вещи:

* **`services/vk_service.py:10` — `import yt_dlp` в `try` на верхнем уровне.**
  Это первая по алфавиту причина, по которой `core/app.py:26` тянет весь yt-dlp
  (103.05 мс, self 50.99 мс, 70 модулей). Внутри `yt_dlp` самые дорогие
  поддеревья — `yt_dlp.downloader.external` → `yt_dlp.downloader` (65.83 мс) и
  `yt_dlp.cookies` (26.25 мс). Экстракторов (`yt_dlp.extractor.*`) при старте
  импортируется всего **5** модулей (на диске их 972): yt-dlp грузит их лениво.
  Тяжёлые stdlib/сторонние зависимости приходят именно отсюда: `asyncio`
  (23.72 мс) через `yt_dlp.downloader.websocket`, `mutagen` (18.26 мс) через
  `yt_dlp.dependencies`, `brotlicffi`, `certifi`, `websockets`.
* **`services/spotify_service.py:6` — `import requests`** (77.37 мс
  включительно; `requests` → `urllib3` 36.10 мс → `charset_normalizer` 11.83 мс,
  `certifi`, `idna`, `http.cookiejar`).
* **`services/youtube_service.py:24` — `from ytmusicapi import YTMusic`**
  (25.98 мс, self 24.06 мс на 52 модулях — почти всё в его собственном коде).
* **`main.py:7 import logging` стоит 49.59 мс** на CPython 3.14: `logging`
  тянет `traceback`, а тот — новый в 3.14 `_colorize` (self 6.34 мс), который
  тянет `dataclasses` → `inspect`. Плюс `re` 15.16 мс.
* **`webview` 67.18 мс**: `webview/http.py:26` подтягивает
  `wsgiref.simple_server` → `http.server` (→ `email`, `http.client`),
  `webview/http.py:31` — `bottle` (12.91 мс), `webview/http.py:21` — `ssl`
  (7.43 мс). `webview.platforms.*` / `clr` / `pythonnet` в дереве **отсутствуют**.

### Топ-сторонние пакеты по инклюзивной стоимости (непересекающиеся поддеревья)

| Семейство | cum, мс | self, мс | модулей |
|---|---:|---:|---:|
| `yt_dlp` | 103.05 | 50.99 | 70 |
| `requests` | 77.37 | 15.05 | 18 |
| `webview` | 67.18 | 7.82 | 15 |
| `logging` | 51.91 | 3.53 | 2 |
| `urllib3` | 36.10 | 28.85 | 30 |
| `ytmusicapi` | 25.98 | 24.06 | 52 |
| `asyncio` | 23.72 | 20.90 | 32 |
| `http` | 20.40 | 7.96 | 5 |
| `_colorize` (из `traceback` ← `logging`) | 20.08 | 6.34 | 1 |
| `mutagen` | 18.26 | 16.01 | 26 |
| `re` | 15.16 | 5.27 | 5 |
| `bottle` | 12.91 | 4.01 | 1 |
| `charset_normalizer` | 11.83 | 11.78 | 8 |
| `email` | 10.29 | 7.22 | 15 |
| `ssl` | 7.43 | 2.43 | 1 |
| `watchdog` | 5.41 | 5.42 | 10 |
| `pypresence` | 3.13 | 3.13 | 8 |

### Ответ про numpy / scipy / PIL / pythonnet

**Ни один из них не импортируется при старте** — это измерено, а не
предположение. В дереве `import main` отсутствуют: `numpy`, `scipy`, `PIL`
(`Pillow`), `pystray`, `clr`, `pythonnet`, `cryptography`, `colorama`, `wave`.
Причины видны в коде: `services/lufs_scanner.py:19-21` импортирует
`miniaudio`/`pyloudnorm`/`numpy` внутри `analyze_lufs`, а `core/tray.py:14-16`
(`PIL`, `pystray`) импортируется лениво из метода `core/api.py:339`.
`wave` нужен только для записи тегов.

`numpy` при этом платит отдельную цену позже: первый вызов `analyze_lufs`
импортирует `numpy`. Величина этой задержки **здесь не измерена** — в idle-окне
нет локальных треков без `lufs`, поэтому импорт не происходит (см. «Не удалось
измерить»).

### Самые дорогие отдельные модули по self

`self=10.07 мс services.lyrics_service` · `6.34 _colorize` ·
`5.84 urllib3.util.url` · `4.51 yt_dlp.utils._utils` · `4.41 charset_normalizer.cd` ·
`4.32 _ssl` · `4.10 urllib3.response` · `4.01 bottle` · `3.58 http.cookiejar` ·
`3.34 inspect` · `3.14 asyncio.events` · `2.78 mutagen.id3._frames`.

---

## 2. Стоимость конструирования `AppCore`

`AppCore.__init__` (`core/app.py:93-174`) конструирует ~21 сервис, поднимает
10 потоков и три фоновых вызова. Измерено тремя независимыми способами; все
дают один порядок величины.

| Способ | Медиана | n |
|---|---:|---:|
| `perf_counter` вокруг `AppCore()` в отдельном процессе | 46.12 мс | 7 |
| То же, но конструктор дополнительно обёрнут таймерами по шагам | 49.09 мс | 7 |
| cProfile-окно вокруг `AppCore()` (профайлер искажает) | 76.94 мс | 1 |

После конструктора живы **9 Python-потоков**:

```
CacheCleanup, MainThread, Thread-1 (_process_queue), Thread-2,
Thread-3 (_process_pending), Thread-6 (_bg), Thread-7 (serve_forever),
Thread-8 (_scan_loop), ThreadPoolExecutor-1_0
```

Родство каждого потока **измерено** скриптом `tools/bench/thread_lineage.py`,
который подменяет `threading.Thread.__init__` в дочернем процессе и печатает
создателя (`file:line`) плюс target для каждого потока в порядке создания:

| # | Поток (имя) | Что это | Где создаётся |
|---:|---|---|---|
| 1 | `ThreadPoolExecutor-1_0` | воркер `youtube_service._get_ydl` | `services/youtube_service.py:145` → `concurrent/futures/thread.py:233` |
| 2 | `Thread-1 (_process_queue)` | обработчик очереди загрузок | `core/downloader.py:47` |
| 3 | `Thread-2` | эмиттер `WindowsApiObserver` (класс `BaseThread` из watchdog) | `watchdog/utils/__init__.py:39` ← `core/app.py:133` (создание `Observer()`) |
| 4 | `Thread-3 (_process_pending)` | выдержка «файл докачан» перед импортом | `services/watchdog_service.py:33` |
| 5 | `Thread-4` (живёт <1 с) | `discord_rpc._connect` | `core/services/discord_rpc.py:85` |
| 6 | `Thread-5` (живёт <1 с) | `update_ytdlp_safely` | `core/app.py:140` |
| 7 | `Thread-6 (_bg)` | фоновое автообновление Zapret | `services/zapret_service.py:868` |
| 8 | `Thread-7 (serve_forever)` | loopback HTTP-прокси | `core/proxy.py:1177` |
| 9 | `Thread-8 (_scan_loop)` | LUFS-сканер | `services/lufs_scanner.py:48` |
| 10 | `CacheCleanup` | чистка `stream_cache` по `expires_at` | `core/app.py:174` |

Потоки 5 и 6 к моменту снимка уже завершились, поэтому в списке живых их нет.

### cProfile: топ-25 по кумулятивному времени

Файл: `tools/bench/results/profile_appcore_init.pstats`
(`sort='cumulative'`; один прогон, профилируемое окно 76.94 мс).

**Оговорка о надёжности этого файла (проверено, не предположено).**
`tools/bench/check_pstats_consistency.py` ищет строки, у которых сумма
`cumtime` по исходящим рёбрам заметно больше собственного `cumtime`: таких
строк 22 из 714, и во всех ломается именно на кадрах, которые **запускают
потоки** (`threading.py:975 start`, `concurrent/futures/thread.py:199 submit`,
`core/app.py:93 AppCore.__init__`, `services/youtube_service.py:114
YouTubeService.__init__`, `core/downloader.py:25`, `services/watchdog_service.py:28/79`
и т.д.). Пример: у `core/app.py:93(__init__)` стоит `cumtime=0.135 мс` при
`ncalls=2`, хотя ребро `app.py:93 → database.py:79` несёт 20.822 мс. То есть
**собственная строка родителя недостоверна**, а cum поддерева (у листьев и у
непорождающих потоки кадров) — достоверна: там `cumtime == сумма рёбер`
(`database.py:79` 20.822 = 20.822, `youtube_service.py:171 _get_ydl`
31.714 = 31.714). Поэтому ниже приводятся cum листьев и непорождающих кадров,
а пошаговая атрибуция (§3) сделана независимо, на `perf_counter`, и именно
она является источником истины по «кто сколько стоит».

| # | cum, мс | self, мс | ncalls | file:line | func |
|---:|---:|---:|---:|---|---|
| 1 | 31.742 | 0.010 | 1 | `concurrent/futures/thread.py:97` | `_worker` |
| 2 | 31.731 | 0.006 | 1 | `concurrent/futures/thread.py:81` | `run` |
| 3 | 31.721 | 0.007 | 1 | `concurrent/futures/thread.py:71` | `run` |
| 4 | **31.714** | 0.012 | 1 | `services/youtube_service.py:171` | `_get_ydl` |
| 5 | 21.363 | 0.075 | 1 | `ytmusicapi/ytmusic.py:53` | `__init__` |
| 6 | 20.822 | 0.043 | 1 | `core/database.py:79` | `__init__` |
| 7 | 20.508 | 0.093 | 1 | `core/database.py:135` | `_init_database` |
| 8 | 20.337 | 0.043 | 1 | `locale.py:599` | `setlocale` |
| 9 | **20.332** | 20.332 | 1 | `<builtin>` | `_locale.setlocale` |
| 10 | 15.435 | 11.876 | 48 | `<builtin>` | `sqlite3.Cursor.execute` |
| 11 | 14.630 | 0.096 | 2 | `services/youtube_service.py:209` | `_get_ydl_opts` |
| 12 | 14.546 | 0.106 | 2 | `services/youtube_service.py:37` | `_detect_browser_cookies` |
| 13 | 12.916 | 0.028 | 1 | `yt_dlp/YoutubeDL.py:634` | `__init__` |
| 14 | 12.720 | 0.047 | 2 | `yt_dlp/cookies.py:116` | `extract_cookies_from_browser` |
| 15 | 12.689 | 2.324 | 2 | `yt_dlp/cookies.py:127` | `_extract_firefox_cookies` |
| 16 | 10.033 | 0.003 | 1 | `yt_dlp/utils/_utils.py:4822` | `windows_enable_vt_mode` |
| 17 | 10.031 | 0.004 | 1 | `yt_dlp/utils/_utils.py:1478` | `get_windows_version` |
| 18 | 10.026 | 0.007 | 1 | `platform.py:464` | `win32_ver` |
| 19 | 10.019 | 0.004 | 1 | `platform.py:405` | `_win32_ver` |
| 20 | 10.015 | 0.005 | 1 | `platform.py:338` | `_wmi_query` |
| 21 | 10.008 | 4.418 | 1 | `<builtin>` | `_wmi.exec_query` |
| 22 | 9.208 | 0.015 | 8 | `core/database.py:131` | `conn` |
| 23 | 9.194 | 8.371 | 8 | `core/database.py:107` | `_get_connection` |
| 24 | 3.382 | 0.006 | 1 | `core/services/discord_rpc.py:68` | `_connect` |
| 25 | 3.368 | 0.006 | 1 | `pypresence/presence.py:83` | `connect` |

Топ по **self**: `_locale.setlocale` 20.332 · `sqlite3.Cursor.execute` 11.876
(ncalls 48) · `core/database.py:107 _get_connection` 8.371 (n=8) ·
`_wmi.exec_query` 4.418 · `_socket.gethostbyaddr` 3.087 ·
`http.cookiejar:1228 deepvalues` 2.407 (n=**6250**) ·
`_extract_firefox_cookies` 2.324 · `lock.acquire` 1.702 · `nt.mkdir` 1.688 ·
`sqlite3.Cursor.fetchall` 1.058.

### Что это значит простыми словами

* **`_locale.setlocale` — 20.33 мс: самая дорогая отдельная функция по self-времени
  во всём профиле конструктора, и это не наш код.**
  `services/youtube_service.py:135` вызывает `YTMusic(language="ru", …)`, а
  `ytmusicapi/ytmusic.py:142` на этом делает
  `locale.setlocale(locale.LC_ALL, self.language)` — то есть **глобально**
  переключает локаль процесса на `ru`. Цепочка вызовов снята из pstats
  (`tools/bench/query_pstats.py --callers-of windows_enable_vt_mode`-формат,
  точнее `--callers-of "locale.py:599"`): `locale.py:599 setlocale <-
  ytmusicapi/ytmusic.py:53 __init__ <- services/youtube_service.py:114 __init__`.
  На этой машине первичная загрузка локали `ru` стоит 20.33 мс. Побочный
  эффект тот же: смена `LC_ALL` влияет на всё, что дальше форматирует
  числа/даты.
* **`_detect_browser_cookies` — 14.55 мс** внутри профилируемого окна
  (`services/youtube_service.py:37`, вызывается из `_get_ydl_opts:272`, когда
  ни `cookiefile`, ни `cookiesfrombrowser` не настроены). Она перебирает
  firefox → chrome → edge → brave → opera и читает cookie-базу каждого
  найденного браузера. За этот прогон `yt_dlp.cookies.extract_cookies_from_browser`
  вызван **2** раза, `_extract_firefox_cookies` — 2 раза (проверено 3 профиля
  Firefox, `cookies.py:203 _firefox_browser_dirs` n=3), база копируется
  дважды (`cookies.py:1112 _open_database_copy` n=2) и материализуется
  **636 объектов `Cookie`** (`http/cookiejar.py:762 __init__` n=636,
  `set_cookie` n=636) — отсюда `deepvalues` с 6250 вызовами. Это часть тех
  120.66 мс `_get_ydl` (см. раздел 3).
* **`yt_dlp/YoutubeDL.__init__` — 12.92 мс, из них 10.03 мс — запрос WMI.**
  `windows_enable_vt_mode` → `get_windows_version` → `platform.win32_ver()` →
  `_wmi_query` → `_wmi.exec_query`: 4.418 мс self плюс ~5.6 мс обвязки вызова
  (10.015 − 4.418). То есть создание `YoutubeDL` на Windows всегда ходит в WMI.
* **`DatabaseManager()` — 15.65 мс медиана**, из них ~9.2 мс это
  `_get_connection` × 8 (по соединению на поток) и 48 вызова
  `sqlite3.Cursor.execute` в `_init_database` (схема + PRAGMA + FTS5).
* **`socket.gethostbyaddr` — 3.09 мс self.** Приходит из
  `LocalProxyManager.start()` → `ThreadingHTTPServer` → `HTTPServer.server_bind`
  → `socket.getfqdn('127.0.0.1')`, то есть это **обратный DNS-резолв
  loopback-адреса** во время старта. В отдельном захвате того же места
  `getfqdn` стоил 10.28 мс — величина зависит от состояния DNS-резолвера.
  Важно: `main.py:160-230` патчит `socket.getaddrinfo` (DoH-фолбэк), но
  `gethostbyaddr` этот патч **не** покрывает.

---

## 3. Пошаговая разбивка `AppCore()`

Метод: `pyprof_child.mode_appcore_breakdown` подменяет `__init__` нужных
классов и стартующие методы на обёртки с `perf_counter` **только в дочернем
процессе** (файлы проекта не меняются), затем `core.app` переимпортирует эти
имена в своё пространство имён, чтобы обёртки реально сработали. 7 прогонов,
каждый в отдельном процессе со свежим профилем.

Сумма шагов главного потока — 48.23 мс при общем 49.09 мс; не атрибутировано
0.86 мс (создание потоков, `threading.Lock`, `Event`).

| Шаг | Медиана, мс | min..max, мс | Поток | file:line |
|---|---:|---:|---|---|
| `YouTubeService._get_ydl()` **[задача executor'а, после возврата конструктора]** | **120.655** | 93.27..139.16 | `ThreadPoolExecutor-1_0` | `services/youtube_service.py:145` (submit) → `:171` |
| `YouTubeService()` | **21.710** | 15.53..24.45 | MainThread | `core/app.py:120` |
| `DatabaseManager()` | **15.645** | 12.68..19.80 | MainThread | `core/app.py:106` |
| `LocalProxyManager.start()` | **6.467** | 4.06..12.64 | MainThread | `core/app.py:147` → `core/proxy.py:1172` |
| `update_ytdlp_safely()` [тело потока] | 1.424 | 0.70..2.02 | `Thread-5` | `core/app.py:140`, `core/app.py:46` |
| `DownloadManager()` | 0.810 | 0.50..1.21 | MainThread | `core/app.py:129` |
| `CacheManager()` | 0.720 | 0.56..0.94 | MainThread | `core/app.py:109` |
| `ZapretService()` | 0.510 | 0.35..0.87 | MainThread | `core/app.py:131` |
| `ZapretService.auto_update_in_background()` | 0.467 | 0.22..1.38 | MainThread | `core/app.py:144` → `services/zapret_service.py:824` |
| `WatchdogService.start()` | 0.339 | 0.24..0.56 | MainThread | `core/app.py:152` → `services/watchdog_service.py:89` |
| `DiscordRPCService.start()` | 0.311 | 0.21..0.54 | MainThread | `core/app.py:137` → `core/services/discord_rpc.py:51` |
| `WatchdogService()` | 0.309 | 0.25..0.37 | MainThread | `core/app.py:133` |
| `PluginManager()` | 0.279 | 0.18..0.42 | MainThread | `core/app.py:130` |
| `LufsScannerService.start()` | 0.235 | 0.16..1.48 | MainThread | `core/app.py:158` → `services/lufs_scanner.py:44` |
| `FileScanner()` | 0.160 | 0.11..0.19 | MainThread | `core/app.py:110` |
| `SettingsManager()` | 0.157 | 0.12..0.23 | MainThread | `core/app.py:107` |
| `SpotifyService()` | 0.033 | 0.03..0.05 | MainThread | `core/app.py:122` |
| `LufsScannerService()` | 0.027 | 0.02..0.03 | MainThread | `core/app.py:134` |
| `AudioEngine()` | 0.013 | 0.009..0.017 | MainThread | `core/app.py:116` |
| `PluginManager.load_plugins()` | 0.011 | 0.006..0.016 | MainThread | `core/app.py:148` → `core/plugins.py:46` |
| `ArtistService()` | 0.009 | 0.006..0.016 | MainThread | `core/app.py:124` |
| `DiscordRPCService()` / `StreamResolver()` / `LyricsService()` / `LocalProxyManager()` / `PlaylistImportService()` / `SessionManager()` / `VKService()` / `AudioFingerprintService()` | ≤ 0.005 каждое | — | MainThread | `core/app.py:113-136` |

Пять пунктов из задания отдельно:

* `DatabaseManager()` — **15.645 мс** медиана (n=7).
* `SettingsManager()` — **0.157 мс**; при этом поток записи настроек
  **не создаётся**: `_wake_writer` вызывается только из `SettingsManager.set()`
  (`core/settings.py:384`), а `__init__` `set()` не вызывает. Подтверждено
  измерением: за 75.51 с idle не было ни одного вызова `Event.wait` на
  `core/settings.py:456`.
* `CacheManager()` — **0.720 мс**: три `os.makedirs` + создание пула на 2 потока
  (`utils/cache_manager.py:28-31`).
* `YouTubeService()` — **21.710 мс** на главном потоке, плюс **120.655 мс**
  задачи `_get_ydl`, ушедшей в собственный `ThreadPoolExecutor(max_workers=10)`
  (`services/youtube_service.py:117`, submit на `:145`). Это самая дорогая
  единица работы при старте, и она **не** входит в 46-49 мс конструктора.
* `LocalProxyManager().start()` — **6.467 мс** (медиана), диапазон 4.06..12.64:
  `secrets.token_urlsafe` + `ThreadingHTTPServer` (bind + обратный DNS) + поток.
* `PluginManager().load_plugins()` — **0.011 мс**: при `general.plugins_enabled`
  = false (по умолчанию) возвращается сразу (`core/plugins.py:48`).
* `WatchdogService().start()` — **0.339 мс**; `LufsScannerService().start()` —
  **0.235 мс**; `DiscordRPCService().start()` — **0.311 мс** (только запуск
  потока `_connect`, сам `pypresence` соединяется асинхронно);
  `zapret.auto_update_in_background()` — **0.467 мс** (только запуск потока
  `_bg`, который первые 5 с спит — `services/zapret_service.py:830`).

---

## 4. Idle CPU фоновых потоков

### Как измерялось (и почему именно так)

* Отдельный режим `pyprof_child idle`: конструирует `AppCore`, **не** создаёт
  окно, 15 с «устаканивания», затем окно 60.51 с.
* psutil-сэмплирование идёт в **собственном потоке** `IdleSampler`, а
  `MainThread` всё окно спит. Иначе измерительный инструмент сам оказался бы
  главным потребителем CPU процесса, что и произошло в первой версии методики.
* Оба endpoint-снимка (`psutil.Process.threads()` до и после окна) снимает
  **тот же** поток `IdleSampler`, иначе он успеет завершиться и его собственная
  CPU станет неатрибутируемой.
* **Контроль**: тот же протокол без `AppCore` (`idle_control`). Разность
  «с `AppCore`» минус «контроль» — это и есть idle CPU, принадлежащий
  `AppCore`.
* `psutil.Process.threads()` на Windows отдаёт user/system time **по каждому
  OS-потоку**, а `threading.get_ident()` на Windows и есть этот OS-thread id —
  поэтому питоновские потоки удалось назвать, а неназванные отнести к
  нативным потокам C-расширений.

Результаты (окно 60.51 с; `harness_cpu_s` — стоимость самого измерителя,
вычтена):

| Поток | Idle CPU, с | % одного ядра |
|---|---:|---:|
| `Thread-1 (_process_queue)` — `core/downloader.py:288-312` | **0.125000** | **0.2066 %** |
| `Thread-3 (_process_pending)` — `services/watchdog_service.py:52-71` | 0.046875 | 0.0775 % |
| `MainThread` | 0.031250 | 0.0516 % |
| `Thread-7 (serve_forever)` — `core/proxy.py:1177` | 0.031250 | 0.0516 % |
| `CacheCleanup`, `Thread-8 (_scan_loop)`, `Thread-2` (watchdog emitter), `ThreadPoolExecutor-1_0` + 4 нативных | 0.000000 | 0.0000 % |

Итого по процессу: 0.7656 с за окно; из них 0.53125 с — сам измеритель;
**0.2344 с = 0.3873 % одного ядра** без него. Контроль без `AppCore`:
0.5781 с, из них 0.546875 с — измеритель, **0.0312 с = 0.0516 %** остаётся
(ровно `MainThread` — это хвост измерения, одинаковый в обоих прогонах).

**Приписываемое `AppCore` idle CPU = 0.2344 − 0.0312 = 0.2032 с за 60.51 с =
0.336 % одного ядра.** Из них:

* `Thread-1 (_process_queue)`: 0.125 с — **61 %** всей idle CPU `AppCore`.
  При 74 итерациях это ~1.69 мс CPU на итерацию (с погрешностью ±15.6 мс).
* `Thread-3 (_process_pending)`: 0.046875 с при 75 итерациях — ~0.63 мс на
  итерацию.
* `Thread-7 (serve_forever)`: 0.03125 с — 2 кванта за 60 с. Это поток
  loopback-прокси (`core/proxy.py:1177`, `self.server.serve_forever` без
  аргументов). Статический факт из stdlib: `socketserver.py:218` —
  `serve_forever(self, poll_interval=0.5)`, тело — `selector.select(poll_interval)`
  (`socketserver.py:235`), то есть поток просыпается каждые 0.5 с
  (2 Гц) в ожидании соединений. Сам интервал опроса инструментом **не**
  измерялся (это C-уровневый `select`, подмена `time.sleep` его не видит);
  измерена только CPU-стоимость.

### Частота пробуждений — измерено подменой `time.sleep` / `Event.wait`

Все модули проекта делают `import time` и затем `time.sleep(...)`, то есть атрибут
резолвится на **общем объекте модуля `time`** в момент вызова. Поэтому
переустановка `time.sleep` / `threading.Event.wait` / `threading.Timer` в
дочернем процессе считает настоящие вызовы, не меняя ни одного исходника.
Для `Event.wait` дополнительно снимается «кто просил ждать» (один кадр выше),
чтобы отличить ожидание приложения от `Thread.join` измерителя.

Журнал наблюдался 75.51 с (15 с устаканивания + 60.51 с окна):

| Место | Что это | Заявленный интервал | Пробуждений | Заблокировано, с | **Измеренная частота** |
|---|---|---:|---:|---:|---:|
| `services/watchdog_service.py:54` | `_process_pending`: `while self._running: time.sleep(1)` | 1 с | **75** | 74.05 | **0.9932 Гц** |
| `core/downloader.py:312` | `_process_queue`: `self._queue_event.wait(timeout=1.0)` на пустой очереди | 1 с | **74** (все 74 — чистые таймауты) | 74.54 | **0.9800 Гц** |
| `services/lufs_scanner.py:70` | `_scan_loop`: `time.sleep(60)` когда нет строк к анализу | 60 с | 2 | 60.00 | **0.0265 Гц** (второй сон не успел завершиться) |
| `core/app.py:166` | `_cache_cleanup_loop`: `while not stop.wait(600)` | 600 с | **0** | — | 0 (ожидаемо) |
| `core/settings.py:456` | `_writer_loop`: `self._writer_wake.wait()` без таймаута | событийный | **0** | — | поток вообще не создан |
| `core/api.py:1788` | `threading.Timer(_timeout, _on_timeout)` на каждый поиск | 4.0 / 8.0 с | **0 таймеров создано** | — | не создаётся без поиска |
| `main.py:455` | `window.events.loaded.wait(35)` | 35 с | — | — | вне измеренного пути (только `main()`) |

### Ответ про py-spy (честно)

py-spy 0.4.2 установлен и **работает**: `py-spy record --pid <pid> --duration 60
--rate 100 --format speedscope --nonblocking --threads` завершился с кодом 0
за 59.85 с, `--format raw` — тоже код 0. Артефакты:
`tools/bench/results/pyspy_idle.speedscope.json` (864 байта) и
`tools/bench/results/pyspy_idle.svg` (308 байт).

**Но для idle-атрибуции он непригоден, и это измерено, а не заявлено.** За 60 с
при 100 Гц (то есть ожидалось ~6000 сэмплов на поток, ~84000 на процесс)
speedscope-выгрузка содержит **6 сэмплов** суммарно (`endValue` 0.04 с и 0.02 с),
а raw-выгрузка — 21 сэмпл, из которых **16 вообще без стека**:

```
thread (13280) 16                                                  <- без стека
thread (13280);<module>;main;mode_idle_hold                        3
thread (19652);_bootstrap;_bootstrap_inner;run;_process_pending (services\watchdog_service.py:54)  2
```

Покрытие — доли процента от ожидаемого.

Причина: idle-потоки заблокированы в `time.sleep` / `WaitForSingleObject`, GIL
свободен, на вершине стека нет Python-кадра — сэмплеру нечего разворачивать.
Поэтому **per-thread idle CPU в этом отчёте получен через
`psutil.Process.threads()`, а не через py-spy**; py-spy использован только как
независимая проверка.

### Что будит процесс чаще, чем нужно

Это **вывод**, а не отдельное измерение, и он опирается на две измеренные
величины выше: частоту (0.99 и 0.98 Гц, то есть 149 пробуждений суммарно за
75.51 с наблюдения) и стоимость итерации (1.69 мс и 0.63 мс CPU).

1. **`core/downloader.py:312`** — `Event.wait(timeout=1.0)` на пустой очереди
   загрузок: 0.98 Гц и **0.125 с CPU за 60 с**, самый дорогой idle-поток
   процесса. Очередь пуста — сигнализировать нечего, таймаут существует только
   чтобы `stop()` был замечен вовремя.
2. **`services/watchdog_service.py:54`** — `time.sleep(1)` в
   `_process_pending`: 0.99 Гц и 0.047 с CPU за 60 с, причём цикл существует
   ради одного условия `now - timestamp >= 3.0` над пустым словарём, когда
   ни одного файла не ждут.
3. `core/app.py:166` (600 с), `services/lufs_scanner.py:70` (60 с) и
   `core/settings.py:456` (событийный, поток ленивый) просыпаются ровно так
   часто, как и задумано — замечаний нет.

---

## 5. Все места с `time.sleep` в циклах опроса

Полный инвентарь — AST-скан всех `*.py` вне `tests/`, `ui/`, `docs/`,
`tools/`, `.venv_win`: **47 мест**, из них **3** были живы в idle-окне. Полный
список с интервалами и измеренными частотами — в
`profile_python_startup.json` → `measurement.sleep_and_wait_sites.sites`
(генерируется `tools/bench/sleepscan.py`, только чтение исходников).

### 5.1 Настоящие циклы опроса (`while` + `sleep`/`wait`)

| file:line | Интервал | Функция | Тип | Измеренная частота |
|---|---:|---|---|---|
| `services/watchdog_service.py:54` | `1` с | `AudioFileHandler._process_pending` | 1 Гц | **0.9932 Гц** |
| `core/downloader.py:312` | `timeout=1.0` с | `DownloadManager._process_queue` | 1 Гц | **0.98 Гц** |
| `core/app.py:166` | `600` с | `AppCore.__init__._cache_cleanup_loop` | 1/600 Гц | **0** |
| `services/lufs_scanner.py:70` | `60` с | `LufsScannerService._scan_loop` | 1/60 Гц | **0.0265 Гц** |
| `services/lufs_scanner.py:96` | `10` с | `_scan_loop` (путь исключения) | 1/10 Гц | не выполнялась |
| `core/settings.py:460` | `FLUSH_INTERVAL_SECONDS` = **0.5** с (`core/settings.py:267`) | `SettingsManager._writer_loop` | 2 Гц | поток не создан |
| `services/zapret_service.py:518` | `0.15` с | `_kill_pid` (`deadline = time.time() + 1.5`, т.е. ≤10 итераций) | 6.7 Гц, ограниченный | не выполнялась |
| `services/zapret_service.py:539` | `0.2` с | `_kill_pid` | 5 Гц, ограниченный | не выполнялась |
| `services/zapret_service.py:549` | `0.15` с | `_kill_pid` | 6.7 Гц, ограниченный | не выполнялась |
| `services/zapret_service.py:1039` | `0.3` с | `_launch_elevated` (`deadline = time.time() + 5.0`, ≤17 итераций) | 3.3 Гц, ограниченный | не выполнялась |
| `services/lastfm_service.py:178` | `min(wait_for, 2.0)` | `_acquire_token` (ограничение частоты запросов Last.fm) | событийный | не выполнялась |
| `services/lyrics_service.py:336` | `not_done` | `get_lyrics` (`concurrent.futures.wait`) | событийный | не выполнялась |

### 5.2 Одноразовые `sleep` (цикла нет)

`core/api.py:425` (`0.2`, только GUI-путь `set_window`) · `core/api.py:548`
(`delay`) · `core/proxy.py:1032` и `:1050` (`1.5**attempt + jitter`, backoff при
ошибке апстрима) · `core/proxy.py:1117` (`0.05`, повтор после
`PermissionError`) · `services/youtube_service.py:800` (`1`, retry извлечения) ·
`services/lufs_scanner.py:57` (`10`, «дать приложению устояться») ·
`services/zapret_service.py:524`, `:551`, `:795` (`1.0`), `:830` (`5.0`),
`:945` (`0.6`) — все в путях, которые на старте срабатывают не более одного раза.

### 5.3 Ожидания по событию (не опрос)

`core/app.py:166` и `core/settings.py:456` — без таймаута либо с длинным;
`audio/engine.py` (`:204`, `:301`, `:318`, `:345`, `:363`, `:402`, `:436`,
`:471`, `:495`) — разовые ожидания с бюджетом 2.5–15 с внутри
`_resolve_via_network`; `core/api.py:1842/1859/1875/2187/2869`,
`core/proxy.py:989`, `core/resolver.py:160`,
`services/track_resolver.py:260/300/391`, `services/youtube_service.py:441`,
`services/zapret_service.py:1068` — разовые ожидания с таймаутом;
`main.py:455` — `window.events.loaded.wait(35)`, только в GUI-пути.

---

## TOP-10 подтверждённых горячих точек

Ранжировать по одной шкале нельзя: стартовые затраты — **однократные миллисекунды**,
а idle — **непрерывный CPU**. Поэтому два списка; внутри каждого ранг задаёт
измеренная величина, а не оценочный вклад. Каждая строка — только то, что
подтверждено измерением; интерпретации вынесены в раздел «Выводы».

### TOP-10A — однократная стоимость старта (мс, медиана, n=7)

| # | Горячая точка | Измеренная величина, мс | Группа / пересечение | file:line |
|---:|---|---:|---|---|
| 1 | Задача `YoutubeDL` в executor'е: сборка cookie-баз браузеров (636 объектов `Cookie` из профилей Firefox) + запрос WMI за версией Windows | **120.66** | конструкция (асинхронно, вне 46 мс) | `services/youtube_service.py:145` (submit) → `:171`; внутри `:37`, `yt_dlp/cookies.py:127`, `yt_dlp/utils/_utils.py:4822` |
| 2 | `import yt_dlp` верхнего уровня в VK-сервисе — 70 модулей, из них `yt_dlp.downloader.external` 65.83 и `yt_dlp.cookies` 26.25 | **103.05** | импорт (внутри `core.app` 258.18) | `services/vk_service.py:10` ← `core/app.py:26` |
| 3 | `import requests` + `urllib3` (36.10) + `charset_normalizer` (11.83) + `certifi` + `idna` | **77.37** | импорт (внутри `core.app`) | `services/spotify_service.py:6` ← `core/app.py:24` |
| 4 | `import webview` → `webview/http.py:26,31,21` (`wsgiref.simple_server`/`http.server`, `bottle` 12.91, `ssl` 7.43) | **67.18** | импорт (прямой ребёнок `main`) | `main.py:19` |
| 5 | `import logging` на CPython 3.14 тянет `traceback` → `_colorize` → `dataclasses` → `inspect` + `re` 15.16 | **49.59** | импорт (прямой ребёнок `main`) | `main.py:7` |
| 6 | `from ytmusicapi import YTMusic` — 52 модуля, self 24.06 почти весь в коде пакета | **25.98** | импорт (внутри `core.app`) | `services/youtube_service.py:24` ← `core/app.py:28` |
| 7 | `YouTubeService()` на главном потоке: `TimeoutSession` + `HTTPAdapter` + `YTMusic(...)` | **21.71** | конструкция | `core/app.py:120` |
| 8 | `locale.setlocale(LC_ALL, "ru")` — самая дорогая отдельная функция по self | **20.33** | конструкция, подпункт №7 (входит в него) | `services/youtube_service.py:135` → `ytmusicapi/ytmusic.py:142` |
| 9 | `DatabaseManager()`: 48 `sqlite3.Cursor.execute`, 8 соединений, `_get_connection` self 8.37 | **15.65** | конструкция | `core/database.py:79` → `:135` → `:107` |
| 10 | `LocalProxyManager.start()`: bind + **обратный DNS-резолв loopback** (`gethostbyaddr` self 3.09) + поток | **6.47** | конструкция | `core/app.py:147` → `core/proxy.py:1172,1175` → `http/server.py:146` → `socket.py:803` |

Сумма позиций 1 + 7 + 8 + 9 + 10 = 185.7 мс; из них конструктор (позиции 1, 7, 8,
9, 10) даёт 164.1 мс, из которых 120.66 мс — асинхронная задача. Позиции 2–6
входят в 258.18 мс `core.app`, позиция 4 и 5 — в 388.70 мс `root_cum`, поэтому
**между группами строки не складываются**.

Пограничные кандидаты, зафиксированные, но не вошедшие в десятку по величине:
`services/lyrics_service.py` (10.07 мс self при импорте), `_wmi.exec_query`
(10.01 мс, подмножество №1), `socket` через `multiprocessing.reduction`
(7.76 мс инклюзивно), `multiprocessing` (7.76), `watchdog` (5.41),
`pypresence` (3.13).

### TOP-idle — непрерывный CPU за 60.51 с (приписывается `AppCore`)

| # | Поток / источник | CPU за 60.51 с | % одного ядра | Частота | file:line |
|---:|---|---:|---:|---:|---|
| 1 | `Thread-1 (_process_queue)` — опрос пустой очереди загрузок | **0.125 с** | 0.2066 % | 0.98 Гц | `core/downloader.py:288-312` |
| 2 | `Thread-3 (_process_pending)` — выдержка файлов для импорта | 0.046875 с | 0.0775 % | 0.9932 Гц | `services/watchdog_service.py:52-71` |
| 3 | `Thread-7 (serve_forever)` — `selector.select(0.5)` прокси-сервера | 0.03125 с | 0.0516 % | 2 Гц (статика stdlib, не измерено) | `core/proxy.py:1177`; `socketserver.py:218,235` |
| 4 | `CacheCleanup`, `Thread-8 (_scan_loop)`, `Thread-2` (watchdog emitter), `ThreadPoolExecutor-1_0`, 4 нативных | 0.000000 с | 0.0000 % | 0 / 1/60 Гц / событийный | `core/app.py:174`, `services/lufs_scanner.py:56-70`, `watchdog/observers/api.py:156-158` |

---

## Выводы (ИНФЕРЕНЦИЯ — явно отделённые от измерений)

Всё выше — измерено. Ниже — интерпретация; ни одно число здесь не новое.

1. **Основной стартовый бюджет — импорты, а не конструктор.** 404 мс CPU в телах
   модулей против 46 мс на `AppCore()`. При этом ~258 мс из 404 мс приходятся на
   `core.app`, и почти всё — три сторонних пакета, которые тянутся из
   верхнеуровневых `import` внутри сервисов. Если `core/app.py` импортировал
   `VKService`/`SpotifyService`/`YouTubeService` лениво (как уже сделано для
   `soundcloud`/`yandex`/`recommendations`), старт сокращается на порядок
   величины — но это изменение поведения, а не измеренный факт.
2. **Реальная «стоимость запуска YouTube» больше, чем показывает конструктор.**
   120.66 мс уходит в executor и в сумму 46 мс не входит, но выполняется сразу
   после старта, конкурируя за GIL с созданием окна. Сбор cookie-баз браузеров и
   WMI-запрос — самая дорогая часть, и обе зависят от машины пользователя
   (число браузеров, установленных профилей).
3. **`locale.setlocale(LC_ALL, "ru")` — побочный эффект, а не только задержка.**
   Библиотека меняет глобальную локаль процесса; это влияет на форматирование
   чисел и дат во всём приложении. Здесь стоило 20.33 мс.
4. **Два 1-Гц цикла — 85 % idle CPU `AppCore`** (0.125 + 0.047 = 0.172 с из
   0.203 с) при пустой очереди загрузок и пустом словаре ожидаемых файлов.
   Абсолютная цифра невелика (0.336 % ядра), но она полностью искусственная:
   обе структуры пусты по определению в простое.
5. **`gethostbyaddr` в `server_bind` — единственное сетевое обращение на
   старте**, и оно не покрыто DoH-фолбэком из `main.py:160-230`, который
   чинит только `getaddrinfo`. При сломанном резолвере это окно нестабильности.

---

## Не удалось измерить

Перечислено честно; ничего из этого не выдаётся за число.

1. **Per-thread idle CPU через py-spy — не удалось.** py-spy работает (код 0),
   но за 60 с @100 Гц собрал 6 сэмплов: idle-потоки заблокированы без
   Python-кадра. Заменено учётом `psutil.Process.threads()`; ограничение —
   квант 15.625 мс, поэтому все idle-числа кратны одному кванту.
2. **Стоимость, которую py-spy не показал бы в любом случае** — вне этого
   профиля: `webview.start()` (создание окна WebView2, загрузка GUI-бэкенда
   `pythonnet`/`clr`), `AppApi(app_core)` (`main.py:244`), `restore_session()`
   (`main.py:249`), отрисовка первой страницы. Ни один из этих путей не
   выполнялся: GUI не запускался.
3. **`import numpy` / `pyloudnorm` / `miniaudio`** внутри
   `services/lufs_scanner.py:19-21` — не измерены: первый вызов
   `analyze_lufs` не происходит в idle-окне (нет локальных треков без `lufs`).
4. **Стоимость pythonnet/`clr`** — в дереве `import main` их нет, и на этом
   пути они не появляются; где именно грузится GUI-бэкенд pywebview, здесь не
   измерено.
5. **Остаток 104.17 мс** (`wall − пол − root_cum`) не разложен на
   составляющие: кандидаты — накладные расходы `-X importtime` на 588 строках
   stderr и финализация интерпретатора (сборка 588 модулей, join потоков).
   Раздельно не измерено.
5. **Стоимость базы данных на «тёплом» профиле** не измерена: каждый прогон
   получает свежий scratch-профиль, поэтому `DatabaseManager()` всегда
   создаёт схему с нуля. На существующей базе `_init_database` будет дешевле —
   величину этой разницы здесь не измеряли.
6. **Поведение под нагрузкой** (воспроизведение, поиск, загрузка) намеренно не
   профилировалось: задача — старт и idle.

---

## Воспроизведение и артефакты

```
tools/bench/run_pyprof.py                    оркестратор (все измерения)
tools/bench/pyprof_child.py                  дочерний измеритель (режимы appcore_*/idle*)
tools/bench/sleepscan.py                     AST-инвентарь sleep/wait (только чтение)
tools/bench/thread_lineage.py                кто создаёт каждый поток AppCore
tools/bench/read_pyprof.py                   чтение JSON по секциям
tools/bench/query_pstats.py                  точечные запросы к .pstats
tools/bench/check_pstats_consistency.py      проверка согласованности cProfile
tools/bench/import_chains.py                 родство в дереве -X importtime
tools/bench/report_numbers.py                печать всех чисел этого отчёта

tools/bench/results/profile_python_startup.json     машинные результаты
tools/bench/results/profile_appcore_init.pstats     cProfile конструктора
tools/bench/results/pyspy_idle.speedscope.json      py-spy (speedscope)
tools/bench/results/pyspy_idle.svg                  py-spy (folded stacks)
tools/bench/results/raw/*.json                      сырые пейлоады каждого прогона
```

Ключи JSON: `measurement.interpreter_and_imports` (импорты),
`measurement.appcore_init`, `measurement.appcore_cprofile`,
`measurement.appcore_breakdown`, `measurement.idle_cpu.{with_appcore,control_no_appcore}`,
`measurement.pyspy` + `pyspy_summary`, `measurement.sleep_and_wait_sites`.

Тесты (`pytest`) не запускались — набор оставался зелёным (566 passed) и
изменений в коде не было.