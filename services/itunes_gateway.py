"""One bounded, cancellable request queue for all iTunes metadata calls."""
import collections
import threading
import time
import requests

from services.base_service import BaseMusicService, normalize_proxy_url


class CatalogueUnavailable(RuntimeError):
    pass


class ITunesGateway(BaseMusicService):
    _condition = threading.Condition(BaseMusicService._cache_lock)
    _recent = collections.deque()
    _next_at = 0.0
    _active = False
    _entries = collections.OrderedDict()
    _flights = {}
    INTERVAL = .1
    PER_MINUTE = 18
    _session_local = threading.local()

    @classmethod
    def get(cls, url, session=None, timeout=4.0, deadline=None, is_current=None, settings=None):
        deadline = deadline if deadline is not None else time.monotonic() + 5.5
        if session is None:
            session = getattr(cls._session_local, 'session', None)
            if session is None:
                session = requests.Session()
                cls._session_local.session = session
            proxy = normalize_proxy_url(settings.get('auth', 'proxy_url', '')) if settings else ''
            session.proxies = {'http': proxy, 'https': proxy} if proxy else {}
        flight_key = (url, id(is_current)) if is_current is not None else url
        is_current = is_current or (lambda: True)
        with cls._condition:
            hit = cls._entries.get(url)
            if hit and hit[0] > time.monotonic():
                cls._entries.move_to_end(url)
                return hit[1]
            if hit:
                cls._entries.pop(url, None)
            flight = cls._flights.get(flight_key)
            owner = flight is None
            if owner:
                flight = {'event': threading.Event()}
                cls._flights[flight_key] = flight
        if not owner:
            while not flight['event'].wait(min(0.1, max(0.0, deadline - time.monotonic()))):
                if time.monotonic() >= deadline or not is_current():
                    raise CatalogueUnavailable('Запрос устарел или истёк срок ожидания каталога')
            if 'error' in flight:
                raise CatalogueUnavailable(str(flight['error']))
            return flight['data']
        acquired = False
        try:
            with cls._condition:
                while True:
                    now = time.monotonic()
                    while cls._recent and now - cls._recent[0] >= 60:
                        cls._recent.popleft()
                    if now >= deadline or not is_current():
                        raise CatalogueUnavailable('Запрос устарел или истёк срок ожидания каталога')
                    if not cls._active and now >= cls._next_at and len(cls._recent) < cls.PER_MINUTE:
                        cls._active = True
                        acquired = True
                        cls._recent.append(now)
                        cls._next_at = now + cls.INTERVAL
                        break
                    cls._condition.wait(min(0.1, deadline - now))
            response = session.get(url, timeout=min(timeout, max(0.05, deadline - time.monotonic())))
            if response.status_code != 200:
                if response.status_code == 429:
                    try:
                        retry = min(60.0, max(3.5, float(response.headers.get('Retry-After', 30))))
                    except (ValueError, TypeError):
                        retry = 30.0
                    with cls._condition:
                        cls._next_at = max(cls._next_at, time.monotonic() + retry)
                raise CatalogueUnavailable(f'iTunes HTTP {response.status_code}')
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('results'), list):
                raise CatalogueUnavailable('Некорректный ответ iTunes')
            with cls._condition:
                cls._entries[url] = (time.monotonic() + (900 if data['results'] else 60), data)
                cls._entries.move_to_end(url)
                while len(cls._entries) > 500:
                    cls._entries.popitem(last=False)
            flight['data'] = data
            return data
        except Exception as exc:
            flight['error'] = str(exc)
            raise CatalogueUnavailable(str(exc)) from exc
        finally:
            with cls._condition:
                if acquired:
                    cls._active = False
                cls._flights.pop(flight_key, None)
                flight['event'].set()
                cls._condition.notify_all()
