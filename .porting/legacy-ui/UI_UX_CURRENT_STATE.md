# Текущее состояние UI/UX проекта NeDotify (AURA Music)

Данный документ представляет собой полную и объективную техническую фиксацию текущей реализации пользовательского интерфейса (UI) и пользовательского опыта (UX) приложения NeDotify (AURA Music). Документ описывает структуру, компоненты, дизайн-систему, поведение элементов и логику взаимодействия без субъективных оценок и предложений по улучшению.

---

## 1. Инвентаризация экранов и страниц

Интерфейс приложения построен как Single Page Application (SPA) с фиксированным контейнером `#app-container`, боковым меню `#sidebar`, областью контента `#main-content`, нижним плеер-баром `#player-bar`, мини-плеером `#mini-player-overlay`, оверлеями и модальными окнами.

### 1.1. Главная страница (Home)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 171–312, контейнер `#view-home.view-page.active`)
  * Стили: `ui/web_new/css/styles.css` (секции `#view-home`, `.stats-grid`, `.stat-card`, `.feed-section`, `.feed-title`, `.feed-scroll`, `.feed-card`, `.wrapped-card-dashboard`, строки 680–890, 4800–4950)
  * Логика: `ui/web_new/js/home.js`, `ui/web_new/js/pages.js`
* **Блоки и секции**:
  1. `home-visualizer-canvas` — полупрозрачный фоновый Canvas аудио-визуализатора (высота 300px, opacity: 0.3, z-index: 0).
  2. `home-greeting` — заголовок приветствия («Добро пожаловать в NeDotify»).
  3. `stats-grid` — сетка из 4 карточек статистики пользователя:
     * `stat-tracks` — количество прослушанных треков.
     * `stat-time` — суммарное время прослушивания (мин/ч).
     * `stat-playlists` — количество созданных/импортированных плейлистов.
     * `stat-favorites` — количество треков в «Избранном».
  4. `home-history` — горизонтальная лента недавно прослушанных треков (`.feed-scroll`).
  5. `home-top-tracks` — горизонтальная лента «Топ треков (Local Last.fm)».
  6. `home-top-artists` — горизонтальная лента «Топ исполнителей».
  7. `section-nedotify-wrapped` — блок персональной аналитики прослушиваний (NeDotify Wrapped):
     * Переключатель периода (`#wrapped-period-btns`): «Неделя», «Месяц», «Всё время».
     * Интерактивный график активности (`#wrapped-activity-canvas`, высота 140px) с бейджем общего времени (`#wrapped-total-time-badge`).
     * Список «Топ-5 за период» (`#wrapped-top-list`).
  8. `home-authentic-feed` — динамический контейнер аутентичной ленты рекомендаций YouTube Music.
  9. `section-home-popular` / `#home-popular` — горизонтальная лента «Популярные треки».
  10. `home-recommended-section` / `#home-recommended` — блок «Рекомендации для вас».
  11. `section-home-releases` / `#home-releases` — блок «Новые релизы».
  12. `section-home-mood` / `#home-mood` — блок «Под настроение».
  13. `section-home-mixes` / `#home-mixes` — блок «Миксы».
  14. `home-artists` — блок «Популярные исполнители».
  15. `home-playlists` — блок «Ваши плейлисты».
* **Доступные действия**:
  * Воспроизведение трека кликом по карточке или кнопке Play поверх обложки.
  * Переключение периода в Wrapped (неделя/месяц/все время) с мгновенной перерисовкой Canvas-графика.
  * Переход к профилю артиста по клику на карточку исполнителя.
  * Горизонтальная прокрутка лент колесиком мыши или свайпом.
  * Клик на кнопку «Повторить» (`.retry-btn`) при тайм-ауте сетевого запроса к провайдерам.

---

### 1.2. Страница поиска (Search)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 315–390, контейнер `#view-search.view-page`)
  * Стили: `ui/web_new/css/styles.css` (секции `.search-capsule`, `.search-platform-wrapper`, `.search-type-filters`, `.type-filter-btn`, строки 890–1050, 2580–2750)
  * Логика: `ui/web_new/js/search.js`, `ui/web_new/js/artist_profile.js`
* **Блоки и секции**:
  1. `search-capsule` — строка поиска с иконкой лупы, текстовым полем `#search-input`, кнопкой очистки `#search-clear` и выпадающим меню платформ `#search-platform-btn`.
  2. `search-platform-dropdown` — выпадающий селектор площадки поиска: «Все площадки» (`all`), «YouTube Music» (`youtube`), «SoundCloud» (`soundcloud`), «Spotify» (`spotify`).
  3. `search-type-filters` — панель переключения типов сущностей: «Все» (`all`), «Треки» (`tracks`), «Плейлисты» (`playlists`), «Альбомы» (`albums`), «Артисты» (`artists`).
  4. `search-results` — контейнер выдачи результатов:
     * Пустое состояние (`.empty-state`).
     * Скелетоны загрузки (`.skeleton-card`, `.spinner`).
     * Список треков (`.track-item`) с пакетным рендерингом через rAF.
     * Сетка плейлистов (`.playlist-cards-grid`, `.playlist-card`).
     * Сетка альбомов (`.album-card`).
     * Разметка профиля артиста (`.artist-profile-layout`).
* **Доступные действия**:
  * Ввод поискового запроса с debounce (300 мс) или запуском по нажатию `Enter`.
  * Очистка строки поиска одной кнопкой.
  * Фильтрация источника стриминга и категории контента.
  * Воспроизведение треков напрямую из списка.
  * Открытие модального окна альбома/плейлиста.
  * Переход в профиль артиста с загрузкой дискографии, фото, биографии и топ-треков.
  * Вызов контекстного меню трека (правый клик или кнопка `...`).

---

### 1.3. Страница медиатеки (Library)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 393–488, контейнер `#view-library.view-page`)
  * Стили: `ui/web_new/css/styles.css` (секции `.lib-top-cards`, `.lib-main-layout`, `.lib-left-sidebar`, `.lib-right-content`, строки 1050–1350)
  * Логика: `ui/web_new/js/library.js`
* **Блоки и секции**:
  1. `lib-top-cards` — верхний ряд быстрых категорий:
     * `#lib-card-favorites` — карточка «Любимые» с бейджем счетчика треков (`#lib-fav-count`).
     * `#lib-card-offline` — карточка «Оффлайн треки» с бейджем счетчика скачанных локально (`#lib-offline-count`).
  2. `lib-left-sidebar` — левая колонка управления плейлистами:
     * Кнопка быстрого создания `#lib-btn-add-playlist`.
     * Поле ввода названия плейлиста `#lib-quick-pl-input`.
     * Кнопка импорта локальных аудиофайлов `#lib-btn-import`.
     * Кнопка импорта/конвертации внешних плейлистов `#lib-btn-convert`.
     * Список созданных пользователем плейлистов `#lib-sidebar-playlists`.
  3. `lib-right-content` — правая основная область:
     * `#lib-empty-selection` — заглушка «Вы ничего еще не выбрали».
     * `#lib-active-view` — активный список треков выбранного раздела.
     * Заголовок раздела `#lib-active-title` и счетчик `#lib-active-sub`.
     * Блок прогресса пакетного скачивания `#lib-batch-progress-box` (прогресс-бар, счетчик `0 / N`, кнопка отмены `#lib-btn-batch-cancel`).
     * Кнопка «Скачать всё» (`#lib-btn-download-all`).
     * Кнопка «Воспроизвести все» (`#lib-btn-play-all`).
     * Список треков `#lib-active-tracks` (`.track-list`) с поддержкой Drag-and-Drop.
