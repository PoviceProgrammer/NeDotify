# Живая проверка поиска — 1 ноября 2026

Проверки выполнены из `.venv_win/Scripts/python.exe` с реальными `LyricsService`, `YouTubeService`, `CatalogService` и публичными каталогами. Каждый Python-процесс сначала перенаправлял HOME, USERPROFILE, APPDATA и LOCALAPPDATA в отдельный TemporaryDirectory. Настройки передавались как `None`: пользовательские токены, cookies и прокси не читались. Нативное приложение не запускалось. Вывод ограничен метаданными; полные тексты, signed URL и секреты не сохранялись.

## Успешные реальные ответы

| Проверка | Наблюдение |
| --- | --- |
| Genius `/api/search/lyric`, английская строка `hello from the other side` | Получены Adele — Hello, YoungBoy Never Broke Again — Show Me Your Love. В highlights реально присутствуют поля property, value, snippet, ranges; property=lyrics. Первый отдельный запрос занял 1.27 с. |
| Полный `find_lyric_tracks`, тот же английский запрос | За 3.74 с найден YouTube Adele — Hello (Official Music Video), id `YQHsXMglC9A`; также YoungBoy Never Broke Again — Show Me Your Love, id `UVvoNQjC8s4`. Совпали фраза в lyrics highlight, название и исполнитель. |
| Genius и полный `find_lyric_tracks`, русская строка `пожелай мне удачи в бою` | В Genius первый кандидат КИНО (KINO) — Группа крови (Blood Type), второй Джизус (Dzhizus) — Группа крови (Rhesus Factor). Полный путь вернул Джизус — Группа крови, YouTube id `v_QSn99hFU8`, за 5.29 с. Каталожный результат КИНО в этом прогоне не подтверждён, поэтому он не выдан. |
| Публичный Deezer `/search?q=Adele%20Hello&limit=3` | За 4.32 с получен Adele — Hello; отдельно Conkarah — Hello (Reggae Cover) и FJ Outlaw — Hello (Adele Remix). Подмены исполнителя и версии не допускаются. |
| Artist resolver, `Earth, Wind & Fire`, require_candidates=true | В одном реальном прогоне получен ambiguous с iTunes-кандидатом Earth, Wind & Fire, id `290699`. Полное имя с запятой и амперсандом сохранено. |

## Ограничения и повторные проверки

Сеть нестабильна. Другие прогоны тех же публичных запросов дали Genius URLError/TimeoutError, iTunes URLError/SSLEOFError, пустые YouTube Music artist/track ответы. Повторная русская проверка вернула пустой список по исчерпании 8-секундного бюджета. Последние artist проверки после изменения бюджета вернули unavailable: Adele за 4.91 с, Earth, Wind & Fire за 1.88 с. Доступность источников не гарантируется. 403/429 не обходились, аутентификация не добавлялась.

Успешные проверки выше подтверждают реальные endpoint, схему и работу полного lyric пути в этой среде; они не доказывают непрерывную доступность сервисов, воспроизведение звука или работу установленного EXE.

## Исправления по результатам проверки

- Genius добавляет английское пояснение в скобках к русскому названию и имени. Такое пояснение удаляется только после кириллицы; Live/Remix и остальные распознаваемые версии сохраняются. Проверка исполнителя использует существующее строгое сопоставление lyrics, включая транскрипцию между кириллицей и латиницей.
- При недоступном YouTube добавлен публичный Deezer fallback, с проверкой названия и исполнителя. Возвращается обычная каталожная запись Deezer. Поле preview не используется как полный трек.
- Для поиска по строчке требуется именно highlight с property=lyrics и полное нормализованное вхождение запроса. Одного совпадения с заголовком недостаточно.
- Вся lyric ветка ограничена 8 с: один full-text запрос, максимум два YouTube и два резервных Deezer запроса. Отменённые запросы не выдают результаты. Обычный поиск точного названия не запускает full-text.
- Artist discovery раньше мог потратить все 8 с на YouTube и вообще не вызвать iTunes. Теперь оба написания делят максимум 3 с, оставляя время iTunes. UI ждёт 10 с, чтобы получить результат после 8-секундного бюджета backend.

Первичные исходники использованного публичного Genius API:

