# Roles from a CV (placeholder — real prompt lands in Phase 3)

You receive a CV digest and return job-search roles.

Return ONE JSON object of the exact shape:

```json
{
  "roles": [
    {
      "title_de": "German job title a German recruiter would actually use",
      "title_en": "English translation of the title",
      "why": "one sentence on why this fits the CV",
      "search_keywords": ["lowercase search phrases"],
      "typical_employment_types": ["werkstudent"],
      "german_level_typical": "B1",
      "confidence": 0.8
    }
  ]
}
```

Rules:

- 8–12 roles.
- `typical_employment_types`: only values from
  `minijob, werkstudent, parttime, fulltime, internship`.
- `german_level_typical`: only `none, A1, A2, B1, B2, C1, C2`.
- `confidence`: a number between 0 and 1.
- All summaries and explanations in English; only `title_de` and
  `search_keywords` are German.