* **Доступные действия**:
  * Переключение между «Любимыми», «Оффлайн» и пользовательскими плейлистами.
  * Создание нового плейлиста (по нажатию `+` или `Enter` в инпуте).
  * Пакетное скачивание всех избранных треков для оффлайн-доступа.
  * Отмена текущего процесса пакетного скачивания.
  * Перетаскивание треков внутри плейлиста (Drag-and-Drop) для изменения порядка воспроизведения.
  * Удаление треков из плейлистов, редактирование тегов трека, вызов контекстного меню.
  * Экспорт плейлиста в M3U8.

---

### 1.4. Страница деталей плейлиста (Playlist Details View)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 491–514, контейнер `#view-playlist-details.view-page`)
  * Стили: `ui/web_new/css/styles.css` (строки 1350–1430)
  * Логика: `ui/web_new/js/library.js`, `ui/web_new/js/search.js`
* **Блоки и секции**:
  1. Кнопка возврата в библиотеку `#btn-back-library`.
  2. Крупная обложка плейлиста (160x160px).
  3. Метаданные: надпись «Плейлист», название `#pl-details-title`, счетчик треков `#pl-details-count`.
  4. Кнопки управления: «Воспроизвести» `#pl-btn-play`, «Экспорт» `#pl-btn-export`.
  5. Список треков плейлиста `#pl-details-tracks`.
* **Доступные действия**:
  * Запуск воспроизведения плейлиста целиком с 1-го трека.
  * Экспорт структуры плейлиста в локальный `.m3u8` файл.
  * Возврат к предыдущему экрану.

---

### 1.5. Полноэкранная страница плеера (Player View)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 516–592, контейнер `#view-player.view-page`)
  * Стили: `ui/web_new/css/styles.css` (секции `.player-2col-layout`, `.player-glass-card`, `.player-cover-section`, `.player-lyrics-container`, строки 1430–1700, 4050–4200)
  * Логика: `ui/web_new/js/player.js`, `ui/web_new/js/visualizer.js`, `ui/web_new/js/lyrics.js`
* **Блоки и секции**:
  1. `#player-bg-glow` — динамическое фоновое неоновое свечение в цвет обложки активного трека.
  2. Левая колонка (Glass-карточка управления):
     * Заголовок `#pp-header-title` (Название `#pp-title` — Исполнитель `#pp-artist`).
     * Контейнер обложки `#pp-cover-wrapper` с изображением `#pp-cover` (квадратная или виниловая пластинка при `.player-style-vinyl`).
     * Canvas визуализатора поверх/под обложкой `#visualizer-canvas`.
     * Прогресс-бар `#pp-progress-track` с текущим временем `#pp-time-current`, общим временем `#pp-time-total`, заполнением `#pp-progress-fill` и Canvas формы волны `#pp-waveform-canvas`.
     * Панель управления воспроизведением:
       * Лайк `#pp-btn-like`.
       * Перемешивание `#pp-btn-shuffle`.
       * Повтор (выкл / трек / список) `#pp-btn-repeat`.
       * Бесконечная волна (Flow) `#pp-btn-flow`.
       * Предыдущий трек `#pp-btn-prev`.
       * Кнопка Play/Pause `#pp-btn-play` (48x48px).
       * Следующий трек `#pp-btn-next`.
       * Кнопка перехода к тексту `#pp-btn-lyrics`.
       * Кнопка открытия очереди `#pp-btn-queue`.
  3. Правая колонка (Glass-карточка синхронизированного текста):
     * Заголовок с кнопкой включения перевода `#btn-toggle-lyrics-translation-page` и кнопками сдвига таймингов `-0.5s` (`#btn-lyrics-offset-minus-page`) / `+0.5s` (`#btn-lyrics-offset-plus-page`).
     * Скролл-контейнер `#player-lyrics-scroll` со списком строк песни `#lyrics-content`.
* **Доступные действия**:
  * Все стандартные функции управления воспроизведением, перемоткой (клик/drag по таймлайну).
  * Интерактивный клик по строке текста песни для мгновенного перехода аудио к этой секунде.
  * Точная подстройка смещения текста песни (сохраняется для трека).
  * Включение/выключение перевода текста на русский язык.

---

### 1.6. Страница профиля пользователя (Profile View)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 626–683, контейнер `#view-profile.view-page`)
  * Стили: `ui/web_new/css/styles.css` (строки 1700–1850)
  * Логика: `ui/web_new/js/main.js`, `ui/web_new/js/pages.js`
* **Блоки и секции**:
  1. Шапка профиля:
     * Аватарка `#btn-change-avatar` (с картинкой `#profile-avatar-img` или иконкой `#profile-avatar-icon`).
     * Редактируемое поле имени пользователя `#profile-name-input` и кнопка сохранения `#btn-save-nickname`.
     * Подзаголовок `#profile-date-joined`.
  2. Кнопка создания локального плейлиста из файлов на диске `#btn-create-local-playlist`.
  3. Статистика (`.stats-grid`):
     * `profile-stat-tracks` (прослушано треков).
     * `profile-stat-time` (общее время в часах).
     * `profile-stat-favorites` (избранных треков).
  4. Секция закрепленного трека `#profile-pinned-section` / `#profile-pinned-track`.
  5. Секция «Топ треков» `#profile-top-tracks`.
  6. Секция «Недавно прослушано» `#profile-recent`.
* **Доступные действия**:
  * Загрузка и смена локального аватара.
  * Изменение никнейма.
  * Выбор и прикрепление трека к профилю.
  * Создание плейлиста из выбранной локальной папки.

---

### 1.7. Модальное оверлей-окно настроек (Settings Overlay)
* **Файлы разметки и стилей**:
  * Разметка: `ui/web_new/index.html` (строки 685–1872, контейнер `#view-settings.view-page.settings-overlay`)
  * Стили: `ui/web_new/css/styles.css` (секции `.settings-overlay`, `.settings-modal-card`, `.settings-nav`, `.settings-panels`, строки 3000–3900)
  * Логика: `ui/web_new/js/settings.js`, `ui/web_new/js/equalizer.js`, `ui/web_new/js/hotkeys.js`
