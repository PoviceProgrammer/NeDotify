"""S4-004: the artist bio translation must actually run (and fail soft)."""

import time
from types import SimpleNamespace

import pytest

from services.artist_service import ArtistService


class FakeTranslator:
    def __init__(self, monkeypatch, result="Переведённый текст", exc=None):
        self.calls = []
        monkeypatch.setattr(
            "services.lyrics_service.LyricsService",
            lambda settings=None: self,
        )
        self.result = result
        self.exc = exc

    def translate_lyrics(self, text, target_lang="ru"):
        self.calls.append((text, target_lang))
        if self.exc:
            raise self.exc
        return self.result


def test_english_bio_is_translated(monkeypatch):
    fake = FakeTranslator(monkeypatch, result="Русский текст биографии")
    svc = ArtistService(SimpleNamespace(), settings=None)
    bio_ru, bio_original = svc._translate_bio("English biography text")
    assert bio_ru == "Русский текст биографии"
    assert bio_original == "English biography text"
    assert fake.calls == [("English biography text", "ru")]


def test_cyrillic_bio_is_not_retranslated(monkeypatch):
    fake = FakeTranslator(monkeypatch)
    svc = ArtistService(SimpleNamespace(), settings=None)
    bio_ru, bio_original = svc._translate_bio("Уже русская биография")
    assert (bio_ru, bio_original) == ("Уже русская биография", "Уже русская биография")
    assert fake.calls == []


def test_translation_failure_falls_back_to_original(monkeypatch):
    FakeTranslator(monkeypatch, exc=ConnectionError("offline"))
    svc = ArtistService(SimpleNamespace(), settings=None)
    bio_ru, bio_original = svc._translate_bio("English biography text")
    assert (bio_ru, bio_original) == ("English biography text", "English biography text")


def test_empty_translation_result_falls_back(monkeypatch):
    FakeTranslator(monkeypatch, result="   ")
    svc = ArtistService(SimpleNamespace(), settings=None)
    assert svc._translate_bio("English text") == ("English text", "English text")


def test_expired_deadline_refuses_translation(monkeypatch):
    fake = FakeTranslator(monkeypatch)
    svc = ArtistService(SimpleNamespace(), settings=None)
    expired = time.monotonic() - 1
    bio_ru, bio_original = svc._translate_bio("English biography text", deadline=expired)
    assert bio_ru == bio_original == "English biography text"
    assert fake.calls == [], "a deadline that already passed must not call the translator"


def test_live_deadline_allows_translation(monkeypatch):
    fake = FakeTranslator(monkeypatch, result="Русский текст")
    svc = ArtistService(SimpleNamespace(), settings=None)
    bio_ru, _ = svc._translate_bio("English biography text", deadline=time.monotonic() + 5)
    assert bio_ru == "Русский текст"
