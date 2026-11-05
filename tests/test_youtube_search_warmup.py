"""First-use visitor headers must not add a homepage request to every Play."""
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property
import logging
import threading

from services.base_service import BaseMusicService
from services.youtube_service import YouTubeService


def test_startup_warmup_and_foreground_search_share_one_visitor_request():
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    visits, results, errors = [], [], []
    class Client:
        @cached_property
        def base_headers(self):
            visits.append(True)
            entered.set()
            assert release.wait(2)
            return {'X-Goog-Visitor-Id': 'public-visitor'}
        def search(self, *args, **kwargs):
            self.base_headers
            return [{'resultType': 'song', 'videoId': 'dQw4w9WgXcQ', 'title': 'Song',
                     'artists': [{'name': 'Artist'}], 'duration': '3:33'}]
    service = YouTubeService.__new__(YouTubeService)
    BaseMusicService.__init__(service)
    service._ytmusic = Client()
    service.logger = logging.getLogger(__name__)
    service.settings = None
    with ThreadPoolExecutor(max_workers=3) as executor:
        service._executor = executor
        warm = service.warm_search()
        assert entered.wait(1)
        service.search('Artist Song', callback=lambda rows: (results.extend(rows), done.set()),
                       error_callback=lambda error: (errors.append(error), done.set()))
        release.set()
        warm.result(timeout=2)
        assert done.wait(2)
    assert visits == [True]
    assert len(results) == 1 and not errors


def test_header_failure_reaches_search_and_can_be_retried():
    attempts = []
    class Client:
        @cached_property
        def base_headers(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise TimeoutError('visitor request failed')
            return {'X-Goog-Visitor-Id': 'public-visitor'}
    service = YouTubeService.__new__(YouTubeService)
    BaseMusicService.__init__(service)
    service._ytmusic = Client()
    try:
        service._prepare_search_headers()
    except TimeoutError:
        pass
    assert service._prepare_search_headers() == {'X-Goog-Visitor-Id': 'public-visitor'}
    assert len(attempts) == 2
