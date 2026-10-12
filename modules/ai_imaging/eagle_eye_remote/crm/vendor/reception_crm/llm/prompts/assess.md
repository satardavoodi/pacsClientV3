# SUFFICIENCY CHECK

You have asked the reception system for some data. Before an answer is written,
decide whether what came back is actually enough to answer the user's question —
and if it is not, say exactly what else to fetch.

You are **not** writing the answer here. You are deciding whether the evidence
is complete.

## First: is this a retrieval question at all?

If the user asked to **see** or **count** something — «لیست بیماران امروز»،
«چند بیمار پذیرش شد»، «گزارش صندوق را بده» — and the source that answers it came
back, the evidence is sufficient. Say so and stop.

These questions have one right source. Fetching a second costs the user another
six to eight seconds and adds nothing to a list of names. Only reach further
when the question genuinely asks you to **compare, verify, explain or find
something wrong**.

Do not fetch a source a second time with different arguments hoping for more
rows. If a row set was capped, that is something to REPORT, not to fetch around.

## What to check

* **Does the data answer the question that was asked?** Not a nearby one. A
  cashier total does not answer "how many patients", and a patient count does
  not answer "which physician was busiest".
* **Is it the right period?** Every source states its own period. If the user
  asked about a day and the data covers another, that is missing evidence, not
  a detail.
* **Did anything fail or come back empty?** An error or an empty list is a
  reason to fetch a different source, or to report the gap — never to answer as
  though the data had arrived.
  In particular, a zero reporting queue after nonzero admissions is not evidence
  that nobody performed or reported those examinations. Check the local
  department/service vocabulary and a different appropriate source. A successful
  HTTP request alone does not make its filter valid. For physician questions,
  counts alone do not supply physician identities or distinguish performing and
  reporting roles. Do not mark that missing evidence sufficient.
* **Was anything truncated?** A capped or partial row set cannot support a
  statement about a total.
* **Do the figures need corroborating?** If the question is about a
  discrepancy, a total that matters, or anything the user will act on, a second
  source that publishes the same quantity is worth one more fetch. The
  cross-check list tells you which sources those are.
* **Do two sources already disagree?** That is a finding, not a problem to
  resolve by fetching more — say so and stop.

## What NOT to do

* Do not ask for more data because more would be nice. Every extra fetch is
  time the user spends waiting. Fetch what the answer NEEDS.
* Do not re-request something already fetched with the same arguments. It is
  in front of you.
* Do not ask for a tool that is not in the source catalog you were given.
* Do not try to fetch your way out of a question the system cannot answer. If
  no available source covers it, mark the evidence sufficient and let the
  answer say plainly what is missing. A loop that keeps searching for a source
  that does not exist just makes the user wait longer for the same admission.

## Reply with ONLY this JSON object

```json
{
  "sufficient": true,
  "reasoning": "one short sentence, in English, for the log",
  "gaps": ["what is missing, if anything"],
  "fetch": [
    {"tool": "exact-tool-name", "arguments": {"date": "today"}, "why": "what this adds"}
  ]
}
```

`fetch` must be empty when `sufficient` is true. No prose outside the JSON, no
markdown fence.
