"""Which places to call first, for someone whose German is limited.

The list is 118 places long in one town. The order it appears in is the order
she will work through it, so the order *is* the product. What she needs first
are the jobs done away from customers — a kitchen, a bakery back room, a hotel's
housekeeping — where the German required is instructions, not conversation.

Deliberately a small readable heuristic and not a model call: it decides row
order, it must be free, and a number she cannot predict is worse than a number
she can argue with.
"""

from __future__ import annotations

from jobfinder.contacts.score import back_of_house_score
from jobfinder.sources.overpass import Place

HER_LANGUAGES = ("persian", "english", "german")


def place(kind: str, **tags) -> Place:
    return Place(
        contact_id=f"node/{abs(hash(kind + str(tags))) % 10000}",
        name=tags.pop("name", "Ein Ort"),
        kind=kind,
        city="Neuburg an der Donau",
        phone=tags.pop("phone", "+498431648595"),
        email=tags.pop("email", None),
        website=tags.pop("website", None),
        tags=tags,
    )


class TestTheKindsSheShouldCallFirst:
    def test_a_bakery_and_a_hotel_outrank_a_bar(self):
        bakery = back_of_house_score(place("bakery"))
        hotel = back_of_house_score(place("hotel"))
        bar = back_of_house_score(place("bar"))

        assert bakery > bar
        assert hotel > bar

    def test_a_restaurant_outranks_counter_service(self):
        """A restaurant has a kitchen with dishwashing and prep in it. A
        fast-food counter is mostly the counter."""
        assert back_of_house_score(place("restaurant")) > back_of_house_score(place("fast_food"))

    def test_a_pub_is_the_least_suitable_kind(self):
        scores = {
            kind: back_of_house_score(place(kind))
            for kind in (
                "restaurant",
                "cafe",
                "fast_food",
                "bar",
                "pub",
                "hotel",
                "bakery",
                "butcher",
                "supermarket",
            )
        }

        assert min(scores, key=scores.get) in {"bar", "pub"}

    def test_every_kind_the_query_returns_has_a_score(self):
        from jobfinder.sources.overpass import TAGS

        for _key, value in TAGS:
            assert back_of_house_score(place(value)) > 0, f"{value} scored nothing"

    def test_an_unknown_kind_still_gets_a_usable_score(self):
        """OSM will grow a tag nobody here anticipated. It belongs at the bottom
        of the list, not off it."""
        assert 0 < back_of_house_score(place("nightclub")) < back_of_house_score(place("bakery"))


class TestWhatNudgesAPlaceUp:
    def test_a_place_with_an_email_scores_above_an_identical_one_without(self):
        """An email is a route she can take without a phone call in German —
        which, at A2, is the difference between applying and not applying."""
        with_email = place("restaurant", email="info@example.de")
        without = place("restaurant")

        assert back_of_house_score(with_email) > back_of_house_score(without)

    def test_a_cuisine_matching_her_languages_is_a_bonus(self):
        persian = place("restaurant", cuisine="persian")
        plain = place("restaurant")

        assert back_of_house_score(persian, languages=HER_LANGUAGES) > back_of_house_score(
            plain, languages=HER_LANGUAGES
        )

    def test_a_cuisine_bonus_is_never_a_requirement(self):
        """A German bakery must not fall below an Italian bar because of a tag —
        the kind of work is the point, the language is a nudge."""
        italian_bar = place("bar", cuisine="italian")
        german_bakery = place("bakery")

        assert back_of_house_score(german_bakery, languages=("italian",)) > back_of_house_score(
            italian_bar, languages=("italian",)
        )

    def test_a_cuisine_she_does_not_speak_is_neither_bonus_nor_penalty(self):
        greek = place("restaurant", cuisine="greek")
        plain = place("restaurant")

        assert back_of_house_score(greek, languages=HER_LANGUAGES) == back_of_house_score(
            plain, languages=HER_LANGUAGES
        )

    def test_a_multi_value_cuisine_tag_is_read_value_by_value(self):
        """OSM writes 'cake;coffee_shop;german' in one field — hers really does."""
        mixed = place("cafe", cuisine="cake;coffee_shop;persian")

        assert back_of_house_score(mixed, languages=HER_LANGUAGES) > back_of_house_score(
            place("cafe"), languages=HER_LANGUAGES
        )


class TestItIsPredictable:
    def test_the_score_is_stable_for_the_same_tags(self):
        first = place("bakery", cuisine="german", email="a@b.de")
        again = place("bakery", cuisine="german", email="a@b.de")

        assert back_of_house_score(first) == back_of_house_score(again)

    def test_the_score_stays_inside_nought_to_one_hundred(self):
        best = place("bakery", cuisine="persian", email="a@b.de")
        worst = place("pub")

        assert 0 <= back_of_house_score(worst) <= 100
        assert 0 <= back_of_house_score(best, languages=HER_LANGUAGES) <= 100

    def test_the_reason_for_a_score_can_be_read_back(self):
        """She should be able to ask why a place is near the top, and the answer
        has to be a sentence rather than a number."""
        from jobfinder.contacts.score import score_reason

        reason = score_reason(place("bakery"))

        assert "bakery" in reason.lower() or "back" in reason.lower()
        assert reason == reason.strip() and reason