* **Блоки и секции** (13 вкладок в левом меню):
  1. **Оформление (`#settings-appearance`)**:
     * Режимы темы: Dark, Light, System (`.theme-mode-btn`).
     * Сетка из 22 цветовых пресетов (`#theme-presets-grid`).
     * Конструктор кастомной темы: палитра 8 цветов (Основной, Акцент, Фон, Текст, Карточки, Границы, Димминг, Фокус), генератор случайной палитры `#btn-random-theme`, сохранение темы.
     * Каталог шрифтов: категории (Системные, Modern, Serif, Mono, Hand, Deco, Game), сетка шрифтовых карточек `#font-cards-grid`, экспорт конфига шрифта.
     * Ползунок базового размера шрифта `#slider-font-size` (12–24px).
     * Прозрачность окна: тумблер `#toggle-transparency` и слайдер `#slider-transparency-level` (20–100%).
     * Размытие стекла: слайдер `#slider-glass-blur` (0–40px).
     * Discord Rich Presence: тумблер `#toggle-discord-rpc`.
  2. **Плеер (`#settings-player`)**:
     * Выравнивание заголовка (`#opt-title-align`): слева, по центру, справа.
     * Стиль обложки (`#opt-player-style`): обычный, виниловый диск.
     * Стиль полосы прогресса (`#opt-slider-type`): Default, Thin, iOS Glass, Waveform.
     * Aura Orbs: тумблер включения фоновых парящих сфер Vision Pro.
     * Настройки очереди: тумблер показа `#toggle-show-queue`, позиция (`#opt-queue-pos`: снизу, слева, справа), компактная кнопка, вид очереди (обычный / расширенный).
     * Автопилот / Flow: тумблер `#toggle-queue-autopilot`.
     * Предзагрузка следующего трека: тумблер `#toggle-player-prefetch`.
     * Настройки мини-плеера: форма прогресса (линия, фон, вокруг обложки), форма обложки (квадрат, круг), форма окна (прямоугольник, капсула), позиционирование окна на экране (9 позиций).
  3. **Фон (`#settings-background`)**:
     * Загрузка фонового изображения пользователя `#btn-upload-bg-image`.
     * Ползунок размытия фона `#slider-bg-blur` (0–50px).
     * Ползунок затемнения фона `#slider-bg-dim` (0–100%).
     * Кнопка удаления пользовательского фона `#btn-remove-bg-image`.
  4. **Мастерская (`#settings-workshop`)**:
     * Поиск по встроенной галерее обоев `#workshop-search-input`.
     * Сортировка (Новые, Популярные, Скачивания).
     * Теги фильтрации (Все, Anime, Cyberpunk, Nature, Abstract, Minimal).
     * Сетка карточек обоев `#workshop-cards-grid` с кнопкой «Применить» и счетчиками лайков.
  5. **Иконки (`#settings-icons`)**:
     * 10 стилизованных паков иконок (`#icon-packs-grid`): AURA Neon, Cyber Disc, Flame Beats, Cosmic Sound, Deep Subwoofer, Studio Vintage, Wave Radio, Electric Heart, Infinity Stream, Crown Gold.
  6. **Частицы (`#settings-particles`)**:
     * Тумблер включения частиц `#toggle-particles`.
     * Выбор формы частиц: Точки, Сердечки, Звезды, Снежинки, Ноты, Блеск, Флаг РФ, Герб РФ.
     * Ползунки: Количество (10–80), Размер (1–5), Скорость (1–3).
  7. **Аудио (`#settings-audio`)**:
     * Селектор аудиоустройства вывода `#select-audio-device`.
     * Тумблеры: Плавный переход Crossfade (`#toggle-crossfade`) и слайдер длительности (1–12 сек), Gapless playback (`#toggle-gapless`), Нормализация громкости ReplayGain / LUFS (`#toggle-normalization`), Автовоспроизведение (`#toggle-autoplay`).
     * Встроенный 10-полосный графический эквалайзер: переключатель режимов (3, 6, 10 полос), выбор пресетов (Flat, Bass Boost, Treble Boost, Vocal, Rock, Pop, Jazz), слайдер Preamp (-20...+20 dB), вертикальные слайдеры полос частот, кнопка сброса `#btn-eq-reset`.
     * Стиль визуализатора: Полосы (Bars), Волна (Wave), Круг (Circle).
  8. **Эффективность & Оптимизация (`#settings-optimization`)**:
     * Пресеты оптимизации: «Максимальная красота» (`high`), «Сбалансированный» (`medium`), «Энергосбережение» (`low`).
     * Состояние ограничения: Без ограничений, При сворачивании, При потере фокуса окна.
     * Качество блюра: HQ (14px), Medium (8px), Fast (4px), Отключено (0px).
     * Неоновое свечение: Полное, Мягкое, Отключено.
     * Активные ресурсы: тумблеры отключения Фонового арта, Частиц, Обложек, Визуализаторов, Блюра.
     * Слайдеры ограничения FPS: Частицы (5–30 FPS), Визуализатор (5–60 FPS), UI/Анимации (15–60 FPS).
     * Unfocus Manager: тумблеры снижения размытия при неактивном окне, отключения анимаций, отключения визуализатора, лимита FPS неактивного окна.
  9. **Горячие клавиши (`#settings-keybinds`)**:
     * Интерактивная таблица переназначения 10 глобальных действий (Play/Pause, Next, Prev, Vol+, Vol-, Mute, Lyrics, Mini-player, Search, Like).
     * Кнопка сброса клавиш `#btn-reset-keybinds`.
  10. **Хранилище (`#settings-storage`)**:
      * Сводка размера кэша (Общий кэш, Аудио-потоки, Обложки).
      * Лимит размера кэша (1, 2, 5, 10, 20 ГБ или без лимита).
      * Кнопка полной очистки кэша `#btn-clear-storage`.
      * Сканер и удаление дубликатов треков медиатеки `#btn-scan-duplicates`.
  11. **Импорт плейлистов (`#settings-import`)**:
      * Импорт по URL (YouTube Music, Spotify, Яндекс Музыка).
  12. **Zapret (Обход DPI) (`#settings-zapret`)**:
      * Тумблер включения обхода `#toggle-zapret-enabled`.
      * Тумблер автозапуска сервиса с приложением `#toggle-zapret-autostart`.
      * Выбор режима обхода `#select-zapret-mode` (YouTube + Discord, General, Custom).
      * Автообновление бинарников winws и кнопка ручного обновления `#btn-update-zapret`.
  13. **Авторизация (`#settings-auth`)**:
      * Статус интеграции Яндекс Музыки и привязки аккаунтов.
* **Доступные действия**:
  * Закрытие окна кликом по фону оверлея или нажатием `Escape`.
  * Мгновенное применение всех визуальных и звуковых настроек без перезагрузки приложения.

---

### 1.8. Полноэкранный оверлей текста песни (Lyrics Overlay)
* **Файлы**:
  * Разметка: `ui/web_new/index.html` (строки 595–610, контейнер `#lyrics-overlay.lyrics-overlay`)
  * Стили: `ui/web_new/css/styles.css` (строки 2300–2450)
  * Логика: `ui/web_new/js/lyrics.js`
* **Блоки**:
  * Кнопка закрытия `#btn-close-lyrics` (шеврон вниз).
  * Заголовок `#lyrics-title`.
  * Элементы смещения таймингов (`-0.5s`, `+0.5s`) и кнопка двуязычного перевода.
  * Скролл-контейнер `#lyrics-container` с караоке-строками `#overlay-lyrics-content`.
* **Действия**:
  * Прокрутка и просмотр текста в крупном размере.
  * Перемотка трека по клику на строчку текста.
  * Закрытие оверлея.

---

### 1.9. Очередь воспроизведения (Queue Overlay / Drawer)
* **Файлы**:
  * Разметка: `ui/web_new/index.html` (строки 613–623 `#queue-overlay`, строки 2231–2237 `#queue-drawer`)
  * Стили: `ui/web_new/css/styles.css` (строки 2450–2485, 4440–4475)
  * Логика: `ui/web_new/js/queue.js`
* **Блоки**:
  * Кнопка закрытия очереди `#btn-close-queue` / `#queue-drawer-close`.
  * Контейнер элементов очереди `#queue-drawer-content`.
  * Drag-handle захваты на каждом элементе трека.
* **Действия**:
  * Перетаскивание треков (Drag-and-Drop) для изменения порядка.
  * Клик по любому треку в очереди для немедленного перехода к его воспроизведению.
  * Закрытие по клику вне области (на `#queue-backdrop`) или клавишей `Escape`.

---

### 1.10. Компактный плавающий мини-плеер (Mini Player Overlay)
* **Файлы**:
  * Разметка: `ui/web_new/index.html` (строки 70–118, `#mini-player-overlay.mini-player-card`)
  * Стили: `ui/web_new/css/styles.css` (строки 4200–4350)
  * Логика: `ui/web_new/js/player.js`
* **Блоки**:
  * Обложка с fallback-иконкой `#mp-cover-wrap`, `#mp-cover`.
  * Зона перетаскивания окна с информацией о треке `.mp-info.pywebview-drag-region` (`#mp-title`, `#mp-artist`).
  * Кнопки управления: Предыдущий `#mp-btn-prev`, Play/Pause `#mp-btn-play`, Следующий `#mp-btn-next`, Лайк `#mp-btn-like`, Свернуть в трей `#mp-btn-minimize`, Развернуть `#mp-btn-expand`, Закрыть `#mp-btn-close`.
  * Тонкая полоса прогресса `#mp-progress-track`, `#mp-progress-fill` и метки времени `#mp-time-current`, `#mp-time-total`.
