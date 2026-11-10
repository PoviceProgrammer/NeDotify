<p align="center"><img src="screenshots/banner.png" width="100%" alt="NeDotify — Your music space"></p>

<h1 align="center">NeDotify</h1>
<p align="center"><b>NeDotify 2.5.6 для Windows 10 / 11</b><br>Локальная библиотека, онлайн-источники, тексты песен и оформление под себя.</p>
<p align="center">
  <a href="https://github.com/PoviceProgrammer/NeDotify/releases/latest"><img src="https://img.shields.io/badge/СКАЧАТЬ_ДЛЯ_WINDOWS-8b5cf6?style=for-the-badge&logo=windows&logoColor=white" alt="Скачать"></a>
  <a href="https://github.com/PoviceProgrammer/NeDotify/releases"><img src="https://img.shields.io/badge/ВСЕ_РЕЛИЗЫ-24292f?style=for-the-badge&logo=github" alt="Релизы"></a>
</p>
<p align="center"><a href="#возможности">Возможности</a> · <a href="#скриншоты">Интерфейс</a> · <a href="#установка">Установка</a> · <a href="#запуск-из-исходников">Из исходников</a></p>
<p align="center">
  <img src="https://img.shields.io/github/stars/PoviceProgrammer/NeDotify?style=flat-square" alt="Stars">
  <img src="https://img.shields.io/github/last-commit/PoviceProgrammer/NeDotify?style=flat-square" alt="Последний коммит">
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=flat-square" alt="Windows">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/PoviceProgrammer/NeDotify?style=flat-square" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square" alt="Python">
</p>

## Скриншоты

Два оформления одного Windows-приложения. Переключаются в настройках.

<details open><summary><b>Обычный интерфейс</b></summary>

<table>
<tr><td width="50%"><img src="screenshots/standard/home.png" alt="Главная"><br><sub>Главная</sub></td><td width="50%"><img src="screenshots/standard/search.png" alt="Поиск"><br><sub>Поиск</sub></td></tr>
<tr><td width="50%"><img src="screenshots/standard/library.png" alt="Библиотека"><br><sub>Библиотека</sub></td><td width="50%"><img src="screenshots/standard/player.png" alt="Плеер"><br><sub>Плеер</sub></td></tr>
<tr><td width="50%"><img src="screenshots/standard/settings.png" alt="Настройки"><br><sub>Настройки</sub></td><td width="50%"><img src="screenshots/standard/profile.png" alt="Профиль"><br><sub>Профиль</sub></td></tr>
</table>
</details>

<details><summary><b>macOS-стиль на Windows</b></summary>

<table>
<tr><td width="50%"><img src="screenshots/macos/home.png" alt="Главная"><br><sub>Главная</sub></td><td width="50%"><img src="screenshots/macos/search.png" alt="Поиск"><br><sub>Поиск</sub></td></tr>
<tr><td width="50%"><img src="screenshots/macos/library.png" alt="Библиотека"><br><sub>Библиотека</sub></td><td width="50%"><img src="screenshots/macos/player.png" alt="Плеер"><br><sub>Плеер</sub></td></tr>
<tr><td width="50%"><img src="screenshots/macos/settings.png" alt="Настройки"><br><sub>Настройки</sub></td><td width="50%"><img src="screenshots/macos/profile.png" alt="Профиль"><br><sub>Профиль</sub></td></tr>
</table>
</details>

---

## Что нового в 2.5.6

- Первоначальный выбор артистов: 20 быстрых карточек с фотографиями и поиск за пределами этого списка.
- Отдельная «Моя волна» на главной: подборка от 60 треков при достаточной выдаче источников, с учётом выбранных артистов, истории, длительности прослушиваний и лайков. Выбор трека переключает очередь на волну.
- Исправления поиска артистов, фотографий, биографий, каталогов и сопоставления ремиксов.
- Автоподбор стратегий Zapret при первом включении, прогресс и отмена; исправления запуска, остановки и обновления.
- Обновлённые настройки, уведомления, выпадающий список стратегий и центрирование свёрнутой боковой панели.

[Описание релиза v2.5.6](docs/releases/v2.5.6.md) · [История изменений](CHANGELOG.md)

## Возможности

**Источники**

- Стриминг с YouTube Music и SoundCloud; каталог Apple Music / iTunes с подбором подходящей записи на YouTube. Прямое воспроизведение защищённых потоков Spotify и импорт его плейлистов по ссылке не поддерживаются.
- Офлайн-треки: плейлисты импортируются и качаются на диск
- Чтение тегов из локальных файлов, эквалайзер на 10 полос

**Воспроизведение**

- Тексты песни по строкам, сдвиг синхронизации ±0.5&nbsp;с, перевод
- Визуализатор
- Повтор, перемешивание, перетаскивание треков в очереди
- Мини-плеер поверх других окон
- ⌨ Горячие клавиши — любую можно переназначить

**Интерфейс**

- Темы оформления, можно собрать свою
- Плейлисты: создать и импортировать; экран плейлиста разделяет описание
  и список треков
- Подборки «Для тебя» и ежедневные миксы строятся по истории и предпочтениям;
  состав можно открыть или сразу воспроизвести
- Главная использует обложки из истории прослушивания для фоновой атмосферы
- Пошаговая первоначальная настройка с живым предпросмотром оформления и параметров
- Анимированный переход между обычным окном и мини-плеером
- Discord Rich Presence — статус об играющем треке

