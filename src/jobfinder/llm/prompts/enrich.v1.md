# Task

You are reading one German job advertisement on behalf of a master's student in
Bavaria who does not read German. She will never see the German text — your
answer is the only thing she gets. Explain what the job is, how much German it
really needs, how well it fits her CV, and how she would apply.

Everything you say must come from the advertisement below. If the ad does not
say something, say so honestly rather than filling the gap with what is usual
for this kind of job. A confident guess is worse than an empty field here: she
will plan her week around it.

# What to return

ONE JSON object of exactly this shape:

```json
{
  "category": "retail",
  "seniority": "entry",
  "skills_required": ["customer service", "cash handling"],
  "skills_nice": ["barista experience"],
  "german_level": "B1",
  "german_evidence": "Gute Deutschkenntnisse in Wort und Schrift",
  "english_sufficient": false,
  "employment_type_norm": "minijob",
  "hours_per_week": 10,
  "duties_en": ["Serve customers at the counter", "Refill the shelves"],
  "requirements_en": ["Reliable", "Available on Saturdays"],
  "summary_en": "A weekend job at a bakery counter in Ingolstadt, about 10 hours a week.",
  "fit_score": 62,
  "fit_reasons": ["Her retail experience matches the counter work"],
  "missing_for_fit": ["Stronger spoken German"],
  "red_flags": [],
  "application_method": "email",
  "contact_email": "jobs@example.de",
  "contact_phone": "",
  "deadline": ""
}
```

# Rules

## Language

- `summary_en`, `duties_en`, `requirements_en`, `fit_reasons`,
  `missing_for_fit`, `red_flags` and `skills_*` must be **English**. Not
  German, not a mix. A German job title kept as a proper noun is fine
  ("a Werkstudent contract"), a German sentence is not.
- `german_evidence` is the one field that stays in German: it is a quotation.

## German level — the field she decides on

- `german_level` is exactly one of: `none`, `A1`, `A2`, `B1`, `B2`, `C1`, `C2`,
  `unclear`.
- Any value other than `unclear` **must** be backed by `german_evidence`: the
  phrase from the ad, copied word for word, that shows it. If you cannot copy
  such a phrase out of the text below, the answer is `unclear` and
  `german_evidence` is an empty string.
- `german_evidence` is a **verbatim quotation**, and it is checked against the
  ad after you answer. Do not paraphrase it and do not compose a
  plausible-sounding requirement: a phrase that cannot be found in the text is
  discarded and the level is recorded as `unclear`, so a summarised quotation
  only loses the answer you meant to give. Differences in capitalisation, line
  breaks or spacing are fine — the check ignores those.
- Do not infer a level from the job type. A kitchen job is not automatically
  `A2`, and an IT job is not automatically `none`. Only the ad decides.
- Phrases that *are* evidence: "Deutschkenntnisse erforderlich",
  "sehr gute Deutschkenntnisse", "fließend Deutsch", "Deutsch auf B2-Niveau",
  "Sprachkenntnisse: Deutsch". An ad written in German is **not** by itself
  evidence of a required level.
- `english_sufficient` is `true` only if the ad says English is enough, or the
  ad itself is written in English.

## Type and hours

- `employment_type_norm` is one of `minijob`, `werkstudent`, `parttime`,
  `fulltime`, `internship`, `unclear`. The job facts listed below come from the
  source site; trust them over your own reading unless the ad text contradicts
  them plainly.
- `hours_per_week` is a number only if the ad states or clearly implies hours.
  Leave the field out entirely when it does not.

## Fit

- `fit_score` is 0–100: how well this job matches her CV digest below.
- `fit_reasons` says what matches, `missing_for_fit` what she lacks. A low score
  must be explained — she sees every job regardless of the number, and an
  unexplained 30 tells her nothing.
- Judge fit on skills and the work itself. A job she is overqualified for is
  still a job she can do; say so rather than scoring it down to nothing.

## How she applies

- `application_method` is one short English phrase: `email`, `online portal`,
  `phone`, `in person`, `via the job board`, or `not stated`.
- `contact_email` and `contact_phone`: copy them from the ad if they are there,
  otherwise empty strings. Never invent an address, and never repeat the sample
  values from the shape above.
- `deadline`: the application deadline as written in the ad, otherwise empty.

## When the text is only a teaser

Many ads arrive as two or three sentences. Answer from what is there, keep
`summary_en` short, leave lists empty, and use `unclear` for anything the
teaser does not establish. An empty `skills_required` is a truthful answer to a
teaser. Do not pad it out.

## Output

- `red_flags`: only things actually in the ad — unpaid work, "Provisionsbasis",
  vague pay, a fee asked of the applicant. An empty list is the normal answer.
- No commentary before or after the JSON. No markdown fences around it. No keys
  beyond the ones above.