* **Действия**:
  * Управление воспроизведением из мини-окна поверх всех окон.
  * Перетаскивание мини-плеера по рабочему столу.
  * Разворачивание обратно в полноразмерный интерфейс.

---

### 1.11. Мастер первоначальной настройки (Onboarding Wizard)
* **Файлы**:
  * Разметка: `ui/web_new/index.html` (строки 2091–2225, `#onboarding-wizard.modal-overlay`)
  * Стили: `ui/web_new/css/styles.css` (секции `.onboarding-step`, `.preset-card`, строки 2900–3000)
  * Логика: `ui/web_new/js/onboarding.js`
* **Шаги**:
  1. Шаг 1: Оформление и производительность (выбор пресета «Красота» / «Скорость», акцентный цвет `#ob-accent-color`).
  2. Шаг 2: Настройка звука (устройство `#ob-audio-device`, Crossfade `#ob-crossfade`, нормализация громкости `#ob-volume-norm`).
  3. Шаг 3: Медиатека (поле быстрой вставки ссылки на плейлист `#ob-playlist-url`).
  4. Шаг 4: Система (тумблеры Автозапуска `#ob-autostart` и Сворачивания в трей `#ob-tray`).
* **Действия**:
  * Навигация по шагам (Далее `#ob-btn-next`, Назад `#ob-btn-back`).
  * Пропуск настройки (`#ob-btn-skip`, `#ob-btn-close`).
  * Завершение и автоматическое сохранение параметров (`#ob-btn-finish`).

---

### 1.12. Модальные диалоговые окна
1. **Создание плейлиста (`#modal-create-playlist`)**:
   * Разметка: `index.html:1966–1981`. Поле ввода названия `#modal-cp-input`, кнопки «Отмена» и «Создать».
2. **Подтверждение удаления плейлиста (`#modal-delete-playlist`)**:
   * Разметка: `index.html:1984–2003`. Иконка предупреждения, текст названия `#modal-dpl-name`, кнопки «Отмена» и «Удалить».
3. **Импорт внешнего плейлиста (`#modal-import-playlist`)**:
   * Разметка: `index.html:2006–2031`. Поля URL `#modal-ip-url`, имя `#modal-ip-name`, спиннер статуса `#modal-ip-status`.
4. **Редактор тегов трека (`#modal-edit-tags`)**:
   * Разметка: `index.html:2034–2084`. Замена обложки `#modal-et-btn-cover`, поля «Название», «Исполнитель», «Альбом», «Жанр», «Год».
5. **Детали альбома (`#album-detail-modal`)**:
   * Динамическое окно в `search.js:548–621`. Обложка, метаданные, кнопка «Слушать всё», список треков альбома.
6. **Детали внешнего плейлиста (`#playlist-detail-modal`)**:
   * Динамическое окно в `search.js:753–820`. Обложка, метаданные, кнопка «Слушать всё», список треков.

---

## 2. Дизайн-система как она есть

Дизайн-система построена на темной эстетике Glassmorphism с кастомными CSS-переменными, системными и загружаемыми шрифтами, полупрозрачными панелями и динамическими акцентами.

### 2.1. Базовые CSS-токены (`themes.css` и `styles.css`)
Объявлены в `themes.css` (строки 6–28) и `styles.css` (строки 16–36):

```css
:root {
    --text-main: #ffffff;
    --text-sec: rgba(255, 255, 255, 0.7);
    --text-dim: rgba(255, 255, 255, 0.45);
    --border: rgba(255, 255, 255, 0.08);
    --bg-panel: rgba(255, 255, 255, 0.03);
    --bg-card: rgba(255, 255, 255, 0.03);
    --bg-hover: rgba(255, 255, 255, 0.08);
    --bg-active: rgba(255, 255, 255, 0.12);

    --primary: #a855f7;          /* Фиолетовый по умолчанию */
    --primary-rgb: 168, 85, 247;
    --primary-fg: #ffffff;
    --accent: #a855f7;
    --accent-glow: rgba(168, 85, 247, 0.25);
    --ambient-glow: rgba(168, 85, 247, 0.2);

    --success: #10b981;
    --error: #ef4444;
    --warning: #f59e0b;
    --shadow-color: rgba(0, 0, 0, 0.6);

    /* Токены производительности и размытия */
    --glass-blur: 8px;
    --blur-sm: calc(var(--glass-blur) * 0.75);
    --blur-md: var(--glass-blur);
    --blur-lg: calc(var(--glass-blur) * 1.5);
    --blur-xl: calc(var(--glass-blur) * 2);
    --player-glow-blur: 40px;
    --player-glow-opacity: 0.5;
    --ambient-blur: 50px;
}
```

---

### 2.2. Темы оформления (22 темы в `themes.css`)

Каждая тема активируется атрибутом `data-theme="..."` на элементе `<html>` и переопределяет цвета фона, поверхностей, акцентных свечений и основного цвета:

| # | ID темы (`data-theme`) | Название | `--bg-main` | `--bg-surface` | `--accent` / `--primary` | `--primary-fg` | Свечение (`--accent-glow`) |
|---|---|---|---|---|---|---|---|
| 1 | `amoled` | AMOLED | `#000000` | `#0a0a0a` | `#ffffff` | `#000000` | `rgba(255, 255, 255, 0.15)` |
| 2 | `dark` | Dark | `#0a0a0f` | `#14141d` | `#a855f7` | `#ffffff` | `rgba(168, 85, 247, 0.25)` |
| 3 | `midnight` | Midnight | `#0a0e17` | `#101622` | `#3b82f6` | `#ffffff` | `rgba(59, 130, 246, 0.15)` |
| 4 | `emerald` | Emerald | `#0b1410` | `#111f18` | `#10b981` | `#ffffff` | `rgba(16, 185, 129, 0.15)` |
| 5 | `sunset` | Sunset | `#170c0a` | `#241310` | `#f97316` | `#ffffff` | `rgba(249, 115, 22, 0.15)` |
| 6 | `ocean` | Ocean | `#06141a` | `#0a2029` | `#06b6d4` | `#ffffff` | `rgba(6, 182, 212, 0.15)` |
| 7 | `lavender` | Lavender | `#130b1c` | `#1d112b` | `#a855f7` | `#ffffff` | `rgba(168, 85, 247, 0.15)` |
| 8 | `rose` | Rose | `#1a0b12` | `#26111a` | `#ec4899` | `#ffffff` | `rgba(236, 72, 153, 0.15)` |
| 9 | `amber` | Amber | `#1a120e` | `#261a15` | `#ff9f1c` | `#000000` | `rgba(255, 159, 28, 0.15)` |
| 10 | `slate` | Slate | `#0f172a` | `#1e293b` | `#94a3b8` | `#ffffff` | `rgba(148, 163, 184, 0.15)` |
| 11 | `neutral` | Neutral | `#18181b` | `#27272a` | `#a1a1aa` | `#000000` | `rgba(161, 161, 170, 0.15)` |
| 12 | `crimson` | Crimson | `#1a0b0e` | `#281115` | `#ef4444` | `#ffffff` | `rgba(239, 68, 68, 0.15)` |
| 13 | `dracula` | Dracula | `#1e1f29` | `#282a36` | `#ff79c6` | `#ffffff` | `rgba(255, 121, 198, 0.15)` |
| 14 | `nord` | Nord | `#2e3440` | `#3b4252` | `#88c0d0` | `#2e3440` | `rgba(136, 192, 208, 0.15)` |
| 15 | `sky` | Sky | `#0c192c` | `#13243f` | `#38bdf8` | `#0c192c` | `rgba(56, 189, 248, 0.15)` |
| 16 | `mint` | Mint | `#061a14` | `#0c2920` | `#34d399` | `#061a14` | `rgba(52, 211, 153, 0.15)` |
| 17 | `violet` | Violet | `#160c28` | `#22133e` | `#a855f7` | `#ffffff` | `rgba(168, 85, 247, 0.15)` |
| 18 | `blossom` | Blossom | `#1f0b18` | `#301126` | `#f43f5e` | `#ffffff` | `rgba(244, 63, 94, 0.15)` |
| 19 | `sakura` | Sakura | `#1c0d15` | `#2b1421` | `#fb7185` | `#ffffff` | `rgba(251, 113, 133, 0.15)` |
| 20 | `terminal` | Terminal | `#051405` | `#0a240a` | `#22c55e` | `#051405` | `rgba(34, 197, 94, 0.15)` |
| 21 | `sand` | Sand | `#1c160c` | `#2c2213` | `#f59e0b` | `#000000` | `rgba(245, 158, 11, 0.15)` |
| 22 | `aqua` | Aqua | `#081b24` | `#0e2b39` | `#06b6d4` | `#ffffff` | `rgba(6, 182, 212, 0.15)` |

