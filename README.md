<p align="center">
  <img src="cover.png" width="190" alt="NeDotify">
</p>

<h1 align="center">NeDotify</h1>

<p align="center">
  Плеер для Windows. Свои файлы или стриминг с&nbsp;YouTube&nbsp;Music, Spotify,<br>SoundCloud и&nbsp;Яндекс.Музыки.
</p>

<p align="center">
  <a href="https://github.com/PoviceProgrammer/NeDotify/releases">
    <img src="https://img.shields.io/badge/Download-2f6feb?style=for-the-badge&logo=github&logoColor=white" alt="Скачать NeDotify">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.14">
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/version-5.0%20Beta-a855f7?style=flat-square" alt="Версия 5.0 Beta">
  <img src="https://github.com/PoviceProgrammer/NeDotify/actions/workflows/ci.yml/badge.svg" alt="CI">
</p>

---

## 📸 Скриншоты

<table>
  <tr>
    <td width="50%" align="center"><img src="screenshots/home.png" alt="Главная"><br><sub><b>Главная</b> — недавние треки и локальный топ</sub></td>
    <td width="50%" align="center"><img src="screenshots/search.png" alt="Поиск"><br><sub><b>Поиск</b> — треки, плейлисты, альбомы, артисты</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="screenshots/player.png" alt="Плеер"><br><sub><b>Плеер</b> — обложка, управление, текст песни со сдвигом ±0.5&nbsp;с</sub></td>
    <td align="center"><img src="screenshots/library.png" alt="Библиотека"><br><sub><b>Библиотека</b> — плейлисты, импорт, офлайн-треки</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="screenshots/settings_themes.png" alt="Темы"><br><sub><b>Темы</b> — готовые пресеты и свои цвета</sub></td>
    <td align="center"><img src="screenshots/profile.png" alt="Профиль"><br><sub><b>Профиль</b> — сколько послушал, топ треков, история</sub></td>
  </tr>
</table>

---

## ✨ Возможности

**Источники**

- 🎧 Стриминг с YouTube Music, Spotify, SoundCloud и Яндекс.Музыки
- 📥 Офлайн-треки: плейлисты импортируются и качаются на диск
- 🎼 Чтение тегов из локальных файлов, эквалайзер на 10 полос

**Воспроизведение**

- 🎤 Тексты песни по строкам, сдвиг синхронизации ±0.5&nbsp;с, перевод
- 📊 Визуализатор
- 🔁 Повтор, перемешивание, перетаскивание треков в очереди
- 🪟 Мини-плеер поверх других окон
- ⌨️ Горячие клавиши — любую можно переназначить

**Интерфейс**

- 🎨 Темы оформления, можно собрать свою
- 📀 Плейлисты: создать, импортировать, скачать офлайн
- 🕹️ Discord Rich Presence — статус об играющем треке

---

## 📦 Установка

Установщик `.exe` ставит ярлыки на рабочий стол и в меню «Пуск».
Актуальная сборка — **5.0 Beta**, файл `Beta5_Setup.exe` на странице релизов:

**[Скачать на GitHub Releases](https://github.com/PoviceProgrammer/NeDotify/releases)**

Собрать самому (имя выходного файла задаёт `OutputBaseFilename` в `installer.iss`):

```bash
.venv_win\Scripts\python.exe -m pip install -r requirements.txt
.venv_win\Scripts\python.exe -m PyInstaller setup_pyinstaller.spec
iscc installer.iss
```

На выходе — `dist\Beta5_Setup.exe`.

---

## 🧑‍💻 Запуск из исходников

```bash
git clone https://github.com/PoviceProgrammer/NeDotify.git
cd NeDotify

python -m venv .venv_win
.venv_win\Scripts\python.exe -m pip install -r requirements.txt
.venv_win\Scripts\python.exe main.py
```

> Системный `python` не подойдёт — в нём нет `pywebview` и `yt-dlp`.
> Нужен именно интерпретатор из `.venv_win`.

---

## 🧪 Тесты

```bash
.venv_win\Scripts\python.exe -m pytest -m "not network"
```

Флаг `not network` пропускает тесты, которым нужен реальный доступ к площадкам —
так же, как в CI.

---

## 🌐 Если площадки не открываются

YouTube, Spotify и SoundCloud иногда недоступны без VPN. Своё прокси можно
указать в **Настройки → Хранилище**, поле `proxy_url`.

Если нужен готовый вариант: [TequilaVPN](https://t.me/TequilaVPNbot?start=refugkQUieF).

---

## 🛠 Стек

Python 3.14 · pywebview + WebView2 · SQLite (WAL) · yt-dlp · Vanilla JS

Фронтенд без сборщика и бандлера: правьте `ui/web_new_v2/` и перезапускайте.
Ветка `ui/web_new/` — устаревшая версия интерфейса, её изменения никуда не попадают.

---

## 📄 Лицензия

Учебный проект, для ознакомления.
