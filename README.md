# NeDotify Linux

Порт текущего Windows desktop-приложения: обычный и macOS-интерфейс,
поиск и воспроизведение через локальный прокси, библиотека и плейлисты,
скачивание, офлайн-файлы, тексты, эквалайзер, рекомендации и непрерывная волна.
Оба оформления работают внутри одного приложения; macOS не требуется.

**Состояние на 2026-11-05:** исходники и Linux-адаптации перенесены;
нативные запуск, звук, скриншоты и готовый Linux-пакет пока не подтверждены.
Работа выполнялась на Windows без установленного WSL. Подробный статус и
доказательства: [матрица соответствия](docs/WINDOWS_PARITY.md),
[проверки](docs/LINUX_VALIDATION.md).

## Установка из исходников

Заявленная среда сборки: **Ubuntu 24.04 x86_64, Python 3.12+**, Qt 6 WebEngine,
PipeWire/PulseAudio и графический сеанс X11 или Wayland. Другие дистрибутивы,
ARM и старые glibc требуют отдельной нативной проверки. Виртуальное окружение
из другой ОС использовать нельзя.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg libegl1 libgl1 libnss3 libnspr4 \
  libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcomposite1 libxdamage1 libxrandr2 \
  libxtst6 libasound2t64 libdbus-1-3 libsecret-1-0 libpulse0 \
  gnome-keyring libnotify-bin libfontconfig1 libfreetype6
bash install_linux.sh --source
bash start_linux.sh
```

Ручной запуск после установки зависимостей: `.venv/bin/python main.py`.
Qt выбирается явно; Chromium sandbox включён. На Wayland запускать приложение
нужно из своего графического сеанса. Для окружения без поддерживаемого Wayland
plugin можно явно выбрать XWayland: `QT_QPA_PLATFORM=xcb bash start_linux.sh`.
Реальный `DISPLAY`/`WAYLAND_DISPLAY` задаёт сеанс, приложение их не подделывает.

FFmpeg/ffprobe берутся из Linux PATH или инструментов мастера настройки.
yt-dlp устанавливается с EJS, curl_cffi и Deno для JavaScript challenges.
Мастер поддерживает проверку, установку и обновление Linux-инструментов;
процесс проигрывателя не меняет собственный импортированный yt-dlp через pip.

## Обновление и удаление

При установке исходников ярлык запускает текущую рабочую копию. Для обновления
нужно закрыть приложение, обновить исходники, повторить
`bash install_linux.sh --source` и запустить снова. Зависимости обновляются
между сеансами приложения.

Portable-пакет распаковывается в отдельную папку. Из неё выполнить:

```bash
bash install_linux.sh --bundle
```

Установка для пользователя сохраняет версии в
`${XDG_DATA_HOME:-$HOME/.local/share}/nedotify-app/releases` и атомарно меняет
ссылку `current`. Предыдущая версия остаётся для отката. Debian-пакет
устанавливается через `sudo apt install ./nedotify_2.5.1_amd64.deb` и
обновляется тем же способом.

```bash
bash install_linux.sh --uninstall
# Для Debian-установки: sudo apt remove nedotify
```

Удаление приложения сохраняет пользовательский профиль `~/.nedotify/`.
Ни установка, ни обновление не переносят Windows-кеши, базы или бинарники.

## Данные и интеграции

Профиль остаётся в `~/.nedotify/`: `nedotify_storage.db`, `downloads/`,
`streams/`, `covers/`, `temp/`, `logs/`. Идентификаторы сохранённых настроек и
провайдеров сохраняются. База обновляется миграциями при открытии;
проверки миграций используют временные файлы.

Секреты сохраняются через Secret Service/KWallet. Если защищённый desktop
keyring недоступен, используется Fernet с отдельным ключом
`~/.nedotify/secrets/key` (каталог 0700, файл 0600). Это защищает отдельный
экспорт базы; доступ от имени того же пользователя позволяет прочитать ключ.
Для переноса такого профиля нужно сохранить и базу, и ключ. Windows DPAPI
зависит от Windows-аккаунта: его зашифрованные значения нельзя расшифровать
на Linux, авторизацию потребуется повторить. Исходные записи не удаляются.

Автозапуск использует XDG `.desktop`; трей — Qt; медиаклавиши и внешнее
управление — MPRIS на session D-Bus. В композиторе должен быть доступен
обработчик медиаклавиш/MPRIS и host системного трея. Discord Rich Presence
требует запущенный локальный Discord с доступным IPC.

Wayland может ограничивать абсолютное перемещение окна, topmost и глобальные
сочетания клавиш; перетаскивание/resize используют системные жесты Qt.
Произвольные глобальные комбинации назначаются в настройках композитора;
сочетания внутри приложения и MPRIS остаются доступны.

Linux-режим обхода сетевых ограничений использует upstream `tpws` как
локальный SOCKS-прокси для TCP-запросов приложения с проверкой загружаемых
ресурсов. Windows-драйвер WinDivert не переносится. Системный UDP/QUIC и
голосовой трафик Discord требуют внешней настройки `nfqws` и прав
администратора; приложение не выдаёт TCP-режим за системный обход.

Источники, требующие авторизации/подписки или доступности сервиса в регионе,
сохраняют эти требования. Spotify используется для метаданных и импорта,
воспроизведение разрешается через действующие музыкальные источники.

## Проверки и сборка

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
# Отдельно, реальные внешние запросы:
.venv/bin/python -m pytest -m network
# Настоящее приложение, временный профиль, оба UI, скриншоты:
.venv/bin/python tools/validate_linux.py --output reports/native-source

.venv/bin/python -m pip install -r requirements-build.txt
bash build_linux.sh
.venv/bin/python tools/validate_linux.py \
  --executable dist/NeDotify/NeDotify --output reports/native-package
```

Сборка выполняется **на Linux**. Результаты: onedir `dist/NeDotify/`,
`NeDotify-2.5.1-linux-amd64.tar.gz`, `nedotify_2.5.1_amd64.deb` и `SHA256SUMS`.
Оба UI, шрифты, иконки, QtWebEngineProcess, EJS и нативные ffmpeg/ffprobe/Deno
включаются в пакет. Пакет рассчитан на системные библиотеки Ubuntu 24.04.
`BUILD-REQUIREMENTS.txt` фиксирует фактически установленные версии сборщика.

[Linux CI](.github/workflows/linux-parity.yml) готовит эту среду, запускает
тесты, source/frozen UI smoke и публикует отчёты/скриншоты/артефакты.
Xvfb smoke проверяет запуск и интерфейс; слышимое воспроизведение, настоящий
Wayland и desktop-интеграции проверяются отдельно по
[нативному сценарию](docs/LINUX_VALIDATION.md).

Исторические изображения в `screenshots/` относятся к предыдущему GTK-порту.
Новые доказательства должны создаваться в `reports/native-*`; на Windows
стенд отказывается создавать отчёт об успешной Linux-проверке.