---

### 2.3. Шрифтовая система
* **Базовый шрифт**: переменная `--font-family: 'Segoe UI', system-ui, -apple-system, sans-serif` (`styles.css:17`).
* **Разрешенные внешние шрифты в CSP (`index.html:10`)**: `https://fonts.googleapis.com` и `https://fonts.gstatic.com`.
* **Стек эмодзи в частицах (`particles.js:195–197`)**: `"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif`.
* **Шрифтовые пресеты в настройках (`settings.js:447–491`)**:
  * *Системные*: Inter, Arial, Segoe UI, Roboto, Helvetica Neue, Tahoma, Verdana, San Francisco, Calibri, Lucida Sans, Arial Black, Segoe UI Light, Segoe UI Semibold.
  * *Modern*: Outfit, Montserrat, Plus Jakarta Sans.
  * *Serif*: Georgia, Times New Roman, Garamond.
  * *Mono*: Consolas, Courier New, Monaco.
  * *Hand*: Cursive, Comic Sans MS.
  * *Deco*: Impact, Trebuchet MS.
  * *Game*: 8-Bit Retro (`Courier New`), Copperplate.
* **Масштабирование**: слайдер `#slider-font-size` (12–24px) меняет `document.documentElement.style.fontSize` и CSS-переменную `--font-size-base`.

---

### 2.4. Скругления, тени и отступы

В проекте отсутствует жесткий централизованный справочник токенов радиусов и теней; значения распределены по селекторам:
* **Скругления (`border-radius`)**:
  * `4px`: иконки логотипа в тайтлбаре, заглушки скелетонов.
  * `6px`: бейджи, кнопки сдвига текста, переключатель периода Wrapped.
  * `8px`: обложки мини-плеера, кнопки действий, тосты.
  * `10px`: `.filter-btn`, `.keybind-record-btn`, обложка редактора тегов.
  * `12px`: кнопки `.btn-primary`, карточки `.feed-card-cover`, `.opt-card`.
  * `16px`: `#player-bar`, карточки `#opt-card-box`, плейлисты `.playlist-card`.
  * `18px`: карточки аналитики Wrapped, `.player-glass-card`.
  * `20px`: модальные карточки альбома/плейлиста, `.settings-modal-card`.
  * `24px` / `50%`: круглые кнопки Play (`.btn-play-large`, `.btn-play-main`), аватары, круглые обложки.
* **Тени (`box-shadow`)**:
  * Карточки и модалки: `0 8px 24px rgba(0, 0, 0, 0.3)`, `0 20px 50px rgba(0, 0, 0, 0.6)`.
  * Активные элементы: `0 4px 14px rgba(245, 158, 11, 0.3)`, `0 0 20px var(--primary)`.
  * Плеер-бар: `0 8px 32px rgba(0, 0, 0, 0.5)`.

---

### 2.5. Полный реестр использования Glass-morphism и Backdrop-filter

Все вхождения `backdrop-filter` с точной привязкой к файлам и строкам:

| Файл | Строка | Селектор / Элемент | Значение `backdrop-filter` |
|---|---|---|---|
| `ui/web_new/css/styles.css` | 361, 367, 373 | `.glass-panel`, `#sidebar`, `#player-bar` | `blur(var(--glass-blur, var(--blur-md, 14px)))` |
| `ui/web_new/css/styles.css` | 442 | `.card`, `.stat-card` | `blur(var(--blur-md))` |
| `ui/web_new/css/styles.css` | 526 | `.player-glass-card` | `blur(var(--blur-md))` |
| `ui/web_new/css/styles.css` | 607 | `.search-capsule` | `blur(var(--blur-sm))` |
| `ui/web_new/css/styles.css` | 806 | `.lib-top-card` | `blur(var(--blur-sm))` |
| `ui/web_new/css/styles.css` | 924 | `.search-platform-dropdown` | `blur(var(--blur-xl))` |
| `ui/web_new/css/styles.css` | 1205 | `.context-menu`, `.rich-track-menu` | `blur(var(--blur-md))` |
| `ui/web_new/css/styles.css` | 1441 | `.player-header-title` | `blur(var(--blur-sm))` |
| `ui/web_new/css/styles.css` | 3151 | `.settings-modal-card` | `blur(24px) !important` |
| `ui/web_new/css/styles.css` | 3596 | `.modal-overlay` | `blur(14px)` |
| `ui/web_new/css/styles.css` | 3624 | `.glass-modal-card` | `blur(28px)` |
| `ui/web_new/css/styles.css` | 4235 | `#mini-player-overlay` | `blur(8px)` |
| `ui/web_new/css/styles.css` | 4251 | `.mp-compact-row` | `blur(3px)` |
| `ui/web_new/css/styles.css` | 4361 | `.playback-bar` | `blur(var(--glass-blur)) saturate(180%)` |
| `ui/web_new/css/styles.css` | 4448 | `#queue-drawer` | `blur(30px)` |
| `ui/web_new/css/styles.css` | 4486 | `.lyrics-overlay` | `blur(50px)` |
| `ui/web_new/css/styles.css` | 4553 | `#album-modal-container` | `blur(20px)` |
| `ui/web_new/css/styles.css` | 4629 | `.dropdown-content` | `blur(8px)` |
| `ui/web_new/css/styles.css` | 4709 | `.custom-glass-dropdown-menu` | `blur(16px)` |
| `ui/web_new/css/styles.css` | 4763 | `.volume-popup` | `blur(8px)` |
| `ui/web_new/index.html` | 2091 | `#onboarding-wizard` | `blur(12px)` (inline style) |
| `ui/web_new/js/artist_profile.js`| 426 | `.artist-btn-shuffle` | `blur(8px)` (inline style) |
| `ui/web_new/js/search.js` | 553 | `#album-detail-modal` | `blur(10px)` (inline style) |
| `ui/web_new/js/search.js` | 758 | `#playlist-detail-modal` | `blur(10px)` (inline style) |

---

## 3. Нижний плеер-бар (Playback Bar)

### 3.1. Разметка (`index.html:1876–1939`)
Плеер-бар размещен фиксированно внизу экрана `#player-bar` (grid из 3 колонок: левая инфо-колонка, центральная колонка управления и прогресса, правая колонка очереди и громкости):

