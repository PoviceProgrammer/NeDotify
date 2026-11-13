# Локальное аудиоранжирование для «Открытий»

Windows-превью `openl3_cosine_v0` переупорядочивает кандидатов для «Открытий для вас». Профиль задаётся локальным файлом событий. Клиент читает каталог и выполняет расчёт в NumPy. При отсутствии пригодного каталога или профиля используется текущий порядок.

## Аудит покрытия

Из корня Windows-репозитория запустить:

```powershell
& '.venv_win/Scripts/python.exe' tools/bench/audit_embedding_coverage.py `
  --db 'C:/path/to/nedotify_storage.db' --catalog 'C:/path/to/catalog.json'
```

`--fma-metadata` принимает официальный `fma_metadata.zip` вместо готового каталога. Аудит сопоставляет метаданные записей с указанными в FMA лицензиями Attribution и CC0. `--live-candidates` собирает свежих кандидатов через обычный поиск метаданных из изолированной копии базы. `--candidates` принимает готовый JSON-список. Счётчик подтверждённого воспроизведения учитывает только кандидатов, для которых предоставлен `playback_verified: true`. `cyrillic_metadata` означает кириллицу в названии или имени артиста.

На проверенной Windows-библиотеке ни одна из 121 записи и ни один из 30 свежих кандидатов не совпали с 7 974 отобранными записями FMA. Это замер одной библиотеки и одного пула поиска. [Источник метаданных FMA](https://github.com/mdeff/fma#data)

## Каталог и запуск превью

Для подготовки каталога использовать отдельное окружение Python 3.11 с OpenL3 0.4.2, TensorFlow 2.15.1, Kapre 0.3.6, librosa 0.10.2.post1, MoviePy 1.x и `setuptools<81` для совместимости с resampy 0.2.2. Эти пакеты нужны только скрипту сборки каталога. Входной JSON содержит список записей с полями `recording_id`, `title`, `artist`, `audio_file`, `audio_license`, `attribution` и необязательными `mbid`, `isrc`, `language`. Путь `audio_file` разрешается относительно входного JSON. [Документация OpenL3](https://openl3.readthedocs.io/en/latest/tutorial.html) · [Лицензия весов](https://github.com/marl/openl3#model-weights-license)

```powershell
& 'C:/path/to/encoder/Scripts/python.exe' tools/build_embedding_catalog.py `
  'C:/path/to/recordings.json' 'C:/path/to/catalog.json' --version local-v1
```

Рядом с `catalog.json` и `catalog.npy` положить `catalog.events.json` следующего формата. Для ранжирования нужны хотя бы три разные записи с эмбеддингами из каталога и актуальными минутами UTC. `weight` равен 1 для дослушивания и 2 для лайка или добавления. События нумеруются без пропусков, начиная с 1.

```json
{
  "catalog_version": "local-v1",
  "session_id": "preview-session",
  "event_seq_id": 1,
  "events": [
    {"recording_id": "track-a", "timestamp_min": 29913600, "event_seq_id": 1,
     "session_id": "preview-session", "weight": 1}
  ]
}
```

Для локального запуска указать путь в `NEDOTIFY_DISCOVERY_PREVIEW_CATALOG` перед запуском NeDotify. Профиль для ранжирования в этой версии загружается из подготовленного файла событий.

## Добровольный сбор на этом ПК

В новых тестовых профилях локальный сбор включён по умолчанию. Сохранённое отключение продолжает действовать.

Из корня Windows-репозитория запустить приёмник:

```powershell
& '.venv_win/Scripts/python.exe' tools/recommendation_event_server.py `
  --db "$env:LOCALAPPDATA/NeDotify/RecommendationBeta/recommendation_events.db"
```

Приёмник слушает `127.0.0.1:8765`. В окне превью открыть **Настройки → Плеер → Рекомендации** и включить «Отправлять события теста рекомендаций на этот ПК». Затем на главной обновить подборки и открыть или запустить «Открытия для вас». Записываются только записи, которым соответствует ID каталога. Отправляемые поля включают случайный идентификатор установки, ID показа и записи, позицию, версии каталога и ранжирования, время с точностью до минуты и результат действия. Аудио, названия треков, пути и прежняя история остаются на устройстве.

Если приёмник временно недоступен, клиент повторяет отправку из SQLite. Отключение сбора очищает неотправленную очередь и сбрасывает идентификатор установки. Уже принятые строки хранятся в базе приёмника, которая очищает данные старше 90 дней при приёме следующего пакета. В этой версии приёмник сохраняет события показа и реакций. Преобразование этого потока в экспорт для обучения и обновление профиля на его основе ещё предстоит подключить.

Посмотреть счётчики в базе при работающем сервере:

```powershell
& '.venv_win/Scripts/python.exe' tools/recommendation_event_server.py --summary `
  --db "$env:LOCALAPPDATA/NeDotify/RecommendationBeta/recommendation_events.db"
```

## Проверка обучения и экспорта

`tools/prepare_recommendation_pairs.py` формирует NPZ из локального экспорта событий и показов одной установки. Он проверяет полный префикс событий и хэш профиля, связывает только положительные и явно отрицательные исходы одного показа и разделяет данные по `--validation-start` в минутах UTC. Схема показа включает `catalog_version`, `feature_schema_version`, `evaluation_timestamp_min`, `session_id`, `event_seq_id`, `profile_state_hash`, `novelty_mode` и список `outcomes`. Каждый исход содержит `recording_id` и поля результата, которые принимает скрипт: `liked`, `added`, `hidden`, `started`, `playback_error`, `manual_skip`, `listened_fraction`, `listened_seconds`.

`tools/train_recommendation_mlp.py` принимает два хронологически непересекающихся NPZ с подготовленными парами. Первый элемент каждой пары положительный. Формы массивов `audio`, `scalars`, `present` равны `(N, 2, 3, 512)`, `(N, 2, 16)`, `(N, 2, 16)` соответственно. Порядок аудио в каждой записи: долгосрочный профиль, короткий профиль, кандидат. Метаданные массива включают `evaluation_timestamp_min` формы `(N,)`, `feature_schema_version`, `catalog_version` и `scalar_features` в порядке из `services/recommendation_mlp.py`. Выбор между `--architecture compact` и `--architecture target` задаёт бюджет в 203 329 и 1 017 473 параметров соответственно.

Тренировочный скрипт проверяет расхождение PyTorch и NumPy перед экспортом весов. Для локальной проверки MLP положить `catalog.npz` и `catalog.model.json` рядом с каталогом. В JSON записать `weights_sha256`, напечатанный скриптом обучения. Тестовый прогон на синтетических парах использует попарную потерю валидации. Для отбора релизной модели потребуются полные показы с метками и расчёт NDCG@20.
