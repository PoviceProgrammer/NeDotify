<p align="center">
  <img src="cover.png" width="220" alt="NeDotify">
</p>

# NeDotify

Плеер для Windows. Можно слушать свои файлы или стримить с YouTube Music, Spotify, SoundCloud и Яндекс.Музыки. Есть тексты по строкам, эквалайзер, темы и мини-плеер поверх окон.

[Скачать установщик](https://github.com/PoviceProgrammer/NeDotify/releases)

Windows 10/11, Python 3.14.

---

## Скриншоты

**Главная** — недавние треки и локальный топ

![Главная](screenshots/home.png)

**Плеер** — обложка, управление и текст песни. Можно сдвинуть синхронизацию на полсекунды

![Плеер](screenshots/player.png)

**Поиск** — треки, плейлисты, альбомы, артисты

![Поиск](screenshots/search.png)

**Библиотека** — плейлисты, импорт, офлайн-треки

![Библиотека](screenshots/library.png)

**Темы** — готовые пресеты и свои цвета

![Темы](screenshots/settings_themes.png)

**Профиль** — сколько послушал, топ треков, история

![Профиль](screenshots/profile.png)

---

## Что умеет

- Стриминг с YouTube Music, Spotify, SoundCloud и Яндекс.Музыки
- Тексты песен по строкам, сдвиг ±0.5 с, перевод
- Эквалайзер на 10 полос
- Визуализатор
- Плейлисты: создать, импортировать, скачать офлайн
- Темы оформления, можно собрать свою
- Мини-плеер поверх других окон
- Горячие клавиши — все можно переназначить
- Статус в Discord, пока играет трек

---

## Установка

Готовый `.exe` с ярлыками на рабочем столе и в «Пуске»:

**[NeDotify_Setup.exe](https://github.com/PoviceProgrammer/NeDotify/releases)**

Собрать самому: `pyinstaller setup_pyinstaller.spec`, потом `iscc installer.iss`. На выходе `dist\NeDotify_Setup.exe`.

---

## Запуск из исходников

```bash
git clone https://github.com/PoviceProgrammer/NeDotify.git
cd NeDotify

python -m venv .venv_win
.venv_win\Scripts\python.exe -m pip install -r requirements.txt
.venv_win\Scripts\python.exe main.py
```

Системный `python` тут не подойдёт — в нём нет pywebview и yt-dlp. Нужен интерпретатор из `.venv_win`.

Тесты: `.venv_win\Scripts\python.exe -m pytest`

---

## VPN

YouTube / Spotify / SoundCloud иногда не открываются без VPN. Своё прокси можно прописать в **Настройки → Хранилище** (`proxy_url`).

Если нужен готовый вариант: [TequilaVPN](https://t.me/TequilaVPNbot?start=refugkQUieF).

---

## Лицензия

Учебный проект, для ознакомления.