- [LyricsGenius public search methods](https://github.com/johnwmillr/LyricsGenius/blob/master/lyricsgenius/api/public_methods/search.py): `search_lyrics` использует `/api/search/lyric`.
- [SearxNG Genius engine](https://github.com/searxng/searxng/blob/master/searx/engines/genius.py): обработка highlights/value. Фактическая схема дополнительно проверена живым запросом выше.

Регрессии находятся в `tests/test_search_lyrics_fallback.py`: реентерабельный callback, полное имя группы, artist shape, budget, отмена, исключение обычных title запросов, Cyrillic/Latin artist identity, Deezer fallback без preview, сохранение версий и недопуск title-only highlight. Все проверки используют искусственные данные и не требуют сети.

## Дополнение: Deezer artist identity и профиль

Отдельный живой `DeezerService._get('search/artist', q='Adele', limit=3)` ответил за 2.66 с. Порядок был не точным: Adèle & Robin (69171232), Adele & Andy (76152522), Adele (75798), все type=artist. Поэтому выбор первого результата запрещён: `resolve_artist` выбирает совпадающее имя или показывает варианты. Публичный `artist/75798` в том же процессе подтвердил id=75798, type=artist, name=Adele, nb_fan=15510274.

Добавлен Deezer candidate→selected profile путь. Candidate имеет type=artist/source=deezer/source_id. При выборе backend заново проверяет type и id ответа `artist/{id}`. Top tracks берутся с `artist/{id}/top`, допускаются только записи с тем же artist.id или явным contributor.id. Для треков используется существующая форма DeezerService, preview не используется. Возвращаются имя, подтверждённый catalogue id, фото, число поклонников и треки. Albums пока пуст: новые маршруты альбомов этой доработкой не создавались. Сохранённые привязки поддерживают Deezer; UI обозначает каталог Deezer.

Новый fallback вызывается только при отсутствии результатов YouTube/iTunes. YouTube получает максимум 3 с общего 8-секундного бюджета; iTunes — максимум следующие 2 с; остаток доступен Deezer. Для selected profile предусмотрен самостоятельный 8-секундный бюджет.

Последующие реальные попытки полного нового пути не дали устойчивого успеха: candidate discovery вернул unavailable за 5.09 с; выбор ранее реально найденного id через ArtistService.get_profile вернул unavailable за 6.44 с; отдельный диагностический прогон установил ReadTimeout на artist/75798 за 3.11 с. Следовательно, прямые live endpoints подтверждены, но успешный live candidate→selected ArtistService profile целиком на этом этапе ещё не подтверждён. Регрессии проверяют полный путь с искусственными данными, включая отбрасывание похожего исполнителя, wrong profile id и треков вместо artist entities.

### Повтор после восстановления доступности: полный путь подтверждён

Следующая ограниченная read-only проверка `ArtistService.get_profile` для ранее живого Deezer-кандидата source=deezer/id=75798 завершилась **found за 0.76 с**: name=Adele, verified=true, фото присутствует, fans=15510283, **50 top tracks**. Среди них Set Fire to the Rain (8086130), Rolling in the Deep (8086126), Lovesong (8086135), все source=deezer/artist=Adele. Это реальные новые ответы `artist/75798` и `artist/75798/top`, не replay и не тестовые данные.

Затем в одном новом временном профиле полностью выполнен свободный запрос→выбор→профиль через реальные `ArtistService` и `CatalogService`: discovery `Adele`/require_candidates=true вернул ambiguous за **2.96 с** с iTunes ids 262836961, 563040812, 1268134202, 1653862462; выбран кандидат **Adele/id=262836961**. Его `get_profile` завершился **found за 3.24 с**, имя Adele, фото присутствует, **70 треков**, первый Skyfall — Adele (каталожная форма source=spotify). Когда iTunes ответил успешно, Deezer fallback не запрашивался.

Таким образом, реальный свободный поиск→выбор→получение наполненного профиля подтверждён, и отдельный реальный выбор Deezer-кандидата также даёт наполненный профиль. Прежние timeout выше сохранены как свидетельство нестабильной доступности внешних сервисов, а не текущий итог проверки. Нативное окно и аудиовоспроизведение этим не проверялись.
