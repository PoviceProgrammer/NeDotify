# Performance Backlog

| ID | Категория | Файл/Компонент | Гипотеза | Статус |
|---|---|---|---|---|
| PERF-001 | RAM/CPU | `services/youtube_service.py`, `services/soundcloud_service.py`, `services/spotify_service.py` | Замена eager приватных `ThreadPoolExecutor` на единый ленивый `_SharedExecutor` из `BaseMusicService` снизит количество фоновых потоков с ~25 до 0-4 на старте и сэкономит стек RAM | done |
| PERF-002 | CPU/RAM | `ui/web_new/js/particles.js` | Устранение утечки слушателей `resize`, `mousemove`, `mouseleave`, `mini_player_toggled`: вынос функций из замыкания `initParticles`, корректное удаление в `stopParticles` и отключение таймера мыши при остановке частиц спасет от бесконечных вызовов и утечек памяти | done |
| PERF-003 | CPU/GPU | `ui/web_new/js/visualizer.js` | Устранение layout thrashing (forced reflow) при чтении `offsetParent` каждый кадр в цикле `draw()`, кэширование видимости канваса и дедупликация слушателя `resize` устранят микрофризы и снизят нагрузку на CPU | done |
| PERF-004 | CPU/RAM | `ui/web_new/js/player.js` | Сброс `animFrameId = null` при уходе вкладки в скрытое состояние (фикс залипания прогресс-бара), кэширование текстовых значений времени/aria-valuenow перед записью в DOM на 15 FPS и кэширование canvas элементов в `renderWaveforms` устранит лишние DOM mutations | done |
| PERF-005 | RAM/CPU | `ui/web_new/js/efficiency.js` | Предотвращение накопления экземпляров `MutationObserver` и слушателей событий `nedotify:app_ready` при повторной инициализации | done |
| PERF-006 | RAM/CPU | `core/database.py` | Оптимизация `PRAGMA cache_size`: замена чрезмерного 8MB на соединение (-8000) на 2MB (-2000) уменьшит расход памяти в многопоточных сценариях без потери скорости запросов | done |
| PERF-007 | CPU | `main.py` | Вынос `import json` из горячего метода конвертации значений `_patched_convert_js_value` в модуль/замыкание снизит CPU overhead при IPC вызовах | done |
| PERF-008 | CPU/NETWORK | `core/proxy.py` | Увеличение размера чанка при отдаче локальных аудиофайлов по Range-запросам с 8KB до 64KB сократит системные вызовы read/write и уменьшит накладные расходы ядра | done |
| PERF-009 | CPU/RAM | `ui/web_new/js/contextmenu.js` | Дедупликация слушателя `contextmenu` на `document` для предотвращения дублирования обработчиков при повторной инициализации | done |
| PERF-010 | CPU/GPU | `ui/web_new/js/artist_profile.js` | Пассивный `{ passive: true }` и rAF-дросселированный скролл в бесконечном списке треков профиля артиста устранит микрофризы и layout thrashing | done |
| PERF-011 | CPU/RAM | `ui/web_new/js/equalizer.js` | Дедупликация слушателя `click` на `document` для закрытия меню пресетов эквалайзера | done |
| PERF-012 | RAM/NETWORK | `ui/web_new/js/artist_profile.js` | Очистка слушателей поиска и таймеров при ошибке bridge-запроса профиля артиста для предотвращения утечек памяти промисов | done |
| PERF-013 | CPU/GPU | `ui/web_new/js/library.js` | Пассивный `{ passive: true }` и rAF-дросселированный бесконечный скролл библиотеки с отменой `cancelAnimationFrame` при смене плейлиста | todo |
| PERF-014 | CPU/NETWORK | `core/proxy.py` | LRU-кэширование корней обложек/аватаров `_cover_roots` и увеличение буфера потоковой передачи удаленных аудиостримов до 64KB | todo |
| PERF-015 | CPU/GPU | `ui/web_new/js/player.js`, `ui/web_new_v2/js/settings.js` | rAF-дросселирование и `{ passive: true }` ресайза холста waveforms, проверка `document.hidden` в таймере опроса аудиоустройств | todo |
