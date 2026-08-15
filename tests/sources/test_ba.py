"""Contract tests for the Bundesagentur adapter — recorded fixtures, never hand-made JSON."""

from __future__ import annotations

from jobfinder.search_spec import SearchSpec


def spec(**overrides) -> SearchSpec:
    parts = dict(
        mode="general",
        employment_types=["minijob"],
        city_names=["Ingolstadt"],
    )
    parts.update(overrides)
    return SearchSpec.build(**parts)


# -- building queries from her spec -------------------------------------------


class TestBuildQueries:
    def test_spec_with_minijob_maps_to_ba_angebotsart_and_arbeitszeit_params(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["minijob"]))
        assert len(queries) == 1
        params = queries[0].params()
        assert params["angebotsart"] == 1  # ARBEIT — verified live
        assert params["arbeitszeit"] == ["mj"]  # minijob — verified live
        assert "was" not in params

    def test_spec_with_three_cities_produces_three_queries_with_correct_umkreis(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(
                city_names=["Neuburg an der Donau", "Ingolstadt", "München"],
                radius_km={"München": 40},
            )
        )
        assert len(queries) == 3
        by_city = {query.params()["wo"]: query for query in queries}
        assert by_city["Neuburg an der Donau"].params()["umkreis"] == 25
        assert by_city["Ingolstadt"].params()["umkreis"] == 25
        assert by_city["München"].params()["umkreis"] == 40

    def test_city_name_is_sent_with_its_umlauts(self):
        # The BA geocoder rejects "Muenchen" silently — canonical names only.
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(city_names=["München"]))
        assert queries[0].params()["wo"] == "München"
        assert "wo=M%C3%BCnchen" in queries[0].url()

    def test_multiple_employment_types_stack_arbeitszeit_codes(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["minijob", "parttime", "fulltime"]))
        assert queries[0].params()["arbeitszeit"] == ["mj", "tz", "vz"]

    def test_werkstudent_has_no_arbeitszeit_code_so_it_rides_in_was(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["werkstudent"]))
        params = queries[0].params()
        assert params["was"] == "Werkstudent"
        assert "arbeitszeit" not in params

    def test_internship_rides_in_was_too(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["internship"]))
        assert queries[0].params()["was"] == "Praktikum"

    def test_her_keywords_become_the_search_term(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(keywords=["umwelttechnik"]))
        assert queries[0].params()["was"] == "umwelttechnik"

    def test_keyword_and_type_keyword_combine(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(employment_types=["werkstudent", "parttime"], keywords=["Datenanalyse"])
        )
        params = queries[0].params()
        assert params["was"] == "Datenanalyse Werkstudent"
        assert params["arbeitszeit"] == ["tz"]

    def test_werkstudent_keyword_from_her_list_is_not_duplicated(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(employment_types=["werkstudent"], keywords=["Werkstudent Umwelt"])
        )
        assert queries[0].params()["was"] == "Werkstudent Umwelt"

    def test_keywords_multiply_into_one_query_per_keyword_per_city(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(city_names=["Ingolstadt", "München"], keywords=["kellner", "küche"])
        )
        assert len(queries) == 4
        terms = {query.params()["was"] for query in queries}
        assert terms == {"kellner", "küche"}

    def test_query_url_carries_the_search_path_and_params(self):
        from jobfinder.sources.ba import build_queries

        query = build_queries(spec())[0]
        url = query.url()
        assert url.startswith("https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?")
        assert "umkreis=25" in url
        assert "page=1" in url