```html
<div id="player-bar">
    <!-- Левая секция: Информация о треке -->
    <div class="pb-track">
        <img id="pb-cover" class="pb-cover" src="" alt="">
        <div class="pb-info">
            <div class="pb-title" id="pb-title">Не играет</div>
            <div class="pb-artist" id="pb-artist">Выберите трек</div>
        </div>
        <button class="btn-ctrl" id="pb-btn-like" title="Нравится">
            <i data-lucide="heart" style="width:14px;height:14px"></i>
        </button>
        <button class="btn-ctrl" id="pb-btn-options" title="Опции">
            <i data-lucide="more-horizontal" style="width:14px;height:14px"></i>
        </button>
    </div>

    <!-- Центральная секция: Кнопки и таймлайн -->
    <div class="pb-controls">
        <div class="pb-buttons">
            <button class="btn-ctrl" id="pb-btn-shuffle" title="Перемешать">
                <i data-lucide="shuffle"></i>
            </button>
            <button class="btn-ctrl" id="pb-btn-prev" title="Предыдущий">
                <i data-lucide="skip-back"></i>
            </button>
            <button class="btn-play-main" id="pb-btn-play" title="Воспроизведение">
                <i data-lucide="play"></i>
            </button>
            <button class="btn-ctrl" id="pb-btn-next" title="Следующий">
                <i data-lucide="skip-forward"></i>
            </button>
            <button class="btn-ctrl" id="pb-btn-repeat" title="Повтор">
                <i data-lucide="repeat"></i>
            </button>
            <button class="btn-ctrl active" id="pb-btn-flow" title="Бесконечная волна (Flow)">
                <i data-lucide="radio"></i>
            </button>
        </div>
        <div class="pb-progress">
            <span class="pb-time" id="pb-time-current">0:00</span>
            <div class="progress-track" id="pb-progress-track">
                <canvas id="pb-waveform-canvas" class="waveform-canvas hidden"></canvas>
                <div class="progress-fill" id="pb-progress-fill"></div>
            </div>
            <span class="pb-time" id="pb-time-total">0:00</span>
        </div>
    </div>

    <!-- Правая секция: Очередь и громкость -->
    <div class="pb-right">
        <button class="btn-ctrl" id="pb-btn-queue" title="Очередь">
            <i data-lucide="list-music"></i>
        </button>
        <div class="volume-wrap">
            <button class="btn-ctrl" id="pb-volume-btn" title="Громкость">
                <i data-lucide="volume-2"></i>
            </button>
            <div class="volume-track" id="pb-volume-track">
                <div class="volume-fill" id="pb-volume-fill" style="width:70%"></div>
            </div>
        </div>
    </div>
</div>
```

### 3.2. Логика и обработка состояний (`player.js`)
* **Воспроизведение и Пауза**:
  * По нажатию `#pb-btn-play` переключается состояние `isPlaying`.
  * Иконка кнопки меняется между `play` и `pause` с сохранением настроек активного пака иконок (`window.__PACK_ICON_MAPS__`).
  * Одновременно синхронизируются кнопки в полноэкранном плеере (`#pp-btn-play`) и мини-плеере (`#mp-btn-play`).
* **Изменение трека (`onTrackChanged`)**:
  * Обновляются названия (`#pb-title`, `#pb-artist`, `#pp-title`, `#pp-artist`, `#mp-title`, `#mp-artist`).
  * Обновляются обложки на всех трех плеерах.
  * Синхронизируется состояние кнопки «Лайк» (`#pb-btn-like`, `#pp-btn-like`, `#mp-btn-like`) по флагу `track.is_favorite`.
  * Запускается экстракция доминантного цвета обложки через `extractDominantColor()` для обновления фонового свечения `#player-bg-glow`.
* **Перемотка (Seeking)**:
  * Поддерживается клик и непрерывное перетаскивание (drag) по `#pb-progress-track`.
  * Полоса прогресса управляется через `transform: translateX(-X%)` на GPU (вместо медленного изменения `width`).
  * Во время драга таймер времени плавно обновляется локально; после отпускания мыши отправляется единичный RPC вызов `seekTo()`.
* **Регулировка громкости**:
  * Поддерживается клик и драг по `#pb-volume-track`.
  * Полоса громкости меняет `width` у `#pb-volume-fill`.
  * Одиночный клик по `#pb-volume-btn` переключает режим `Mute` (сохраняя прошлый уровень громкости).
  * Вызовы RPC `set_volume` троттлятся с интервалом 100 мс (`scheduleVolumeRpc`).
* **Кнопка опций трека (`#pb-btn-options`)**:
  * Открывает контекстное меню `#track-options-menu` (добавление в плейлист, скачивание, копирование названия, переход в плеер).
* **Бесконечная волна (Flow) (`#pb-btn-flow`)**:
  * Переключает автоматическую подгрузку похожих треков при окончании очереди.
* **Перемешивание (Shuffle) и Повтор (Repeat)**:
  * `#pb-btn-shuffle` включает/выключает класс `.active`.
  * `#pb-btn-repeat` циклически переключает режимы: выключен -> повтор всего списка -> повтор одного трека (`repeat-1`).

---

## 4. Анимации и интерактивные элементы

### 4.1. Реестр всех CSS Keyframe анимаций в `styles.css`

| Название `@keyframes` | Строка | Селекторы / Элементы | Описание и длительность |
|---|---|---|---|
| `splashShimmer` | 162 | `.app-splash-shimmer` | `1.4s ease-in-out infinite` — мерцание полоски загрузки на сплеш-скрине |
| `pageSlideIn` | 556 | `.view-page.active` | `0.3s cubic-bezier(0.16, 1, 0.3, 1)` — плавное появление и подъем страницы |
| `panelTabSlide` | 582 | `.settings-panel.active` | `0.25s ease` — сдвиг вкладки настроек |
| `shimmer` | 758, 2872, 4394 | `.skeleton-cover`, `.skeleton-title` | `1.5s - 2s infinite linear` — шиммер-эффект скелетон-карточек |
| `dropdownFadeIn` | 933, 4721 | `.search-platform-dropdown`, `.custom-glass-dropdown-menu` | `0.2s cubic-bezier(0.16, 1, 0.3, 1)` — раскрытие меню |
| `spinIcon` | 1188 | `.spin-icon`, `.spinner` | `1s linear infinite` — вращение индикатора загрузки |
| `menuPop` | 1943 | `.context-menu.visible`, `.rich-track-menu` | `0.15s cubic-bezier(0.16, 1, 0.3, 1)` — вылет контекстного меню |
| `toastIn` | 2095 | `.toast` | `0.3s cubic-bezier(0.16, 1, 0.3, 1)` — появление тоста снизу |
| `toastOut` | 2099 | `.toast.hiding` | `0.25s ease forwards` — исчезновение тоста |
| `particleFloat` | 2119 | `.particle` | `6s ease-in-out infinite` — плавное парение DOM-частиц |
| `fadeIn` | 2127 | `.fadeIn` | `0.25s ease` — общее плавное появление |
| `spin-slow` | 2131 | `.animate-spin-slow` | `12s linear infinite` — медленное вращение винила |
| `lyricLineFadeIn` | 2346 | `.lyric-line` | `0.4s ease` — появление строки текста песни |
| `fadeInSlideUp` | 2462 | `#queue-drawer.open` | `0.3s ease` — выезд шторки очереди |
| `modalPop` | 2977 | `.glass-modal-card` | `0.25s cubic-bezier(0.16, 1, 0.3, 1)` — масштабирование модального окна |
| `heartPulse` | 3054 | `.like-btn.liked i` | `0.35s ease` — пульсация сердечка при лайке |
| `iconRotatePop` | 3061 | `.icon-btn:active` | `0.15s ease` — микро-вращение при нажатии |
| `spinVinyl` | 4062 | `.player-style-vinyl .player-cover-img` | `20s linear infinite` — вращение пластинки во время воспроизведения |
| `auraFloat` | 4875 | `.aura-orb` | `18s - 25s ease-in-out infinite alternate` — парение сфер Vision Pro |

---