---

## Установка

Требуются **Windows 10/11 x64** и интернет для онлайн-источников и подготовки недостающих компонентов.

[Репозиторий](https://github.com/PoviceProgrammer/NeDotify) → **Releases** → **v2.5.6** → **Assets** → **`NeDotify_Setup.exe`**.

1. Откройте [релиз v2.5.6](https://github.com/PoviceProgrammer/NeDotify/releases/tag/v2.5.6).
2. В разделе **Assets** скачайте [NeDotify_Setup.exe](https://github.com/PoviceProgrammer/NeDotify/releases/download/v2.5.6/NeDotify_Setup.exe).
3. Запустите установщик и пройдите шаги мастера. Он устанавливает приложение в профиль пользователя и создаёт выбранные ярлыки.
4. Откройте NeDotify, завершите первоначальную настройку, выберите артистов и запустите трек через поиск или «Мою волну».

При отсутствии WebView2 установщик предложит установить его. Компоненты для обработки аудио подготавливаются приложением; Python и winget для установки не требуются. Архивы **Source code** содержат исходники.

[Подробная инструкция: установка, VPN и первый трек](docs/TUTORIAL_WINDOWS_INSTALL_VPN_PLAYBACK.md).

Собрать самому (имя выходного файла задаёт `OutputBaseFilename` в `installer.iss`):

```powershell
& ".venv_win\Scripts\python.exe" -m pip install -r requirements.txt
& ".venv_win\Scripts\python.exe" -m PyInstaller setup_pyinstaller.spec
iscc installer.iss
```

На выходе — `dist\NeDotify_Setup.exe`.

---

## Запуск из исходников

Для исходников Windows v2.5.6 нужен Python 3.14 x64.

```powershell
git clone --branch v2.5.6 https://github.com/PoviceProgrammer/NeDotify.git
cd NeDotify

python -m venv .venv_win
& ".venv_win\Scripts\python.exe" -m pip install -r requirements.txt
```

Запуск — `python main.py` из корня репозитория, интерпретатором из `.venv_win`:

```powershell
& ".venv_win\Scripts\python.exe" main.py
```

> Системный `python` не подойдёт — в нём нет `pywebview` и `yt-dlp`.
> Нужен именно интерпретатор из `.venv_win`.

Если приложение уже работает, но окно скрыто, откройте NeDotify через значок
в трее. Крестик полностью закрывает приложение и очищает Discord-статус.
Обычное сворачивание сохраняет воспроизведение музыки.

---

## Тесты

```powershell
& ".venv_win\Scripts\python.exe" -m pytest
& ".venv_win\Scripts\python.exe" -m pytest tests\test_build_and_brand.py -q
```

`pytest.ini` по умолчанию исключает тесты с маркером `network`, которым нужен
реальный доступ к площадкам. Для их отдельного запуска передайте `-m network`.
`run_tests.py` использует ту же конфигурацию pytest.

Инструкции для разработки:

- [Тесты — nedotify-test](.claude/skills/nedotify-test/SKILL.md)
- [Запуск и проверка окна — nedotify-run](.claude/skills/nedotify-run/SKILL.md)
- [Сборка EXE и установщика — nedotify-build](.claude/skills/nedotify-build/SKILL.md)
- [Замеры производительности — nedotify-perf](.claude/skills/nedotify-perf/SKILL.md)

Актуальные описания функций и изменений интерфейса собраны в
[STATUS.md](STATUS.md) и тематических заметках:

- [Рекомендации «Для тебя» и ежедневные миксы](docs/recommendations-for-you-20261102.md)
- [Первоначальная настройка и анимации](docs/riff-onboarding.md)
- [Атмосфера главной и Discord Rich Presence](docs/ATMOSPHERE_AND_DISCORD.md)
- [История функций и проверок библиотеки](docs/FEATURES_2026_10_15.md) — датированный
  архив; некоторые пункты могли быть удалены позднее.

---

## Доступ к онлайн-источникам

Если площадка недоступна в вашей сети, приложение может работать через системный
VPN в TUN-режиме. В Happ выберите **TUN → Sing-box**, подключитесь к серверу,
затем повторите поиск в NeDotify. Явный прокси задаётся в настройках приложения.

Встроенный Zapret включается в **Настройки → Zapret (Обход DPI)**. Перед первым
запуском идёт подбор стратегий; дождитесь результата или отмените его.
Доступность источников зависит от сети и региона. [Пошаговая инструкция](docs/TUTORIAL_WINDOWS_INSTALL_VPN_PLAYBACK.md).

<table>
<tr><td>

### TequilaVPN

**VPN для доступа к музыкальным сервисам.**

[Открыть TequilaVPN в Telegram](https://t.me/TequilaVPNbot?start=refugkQUieF)

Реферальная ссылка автора проекта. Сервис предоставляется отдельно от NeDotify.

</td></tr>
</table>

---

## Стек

Python 3.14 · pywebview + WebView2 · SQLite (WAL) · yt-dlp · Vanilla JS

Фронтенд без сборщика и бандлера: правьте `ui/web_new_v2/` и перезапускайте.
Единственный интерфейс **desktop-плеера** — `ui/web_new_v2/`; он включён в
сборку EXE. Выбор других версий удалён.

---

## Лицензия

Проект распространяется по лицензии [MIT](LICENSE).

Уведомления об авторстве и лицензии сторонних компонентов сохранены в [licenses/](licenses/).
