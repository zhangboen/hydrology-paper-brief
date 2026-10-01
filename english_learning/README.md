# Daily English Learning

An independent `daily-english-learning` GitHub Actions workflow for a Chinese-speaking
IELTS 6.5 / B2 adult. Sends to **zhangben@mail.sysu.edu.cn** at **06:00 Asia/Shanghai**
(`0 22 * * *` UTC). A 06:27 recovery check reuses the same dated lesson and skips
an already accepted email. GitHub schedules can be delayed or dropped under load;
this is not a guaranteed exact-time delivery service.

## Daily email

1. One practical English usage/communication concept, examples and a common mistake.
2. Exactly three useful native-speaker expressions: American IPA, pronunciation tips,
   Chinese meanings, plain-English explanations, register and two examples each.
3. A rotating everyday/workplace scenario, about 140–210 English words, full Chinese
   translation and a memorization tip. Covers introductions, coffee, hotels, banking,
   gyms, supermarkets, restaurants, colleagues, travel and more.
4. An original 220–300-word reading, rotating genres, with a short Chinese summary
   and two comprehension questions and answers. Real speeches are not reproduced.

Uses `gpt-4o-mini` by default; the repository variable `ENGLISH_MODEL` can override
it with a compatible Chat Completions / strict JSON-schema model. Typical generation
uses one API request. Retries are capped at three total attempts, with 120-second
request timeouts and backoff. Usage returned by all completed attempts is recorded
in the artifact and job summary. Requests that time out may incur unreported usage.

## Configuration

Reuses the existing repository secrets `OPENAI_API_KEY`, `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`. Port 465 uses TLS; 587/25 require STARTTLS. SMTP passwords
may need to be provider-issued app passwords. The recipient is configured separately
in the workflow, so the hydrology brief recipient does not change. No additional
Python packages are needed.

The `english-learning-state` branch stores `history.json` and dated JSON lessons.
Its separate history avoids concurrent commits to the hydrology workflow's main
branch. This repository is public, so lesson content and usage records are public;
SMTP credentials and recipient addresses are not written into state records.

## Operation

- Actions → **daily-english-learning** → **Run workflow** sends today's lesson.
- Check `preview` to generate an artifact without sending or updating history.
- Check `prepare_only` to archive today's lesson for review without sending; a later
  normal run sends that same saved lesson without another model request.
- Rerunning a sent date reuses the saved lesson without another model call or email.
- Exact normalized vocabulary/concept keys and scene/reading titles are checked
  against all saved history; the prompt also asks for semantic variety. Exact-match
  checks do not guarantee the absence of all conceptual overlap.
- SMTP connect/login errors retry three times. Explicit submission rejection leaves
  the lesson prepared for a later retry. Delivery is marked in-progress before
  submitting mail and sent after SMTP acknowledgement.
- A connection break during submission, or a process interruption at that point,
  leaves `delivery_uncertain` or `sending`. Automatic resending is blocked to avoid
  duplicates. Check the recipient's inbox/spam and provider logs first; only if mail
  was not delivered, change that date's status back to `prepared` on the state branch
  and rerun. SMTP acceptance does not prove inbox delivery.
- Preview lessons are not part of history and may differ from the later sent lesson.
- Disable this workflow in Actions to stop daily emails. No Codex app automation is
  needed; the schedule is managed directly by GitHub.

Run local checks with `python -m unittest discover -s english_learning -p 'test_*.py' -v`.