### 4.2. Hover-эффекты и интерактивные переходы
* **Карточки (`.feed-card`, `.playlist-card`, `.stat-card`)**: при наведении `transform: translateY(-4px)`, увеличение яркости фона до `rgba(255, 255, 255, 0.08)`, проявление оверлея кнопки Play (`opacity: 1`).
* **Кнопки управления (`.btn-ctrl`, `.icon-btn`, `.filter-btn`)**: при наведении масштабирование `transform: scale(1.05)`, подсветка границы `border-color: rgba(255, 255, 255, 0.25)`. При нажатии (`:active`) сжатие `transform: scale(0.95)`.
* **Строки треков (`.track-item`)**: при наведении подсветка строки `background: rgba(255, 255, 255, 0.06)`, появление кнопки скачивания и меню трех точек.
* **Строки текста караоке (`.lyric-line`)**: активная строка масштабируется до `font-size: 22px; font-weight: 700; color: #ffffff`, неактивные строки полупрозрачны (`opacity: 0.35; font-size: 16px`).

---

### 4.3. Фоновые частицы (`particles.js`)
* **Технология**: HTML5 2D Canvas (`#particles-canvas`), работающий поверх слоя фона `#particles-bg`.
* **Поведение**:
  * 8 геометрических/символьных форм: точки, сердечки, звезды, снежинки, ноты, искры, флаг РФ, герб РФ.
  * Текстовые эмодзи предварительно рендерятся в скрытые Canvas-спрайты (`getEmojiSprite`) для избежания вызовов `fillText` на каждом кадре.
  * Интерактивность: курсор мыши отталкивает частицы в радиусе 60px (`pushRadius`).
  * Троттлинг FPS: настраиваемый лимит (по умолчанию 24 FPS).
  * Автоматическая пауза при скрытии окна (`document.hidden`), активации мини-плеера или переходе в режим энергосбережения.

---

### 4.4. Vision Pro Glass Aura Orbs (`styles.css:4850–4900`)
* **Контейнер**: `#aura-orbs-container.aura-orbs-container`.
* **Сферы**: три градиентных размытых пятна (`orb-1`, `orb-2`, `orb-3`) с фильтром `filter: blur(80px)` и анимацией `auraFloat` (разные траектории движения).
* **Логика управления**: автоматически отключаются в светлой теме (`data-theme="light"`), при пресете низкой производительности (`.perf-low`) или при работе от батареи (`.battery-saver-active`).

---

### 4.5. Аудио-визуализатор (`visualizer.js`)
* **Контейнеры**: `#visualizer-canvas` (на странице плеера) и `#home-visualizer-canvas` (на главной странице).
* **Стили визуализации**:
  1. `bars` — 48 вертикальных столбиков с линейным градиентом от цвета `--primary-rgb`.
  2. `wave` — плавная заполненная синусоидальная волна (кривые Безье).
  3. `circle` — радиальный круговой визуализатор вокруг обложки.
* **Источник данных**: Web Audio API (`AnalyserNode.getByteFrequencyData`) с частотной сеткой 64 бина. При отсутствии живого потока активна процедурная симуляция на базе синусоид и битов.

---

## 5. Компоненты интерфейса

### 5.1. Кнопки
1. `.btn-primary`: акцентная кнопка с фоном `var(--primary)` и скруглением 12px.
2. `.filter-btn`: стеклянная кнопка фильтра с полупрозрачным фоном `rgba(255, 255, 255, 0.05)` и тонкой границей `1px solid rgba(255, 255, 255, 0.12)`.
3. `.btn-ctrl`: квадратная/круглая прозрачная кнопка управления плеером (32x32px или 36x36px).
4. `.btn-play-main`: главная круглая кнопка воспроизведения (40x40px) в нижнем баре.
5. `.btn-play-large`: крупная круглая кнопка Play (48x48px) на странице плеера и плейлиста.
6. `.icon-btn`: универсальная компактная кнопка с иконкой.
7. `.opt-card` / `.opt-toggle-btn`: крупные плиточные кнопки настроек с иконками.
8. `.keybind-record-btn`: кнопка захвата клавиши в настройках с состоянием «Нажмите клавишу...».

---

### 5.2. Карточки
1. `.feed-card`: карточка трека/альбома в горизонтальных лентах с квадратной обложкой (`aspect-ratio: 1/1`), заголовком и подзаголовком.
2. `.stat-card`: плитка статистики с крупным числовым значением (`font-size: 24px; font-weight: 700`) и подписью.
3. `.lib-top-card`: крупная градиентная карточка («Любимые», «Оффлайн»).
4. `.skeleton-card`: карточка-заглушка с анимированными серыми блоками.
5. `.workshop-card`: карточка обоев с превью, бейджем, оверлеем и счетчиком лайков.
6. `.theme-card`: карточка пресета темы с тремя цветными точками и бейджем активного выбора.

---

### 5.3. Элементы списка треков (`.track-item`)
* **Структура**:
  * Номер трека или иконка перетаскивания `.drag-handle`.
  * Обложка трека (40x40px) с fallback SVG-нотой.
  * Блок названия и автора с кликабельным исполнителем `.clickable-artist`.
  * Иконка источника (YouTube / SoundCloud / Spotify / Local).
  * Кнопка скачивания `.download-btn` со статусами: обычная, `.downloading` (спиннер), `.downloaded` (зеленая галочка).
  * Кнопка добавления в любимые `.like-btn`.
  * Кнопка вызова меню `.track-more-btn` (`...`).
  * Длительность трека (`M:SS`).
* **Состояние воспроизведения**: при активном треке добавляется класс `.playing`, название окрашивается в `var(--primary)`.

---

### 5.4. Модальные окна, тосты и меню
* **Тосты (`#toast-container`, `.toast`)**: всплывающие уведомления в правом нижнем углу с 4 типами статусов (`info`, `success`, `warning`, `error`), прогресс-полосой и авто-исчезновением через 3–4 сек.
* **Контекстные меню**:
  * `.context-menu` (`#playlist-context-menu`, `#track-options-menu`): темное меню с размытием 14px.
  * `.rich-track-menu`: богатое всплывающее меню с шапкой обложки трека и 11 действиями.
* **Селекторы и дропдауны**: `.search-platform-dropdown`, `.custom-glass-dropdown-menu` с темным стеклянным фоном.

---

### 5.5. Формы ввода, переключатели и слайдеры
* **Поля ввода (`.text-input`, `.glass-modal-input`, `.search-input`)**: прозрачный или полупрозрачный фон `rgba(255, 255, 255, 0.06)`, тонкая рамка, скругление 8–12px, белый текст, отсутствие браузерного outline.
* **Переключатели (`.toggle-switch`)**: стеклянный свитч (ширина 44px, высота 24px) с подвижной точкой `.toggle-dot`. При включении (`.on`) фон переходит в `var(--primary)`, а точка смещается вправо.
* **Слайдеры (`input[type="range"]`, `.progress-track`, `.volume-track`)**:
  * Горизонтальные треки с заполнением `.progress-fill` / `.volume-fill`.
  * Вертикальные полосы эквалайзера `.eq-band-slider`.

---

## 6. Настройки, влияющие на внешний вид

Все пользовательские параметры из вкладки «Настройки» и их точная техническая реализация:

