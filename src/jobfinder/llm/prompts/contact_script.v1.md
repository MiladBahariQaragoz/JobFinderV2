# Task

You write the German a foreign student in Bavaria says on the phone when she
asks a local business for casual work, and the short German email she sends when
there is no phone number.

She is a master's student in Bavaria. Her German is limited — roughly A2 — so she
will be **reading these lines aloud**, and she has to understand every word she
says. That is why each line comes with an English gloss.

The business she is calling is described below by its kind. Write for that kind
of place: the work she is offering to do in a bakery is not the work she is
offering to do in a hotel.

# What to return

ONE JSON object of exactly this shape:

```json
{
  "script_lines": [
    { "de": "Guten Tag, mein Name ist Saba.", "en": "Hello, my name is Saba." },
    { "de": "Ich bin Studentin in {city} und suche einen Minijob.", "en": "I am a student in {city} and I am looking for a part-time job." },
    { "de": "Ich kann in der Küche helfen.", "en": "I can help in the kitchen." },
    { "de": "Suchen Sie im Moment Aushilfen?", "en": "Are you looking for helpers at the moment?" },
    { "de": "Darf ich meine Unterlagen vorbeibringen?", "en": "May I bring my documents by?" }
  ],
  "email_subject": "Bewerbung als Aushilfe",
  "email_body": "Guten Tag,\n\nich bin Studentin in {city} und suche einen Minijob bei {place}.\n\n…\n\nMit freundlichen Grüßen\nSaba"
}
```

# Rules

- Exactly **five** `script_lines`, in the order she will say them: greeting and
  name, who she is and what she wants, what she can do, the question, the next
  step.
- Every line needs both `de` and `en`. The `en` is a plain-English gloss of that
  line, not a translation of the whole script.
- Keep each German line **short and sayable** — one clause where possible. She is
  reading it aloud at A2. No subordinate clauses stacked two deep.
- Use **Sie**, never du. This is a stranger and a business.
- `{place}` and `{city}` are placeholders that get filled in per business. Use
  `{city}` in the script where the town belongs. The `email_body` **must**
  contain `{place}` at least once — it is reused for every business of this kind.
- The email is 4–8 short lines: greeting, who she is, what she can do, when she
  is available, a closing. It ends with her first name and nothing else — no
  address, no phone number, no email address.
- Say she is a student looking for a **Minijob or Teilzeit**. Do not invent
  qualifications, experience, or a start date.
- Everything in `de` is German; everything in `en` is English. Do not mix.
- Return the JSON object and nothing else — no fences, no commentary.
