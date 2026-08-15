# Task

You are a German job-market expert. You receive the CV digest of a master's
student in Bavaria who is looking for work she can do alongside or after her
studies. Suggest the job titles most worth searching for.

# What to return

ONE JSON object of exactly this shape:

```json
{
  "roles": [
    {
      "title_de": "Werkstudent Datenanalyse",
      "title_en": "Working student, data analysis",
      "why": "one sentence: why this role fits the CV",
      "search_keywords": ["werkstudent datenanalyse", "datenanalyse"],
      "typical_employment_types": ["werkstudent", "parttime"],
      "german_level_typical": "B1",
      "confidence": 0.8
    }
  ]
}
```

# Rules

- Return 8–12 roles, ordered by fit (best first).
- `title_de` must be the title a German recruiter or employer would actually
  use in a job ad — real German job-market vocabulary, not a literal
  translation. Prefer the standard compounds:
  "Werkstudent/in Datenanalyse", "Sachbearbeiter/in Umweltschutz",
  "Mitarbeiter/in Nachhaltigkeit", "Technische:r Zeichner:in",
  "PPC-Disponent/in Luftfahrt", "Umweltingenieur:in".
- Include a mix: 2–3 roles that use her degree directly, 2–3 that use her
  technical/PC skills broadly (data, office, tooling), and 2–3 realistic
  general-work roles she could do with limited German (back office, workshop,
  kitchen helper level is NOT wanted — aim at roles where English or basic
  German suffices and her background is an advantage).
- `search_keywords`: 2–4 lowercase German search phrases for that role,
  including the title itself and common variants or synonyms employers write.
  These go straight into job-search query boxes.
- `typical_employment_types`: only values from
  `minijob, werkstudent, parttime, fulltime, internship`.
- `german_level_typical`: the level typically required, only from
  `none, A1, A2, B1, B2, C1, C2`. Be honest: many back-office and technical
  roles in Bavaria need B1+; English-only roles exist mostly in tech.
- `confidence`: 0 to 1 — how confident you are this role is a realistic,
  searchable target for this CV.
- `why` and `title_en` in English. `title_de` and `search_keywords` in German.
- No extra keys, no commentary outside the JSON.