| Название настройки в UI | Ключ хранилища | Техническое действие в DOM / CSS |
|---|---|---|
| **Режим темы** (Dark / Light / System) | `theme_mode` | Устанавливает атрибут `data-theme="dark\|light"` на `<html>` |
| **Пресеты тем** (22 темы) | `theme` | Устанавливает `data-theme="[id]"` на `<html>` |
| **Кастомные цвета темы** | `color_*` | Меняет CSS-переменные `--primary`, `--accent`, `--bg-main`, `--text-main`, `--bg-card`, `--border`, `--text-dim` |
| **Семейство шрифта** | `font_family` | Меняет CSS-переменную `--font-family` |
| **Размер шрифта** | `font_size` | Меняет `document.documentElement.style.fontSize` (12–24px) и `--font-size-base` |
| **Прозрачность окна** | `transparency_enabled`, `transparency_level` | Меняет `--app-bg-opacity` (0.2–1.0) |
| **Размытие стекла** | `glass_blur` | Меняет `--glass-blur`, `--blur-sm`, `--blur-md`, `--blur-lg`, `--blur-xl` |
| **Пользовательский фон** | `custom_bg_image` | Устанавливает `background-image` на `#custom-bg-layer` |
| **Размытие фона** | `bg_blur` | Устанавливает `filter: blur(Xpx)` на `#custom-bg-layer` |
| **Затемнение фона** | `bg_dim` | Устанавливает `background-color: rgba(0,0,0, X)` на `#custom-bg-dim-layer` |
| **Пак иконок** (10 паков) | `icon_pack` | Устанавливает `data-icon-pack="[id]"` и меняет иконки `data-lucide` |
| **Частицы: тумблер** | `particles_enabled` | Запускает/останавливает цикл `requestAnimationFrame` в Canvas |
| **Частицы: форма, кол-во, скорость, размер** | `particles_*` | Перестраивает массив частиц в `particles.js` |
| **Стиль плеера** (Default / Vinyl) | `player_style` | Добавляет класс `.player-style-vinyl` на `<html>` |
| **Выравнивание заголовка плеера** | `title_align` | Добавляет класс `.title-align-left\|center\|right` на `<html>` |
| **Стиль слайдера прогресса** | `slider_type` | Добавляет класс `.slider-type-default\|thin\|ios\|wave` на `<html>` |
| **Vision Pro Aura Orbs** | `aura_orbs_enabled` | Добавляет/удаляет класс `.disabled` на `#aura-orbs-container` |
| **Отображение очереди** | `show_queue` | Скрывает/показывает кнопку очереди `#pb-btn-queue` |
| **Позиция очереди** | `queue_pos` | Добавляет класс `.queue-pos-bottom\|left\|right` на `<html>` |
| **Вид очереди** | `queue_view` | Добавляет класс `.queue-view-normal\|expanded` на `<html>` |
| **Мини-плеер: форма прогресса/обложки/окна** | `mp_*` | Добавляет классы `.mp-progress-*`, `.mp-cover-*`, `.mp-shape-*` на `<html>` |
| **Пресеты производительности** (High/Medium/Low) | `performance_preset` | Добавляет классы `.perf-medium` или `.perf-low` на `<html>` (отключает блюр, тени, переходы) |
| **Качество размытия** (HQ/Mid/Fast/Off) | `blur_quality` | Принудительно задает фиксированные значения переменным `--blur-*` |
| **Неоновое свечение обложки** | `glow_quality` | Задает `--player-glow-blur` (40px/22px/0px) и `--player-glow-opacity` |
| **Unfocus Manager** (Эффективность при расфокусе) | `unfocus_*` | Добавляет `.unfocused-blur-disabled`, `.unfocused-animations-disabled` на `<body>` |

---

## 7. Адаптивность

В приложении реализованы следующие медиазапросы (`styles.css`):

### 7.1. Брейкпоинт `@media (max-width: 900px)` (`styles.css:2491–2535`)
* Боковое меню `#sidebar` уменьшается с 240px до 70px (схлопывается в иконки).
* Скрываются текстовые лейблы `.sidebar-logo span`, `.nav-section-label`, `.nav-item span`.
* Пункты навигации центрируются (размер 44x44px).
* Горизонтальные ленты `.feed-scroll` перестраиваются в адаптивную сетку `grid-template-columns: repeat(auto-fill, minmax(130px, 1fr))`.
* Карточки `.feed-card` занимают 100% ширины ячейки сетки.
* Нижний плеер-бар `#player-bar` перестраивает колонки в `grid-template-columns: 1fr 2fr 0.5fr`.
* Метки времени `.pb-time` в плеер-баре скрываются.

### 7.2. Брейкпоинт `@media (max-width: 768px)` (`styles.css:3973, 4419–4438`)
* Сетка параметров в оптимизации `.opt-grid.cols-5` схлопывается до 3 колонок.
* Скрывается имя артиста `.pb-left .track-info .track-artist` в плеер-баре.
* Скрывается правый блок громкости `.pb-right`.
* Сайдбар сужается до 60px.

### 7.3. Брейкпоинт `@media (max-width: 600px)` (`styles.css:2537–2578`)
* Сайдбар `#sidebar` перемещается в нижнюю часть экрана как мобильный таббар (`position: fixed; bottom: 0; width: 100%; height: 60px; flex-direction: row`).
* Логотип, разделители и спейсеры сайдбара скрываются.
* Нижний плеер-бар поднимается над таббаром (`bottom: 70px; height: 70px`) и переходит в двухколоночный режим (`grid-template-columns: 1fr 1fr`).
* Блок громкости `.pb-right` полностью скрывается.
* Контентная область `#main-content` получает нижний отступ `margin-bottom: 160px`.
* Карточки в лентах уменьшаются до минимальной ширины 110px.

### 7.4. Медиазапрос `@media (prefers-reduced-motion: reduce)` (`styles.css:3916–3929`)
* Полностью отключаются CSS-анимации и переходы для `.lyric-line`, `.skeleton-*`, `.particle`, `.feed-card`, `.nav-item`, `.track-item`.

---

## 8. Известные слабые места и несогласованности

Ниже зафиксированы фактические визуальные и структурные несогласованности, дублирование стилей и устаревший код без предложений решений:

1. **Тройное дублирование ключевых кадров `@keyframes shimmer`**:
   * `styles.css:758` (`@keyframes shimmer`)
   * `styles.css:2872` (`@keyframes shimmer`)
   * `styles.css:4394` (`@keyframes shimmer`)
2. **Двойное дублирование `@keyframes dropdownFadeIn`**:
   * `styles.css:933`
   * `styles.css:4721`
3. **Дублирование разметки очереди**:
   * В `index.html` одновременно присутствуют два элемента очереди: `#queue-overlay` (строка 613) и `#queue-drawer` (строка 2231).
4. **Несогласованность именования селекторов и CSS-переменных**:
   * Для плеер-бара в стилях параллельно используются селекторы `#player-bar` (строки 1876, 2528) и устаревший `.playback-bar` (строка 4355, 4420).
   * Для бокового меню используются селекторы `#sidebar` и устаревший `.sidebar` (строка 4432).
   * В разных темах используются конфликтующие имена: `--bg-main` vs `--background` (`themes.css:55`), `--bg-surface` vs `--surface` (`themes.css:56`), `--accent` vs `--primary`.
5. **Фрагментация объявления backdrop-filter**:
   * Значения блюра разбросаны между CSS-переменными (`var(--blur-md)`), жестко прописанными пикселями в CSS (`blur(24px)`, `blur(30px)`, `blur(50px)`) и inline-стилями в JS (`modal.style.cssText = '... backdrop-filter:blur(10px)...'`).
6. **Массивное использование жестко закодированных inline-стилей**:
   * В `index.html` сотни элементов содержат атрибуты `style="..."` с жесткими цветами `rgba(255,255,255,0.06)`, отступами и z-index (например, строки 47, 49, 172, 226, 235, 628, 2091).
   * В JS файлах (`artist_profile.js`, `search.js`, `settings.js`, `utils.js`) разметка генерируется с хардкодом inline-стилей вместо единых классов дизайн-системы.
7. **Отсутствие единой сетки радиусов и отступов**:
   * В коде присутствуют несистемные значения `border-radius`: 2px, 4px, 6px, 8px, 10px, 12px, 14px, 16px, 18px, 20px, 24px, 50%.
8. **Ручной пересчет градиентов по строковому хешу**:
   * В `artist_profile.js` (строки 6–17), `search.js` (строки 630–639) и `utils.js` параллельно объявлены три разных массива fallback-градиентов с разной логикой хеширования строк.
