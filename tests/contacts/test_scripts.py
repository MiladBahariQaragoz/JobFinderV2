"""The German she reads down the phone, and the German she sends.

This is the part of the phase that only a model can write, and the part that has
to be *right* in a way nothing else here does: she is going to say these words
out loud to a stranger, in a language she is at A2 in. So every line carries an
English gloss underneath — she has to know what she just said.

**One script per kind of place, not one per place.** MASTER_PLAN asked for
per-place. Measured against her real list that is 34 calls in Neuburg alone to
produce 34 texts differing only in a name, and the free-tier quota is the
constraint this whole project is built around. Per kind is 8 calls, cached, with
the name and city substituted at render time.
"""

from __future__ import annotations

import pytest
from tests.fakes import FakePool

from jobfinder.config import Settings
from jobfinder.contacts.scripts import (
    ScriptError,
    render_email,
    render_script,
    write_texts_for_kinds,
)
from jobfinder.sources.overpass import Place

SCRIPT_ANSWER = {
    "script_lines": [
        {"de": "Guten Tag, mein Name ist Saba.", "en": "Hello, my name is Saba."},
        {
            "de": "Ich bin Studentin in Neuburg und suche einen Minijob.",
            "en": "I am a student in Neuburg and I am looking for a part-time job.",
        },
        {
            "de": "Ich kann in der Küche oder beim Abwasch helfen.",
            "en": "I can help in the kitchen or with the washing up.",
        },
        {
            "de": "Suchen Sie im Moment Aushilfen?",
            "en": "Are you looking for helpers at the moment?",
        },
        {
            "de": "Darf ich meine Unterlagen vorbeibringen?",
            "en": "May I bring my documents by?",
        },
    ],
    "email_subject": "Bewerbung als Aushilfe",
    "email_body": (
        "Guten Tag,\n\nich bin Studentin in {city} und suche einen Minijob bei "
        "{place}.\n\nIch kann nachmittags und am Wochenende arbeiten.\n\n"
        "Mit freundlichen Grüßen\nSaba"
    ),
}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(project_root=tmp_path)


def place(kind="bakery", name="Bäckerei Müller & Söhne", city="Neuburg an der Donau") -> Place:
    return Place(
        contact_id="node/1",
        name=name,
        kind=kind,
        city=city,
        phone="+498431648595",
    )


class TestTheScriptItself:
    def test_a_script_is_five_lines_of_german_each_with_an_english_gloss(self, settings):
        pool = FakePool([SCRIPT_ANSWER])

        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        lines = texts["bakery"].script_lines
        assert len(lines) == 5
        assert all(line.de and line.en for line in lines)

    def test_a_rendered_script_names_the_place_and_the_city(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        rendered = render_script(texts["bakery"], place())

        assert "Bäckerei Müller & Söhne" in rendered
        assert "Neuburg an der Donau" in rendered

    def test_a_rendered_script_keeps_every_english_gloss(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        rendered = render_script(texts["bakery"], place())

        assert "Hello, my name is Saba." in rendered
        assert "washing up" in rendered

    def test_the_prompt_says_she_is_a_student_looking_for_a_minijob(self, settings):
        pool = FakePool([SCRIPT_ANSWER])

        write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        sent = pool.calls[0].lower()
        assert "student" in sent
        assert "minijob" in sent or "part-time" in sent

    def test_only_her_first_name_is_sent(self, settings):
        """Her surname, address, phone and email stay on the laptop — the same
        line the CV digest holds (§ Cross-cutting concerns)."""
        pool = FakePool([SCRIPT_ANSWER])

        write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        sent = pool.calls[0]
        assert "Saba" in sent
        assert "Aghakhani" not in sent
        assert "@" not in sent


class TestTheEmailDraft:
    def test_a_rendered_email_names_the_place_and_her_availability(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        subject, body = render_email(texts["bakery"], place())

        assert "Bäckerei Müller & Söhne" in body
        assert "Neuburg an der Donau" in body
        assert "Wochenende" in body or "nachmittags" in body

    def test_an_email_has_a_subject_and_a_greeting(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        subject, body = render_email(texts["bakery"], place())

        assert subject.strip()
        assert body.strip().startswith("Guten Tag")

    def test_an_email_ends_with_her_first_name(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        _subject, body = render_email(texts["bakery"], place())

        assert body.strip().endswith("Saba")


class TestWhatItSpends:
    def test_one_call_per_kind_is_made_not_one_per_place(self, settings):
        pool = FakePool([SCRIPT_ANSWER, SCRIPT_ANSWER])

        write_texts_for_kinds(settings, pool, kinds=("bakery", "hotel"), first_name="Saba")

        assert len(pool.calls) == 2

    def test_a_second_place_of_the_same_kind_spends_no_call(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        texts = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        first = render_script(texts["bakery"], place(name="Bäckerei Eins"))
        second = render_script(texts["bakery"], place(name="Bäckerei Zwei"))

        assert len(pool.calls) == 1
        assert "Bäckerei Eins" in first and "Bäckerei Zwei" in second

    def test_asking_twice_for_the_same_kind_is_served_from_the_cache(self, settings):
        pool = FakePool([SCRIPT_ANSWER])
        write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        again = write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        assert len(pool.calls) == 1  # the second pass asked nothing
        assert again["bakery"].script_lines


class TestWhenTheModelIsNoHelp:
    def test_a_script_with_too_few_lines_is_refused(self, settings):
        broken = dict(SCRIPT_ANSWER, script_lines=SCRIPT_ANSWER["script_lines"][:2])
        pool = FakePool([broken])

        with pytest.raises(ScriptError) as refused:
            write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        assert "line" in str(refused.value).lower()

    def test_a_line_with_no_english_gloss_is_refused(self, settings):
        lines = [dict(line) for line in SCRIPT_ANSWER["script_lines"]]
        lines[2]["en"] = ""
        pool = FakePool([dict(SCRIPT_ANSWER, script_lines=lines)])

        with pytest.raises(ScriptError):
            write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

    def test_an_email_body_without_the_place_placeholder_is_refused(self, settings):
        """The body is reused for every place of a kind, so it has to have
        somewhere to put the name — otherwise she sends a letter to nobody."""
        pool = FakePool([dict(SCRIPT_ANSWER, email_body="Guten Tag,\n\nSaba")])

        with pytest.raises(ScriptError):
            write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

    def test_a_refused_kind_is_not_stored(self, settings):
        pool = FakePool([dict(SCRIPT_ANSWER, script_lines=[])])

        with pytest.raises(ScriptError):
            write_texts_for_kinds(settings, pool, kinds=("bakery",), first_name="Saba")

        pool_again = FakePool([SCRIPT_ANSWER])
        write_texts_for_kinds(settings, pool_again, kinds=("bakery",), first_name="Saba")
        assert len(pool_again.calls) == 1  # nothing usable was cached the first time

    def test_a_spent_quota_keeps_the_kinds_already_written(self, settings):
        from llmpool import PoolExhausted

        pool = FakePool([SCRIPT_ANSWER, PoolExhausted("no providers left")])

        texts = write_texts_for_kinds(
            settings, pool, kinds=("bakery", "hotel"), first_name="Saba", stop_on_exhausted=True
        )

        assert "bakery" in texts
        assert "hotel" not in texts
