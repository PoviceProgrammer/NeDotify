<p align="center">
  <img src="cover.png" width="230" style="border-radius: 18px;" alt="NeDotify">
  <h1>NeDotify</h1>
  <p><b>Локальный аудиоплеер для Windows.</b><br>
  Стриминг с YouTube Music, Spotify и SoundCloud — синхронные тексты песен,
  эквалайзер, визуализатор и 22 темы оформления.</p>
  <p>
    <img src="https://img.shields.io/badge/python-3.14%2B-3776AB?style=flat-square" alt="Python 3.14+">
    <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4?style=flat-square" alt="Windows 10/11">
    <img src="https://img.shields.io/badge/UI-pywebview%20%2B%20WebView2-512BD4?style=flat-square" alt="pywebview + WebView2">
    <img src="https://img.shields.io/badge/UI-Vanilla%20JS%2C%20no%20bundler-cb3837?style=flat-square" alt="Vanilla JS, no bundler">
  </p>
  <p>
    <a href="https://github.com/PoviceProgrammer/NeDotify/releases"><b>⬇ Скачать NeDotify_Setup.exe</b></a>
  </p>
</p>

---

## 📷 Интерфейс

<table>
  <tr>
    <td width="50%" align="center"><img src="screenshots/home.png" alt="Главный экран"><br><sub><b>Главная</b> — недавно прослушано и локальный Last.fm</sub></td>
    <td width="50%" align="center"><img src="screenshots/player.png" alt="Плеер и тексты песен"><br><sub><b>Плеер и тексты</b> — синхронный текст с подстройкой ±0.5 с</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="screenshots/library.png" alt="Библиотека и плейлисты"><br><sub><b>Библиотека</b> — плейлисты, офлайн-треки, импорт</sub></td>
    <td align="center"><img src="screenshots/search.png" alt="Поиск по музыке"><br><sub><b>Поиск</b> — треки, плейлисты, альбомы и артисты</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="screenshots/settings_themes.png" alt="Настройки тем оформления"><br><sub><b>Оформление</b> — 22 пресета и конструктор своей темы</sub></td>
    <td align="center"><img src="screenshots/profile.png" alt="Профиль и статистика"><br><sub><b>Профиль</b> — статистика, топ треков, история</sub></td>
  </tr>
</table>

---

## ✨ Возможности

| Возможность | Где | Детали |
|---|---|---|
| **Стриминг** | Главная, Поиск | YouTube Music, Spotify, SoundCloud, Яндекс.Музыка |
| **Синхронные тексты** | Плеер | Поиск по названию трека, сдвиг ±0.5 с, перевод, работает с ремиксами |
| **Эквалайзер** | Настройки → Аудио | 10 полос, пресеты и ручная настройка |
| **Визуализатор** | Плеер | FFT в реальном времени |
| **Плейлисты** | Библиотека | Импорт, конвертация, офлайн-треки |
| **Темы** | Настройки → Оформление | 22 пресета + конструктор своей темы |
| **Мини-плеер** | Поверх всех окон | Виджет для управления с любого приложения |
| **Статистика** | Профиль | Прослушано, суммарное время, избранное, топ треков |
| **Discord RPC** | Автоматически | Статус воспроизведения в профиле Discord |
| **Горячие клавиши** | Настройки → Клавиши | Полностью переназначаемые |

---

## 🛠 Стек

| Слой | Решение | Почему так |
|---|---|---|
| Оболочка | pywebview 5 + WebView2 | Нативное окно без Electron и его 100 МБ |
| Язык | Python 3.14 | Проверено на 3.14.7 |
| Интерфейс | Vanilla JS, **без сборщика** | Нет `node_modules`, нет бандла, нет шага сборки |
| Аудио | miniaudio, WebAudio API | Декодирование нативно, визуализация в браузере |
| Прокси потока | Bottle на loopback, Range RFC 7233 | Перемотка и частичное воспроизведение |
| Обложки | Pillow | Локальный кэш обложек |
| Упаковка | PyInstaller + Inno Setup | Один установщик, ярлыки на рабочем столе и в «Пуске» |

### Архитектура

```text
core/                 # AppCore, настройки, потокобезопасный _emit
services/             # по модулю на сервис: spotify, soundcloud, youtube, yandex
ui/web_new_v2/        # рабочий интерфейс (v1 скрыт за флагом --ui-v1)
tools/bench/          # замеры старта, idle, атрибуция CPU
tools/visual_guard/   # регресс интерфейса по скриншотам
tests/                # pytest: мост, лейаут, keybind-контракты, прокси
```

**Про мост pywebview.** `_emit` никогда не выполняется на UI-потоке: WinForms-бэкенд
маршалит `evaluate_js` через `Control.Invoke`, и UI-поток ждёт сам себя — окно
виснет. `AppApi._emit` это определяет и передаёт работу потоку `EmitWorker`.
Ветку нельзя удалять, её закрепляет `tests/test_emit_thread_safety.py`.

**Одна общая блокировка на класс.** `BaseMusicService` держит `_search_cache` и
`_stream_cache` под общей `_cache_lock`; `StreamResolver` — `_mem` и `_inflight`
под `self._lock`. Новое поле присоединяется к существующей блокировке класса, а не
открывает вторую.

**Тишина вместо ошибки.** Класс багов, который этот проект лечит: значение
записывается на одной стороне моста под одним именем, а читается на другой под
другим. Например, keybind назывался `mute`, а фронтенд принимает только
`toggle_mute` — значение молча отбрасывалось, и действие падало на дефолт.
`tests/test_keybind_contracts.py` теперь парсит оба файла и падает на расхождении.

---

## 📥 Установка

Готовый инсталлер с автоматическим созданием ярлыков на **рабочем столе** и в меню
**«Пуск»**:

**⬇ [Перейти к загрузке NeDotify_Setup.exe (Releases)](https://github.com/PoviceProgrammer/NeDotify/releases)**

Инсталлер собирается в два шага: `pyinstaller setup_pyinstaller.spec` даёт
`dist\NeDotify.exe`, затем `iscc installer.iss` — `dist\NeDotify_Setup.exe`.

## 🚀 Запуск из исходников

**Требования:** Windows 10/11, Python 3.14 или новее (проверено на 3.14.7).

```bash
git clone https://github.com/PoviceProgrammer/NeDotify.git
cd NeDotify

python -m venv .venv_win
.venv_win\Scripts\python.exe -m pip install -r requirements.txt

.venv_win\Scripts\python.exe main.py
```

> Всегда запускай через интерпретатор из `.venv_win`. Системный Python не имеет
> `pywebview` и `yt-dlp`.

**Тесты:**

```bash
.venv_win\Scripts\python.exe -m pytest
```

---

## 🌐 Доступность внешних сервисов (VPN)

Для бесперебойной работы интеграций со сторонними аудио-сервисами (YouTube Music,
Spotify, SoundCloud и др.) может потребоваться активное VPN-соединение.

> 🔒 **Рекомендуемый и проверенный VPN:**
> [TequilaVPN Bot](https://t.me/TequilaVPNbot?start=refugkQUieF) — быстрый и надёжный сервис.

В логах это выглядит так:

```text
WARNING: Ignoring unusable auth.proxy_url 'http://127.0.0.1:1080'.
Falling back to a direct connection.
```

Своё прокси можно задать в `Настройки → Хранилище` полем `proxy_url` — приложение
проверяет, что это полный URL, и молча игнорирует мусор вместо падения.

---

## 📄 Лицензия

Проект распространяется в учебных и ознакомительных целях.
