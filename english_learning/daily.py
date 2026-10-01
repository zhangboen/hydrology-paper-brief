"""Daily B2 English lesson: generate, validate, archive, and email. Standard library only."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request

CHINA = timezone(timedelta(hours=8))
SCENARIOS = [
    "Introducing yourself to a new colleague", "Ordering coffee and making a small change",
    "Checking into a hotel", "Opening an account at a bank", "Asking about a gym membership",
    "Finding an item and checking out at a supermarket", "Ordering at a restaurant",
    "Making small talk with a neighbor", "Rescheduling a work meeting",
    "Asking for directions and using public transport", "Returning an item to a shop",
    "Booking an appointment by phone", "Asking a colleague for help",
    "Explaining your research to a non-specialist", "Collecting a parcel",
    "Handling a flight delay at the airport", "Viewing an apartment",
    "Giving a short update in a team meeting", "Inviting someone to lunch",
    "Politely raising a problem at a hotel", "Buying a train ticket",
    "Joining a conversation at a conference", "Discussing weekend plans",
    "Clarifying an unfamiliar expression", "Negotiating a realistic deadline",
    "Giving and receiving constructive feedback", "Ordering food for delivery",
    "Introducing a visiting scholar", "Explaining a minor problem at a repair shop",
    "Thanking someone and saying goodbye naturally",
]
GENRES = ["personal diary", "short reflective essay", "original short speech",
          "first-person monologue", "short story", "informal letter",
          "popular-science vignette", "travel journal"]


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


S = {"type": "string"}
STRINGS = {"type": "array", "items": S}
SCHEMA = obj(
    title=S,
    concept=obj(key=S, name_en=S, name_zh=S, explanation_zh=S, examples=STRINGS,
                common_mistake_zh=S),
    vocabulary={"type": "array", "items": obj(
        term=S, ipa_us=S, pronunciation_tip_zh=S, meaning_zh=S,
        explain_in_english=S, usage_note_zh=S, examples=STRINGS)},
    scene=obj(title=S, context_zh=S,
              script_en={"type": "string", "description": "Full natural English dialogue, 140-210 ENGLISH WORDS, around 12-16 substantial speaking turns. Not a brief outline."},
              translation_zh=S, practice_tip_zh=S),
    reading=obj(title=S, genre=S,
                text_en={"type": "string", "description": "Complete original English reading: 220-300 ENGLISH WORDS in 4 developed paragraphs. Do not summarize or stop after one paragraph."},
                summary_zh=S,
                questions={"type": "array", "items": obj(question=S, answer=S)}),
)
SYSTEM = """You are an expert English-language teacher writing natural, idiomatic American
English for a Chinese-speaking adult at IELTS 6.5 (B2). Help the learner speak with
confidence in real daily and professional situations, not memorize exam jargon.
Create one coherent, engaging daily lesson with EXACTLY these four parts:
1. ONE practical English communication concept. Give an English canonical key,
English and Chinese names, a clear Chinese explanation, 2-3 natural English
examples, and one common mistake with a correction. Prefer pragmatics, usage,
collocations, conversational strategies, or a focused grammar distinction.
2. EXACTLY THREE new useful words or phrases widely used by native speakers.
Each needs accurate General American IPA inside /slashes/, a Chinese pronunciation
tip (stress/linking; no Chinese phonetic transliterations), Chinese meaning, a
simple English explanation the learner can SAY to another person, TWO natural
English examples, and a Chinese note on register/context. Avoid obscure slang,
regional expressions without labels, basic A1 words, and dictionary-style circular
definitions. If unsure of a pronunciation, choose a more familiar expression.
3. ONE realistic scene for memorization: 140-210 English words, a natural dialogue
with named speaker labels (or a first-person script when appropriate), a brief
Chinese context, full Chinese translation, and one practical memorization tip.
Use a NEW specific situation within the assigned scenario family. No invented
personal facts about the learner. Use editable placeholders when necessary.
4. ONE ORIGINAL reading of 220-300 English words in the assigned genre, with a
title, short Chinese summary, and TWO English comprehension questions with answers.
Never copy or attribute real speeches, copyrighted passages, or unverifiable quotes.
All readings are your original teaching material. Favor interesting human details
over generic motivational cliches. Avoid unsupported news/medical/financial advice.
Reuse today's vocabulary naturally in the scene or reading when it fits. Do not
force awkward phrasing. Keep the teaching friendly and useful in 15-20 minutes.
Do not repeat previously taught concepts (even renamed), vocabulary, scene details,
or reading themes. Return only the JSON specified by the response schema.
"""


def today():
    return datetime.now(CHINA).date().isoformat()


def normalized(value):
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def word_count(value):
    return len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", value))


def validate_shape(value, schema, path="lesson"):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise ValueError(f"{path}: missing or unexpected fields")
        for key, child in schema["properties"].items():
            validate_shape(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected an array")
        for child in value:
            validate_shape(child, schema["items"], path)
    elif not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected non-empty text")


def validate(lesson, history):
    validate_shape(lesson, SCHEMA)
    if len(lesson["vocabulary"]) != 3:
        raise ValueError("Exactly three vocabulary items are required")
    used = {normalized(term) for row in history for term in row["terms"]}
    terms = [normalized(item["term"]) for item in lesson["vocabulary"]]
    if len(set(terms)) != 3 or used.intersection(terms):
        raise ValueError("Vocabulary repeats today's or an earlier lesson's terms")
    concept = lesson["concept"]
    for row in history:
        if (normalized(concept["key"]) == normalized(row["concept_key"])
                or normalized(concept["name_en"]) == normalized(row["concept_name"])):
            raise ValueError("Concept was already taught")
        if normalized(lesson["scene"]["title"]) == normalized(row["scene"]):
            raise ValueError("Scene title repeats an earlier lesson")
        if normalized(lesson["reading"]["title"]) == normalized(row["reading"]):
            raise ValueError("Reading title repeats an earlier lesson")
    if not 2 <= len(concept["examples"]) <= 3:
        raise ValueError("Concept needs 2-3 examples")
    for item in lesson["vocabulary"]:
        if not re.fullmatch(r"/[^/\n]+/", item["ipa_us"].strip()):
            raise ValueError("Provide IPA enclosed in slashes")
        if len(item["examples"]) != 2:
            raise ValueError("Each vocabulary item needs two examples")
    scene_words = word_count(lesson["scene"]["script_en"])
    reading_words = word_count(lesson["reading"]["text_en"])
    length_errors = []
    if not 130 <= scene_words <= 230:
        length_errors.append(f"Scene must contain 140-210 English words; received {scene_words}")
    if not 210 <= reading_words <= 320:
        length_errors.append(f"Reading must contain 220-300 English words; received {reading_words}")
    if length_errors:
        raise ValueError("; ".join(length_errors))
    if len(lesson["reading"]["questions"]) != 2:
        raise ValueError("Reading needs two comprehension questions")


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def persist(state_dir, enabled, message):
    if not enabled:
        return
    def git(*args):
        return subprocess.run(["git", "-C", str(state_dir), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    if git("branch", "--show-current") != "english-learning-state":
        raise RuntimeError("Refusing to persist lesson state on an unexpected branch")
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "history.json", "lessons")
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", message)
        git("push", "origin", "HEAD:english-learning-state")


def generate(history, date, usage_path):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY repository secret")
    model = os.environ.get("ENGLISH_MODEL") or "gpt-4.1-mini"
    n = len(history)
    prompt = {
        "date": date, "level": "IELTS 6.5 / B2", "lesson_number": n + 1,
        "scenario_family": SCENARIOS[n % len(SCENARIOS)],
        "reading_genre": GENRES[n % len(GENRES)],
        "do_not_repeat": [{k: row[k] for k in (
            "concept_key", "concept_name", "terms", "scene", "reading")} for row in history],
    }
    usage = {"model": model, "prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "reasoning_tokens": 0, "attempts": 0}
    last_error = ""
    previous_content = None
    for attempt in range(1, 4):
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
        if previous_content:
            messages.extend([
                {"role": "assistant", "content": previous_content},
                {"role": "user", "content": f"Revise the complete lesson. Validation errors: {last_error}. "
                 "Preserve correct sections, repair errors, and return the entire valid JSON. "
                 "For length errors count ENGLISH WORDS, not characters: aim for 175 scene words and 250 reading words."},
            ])
        request_body = {
            "model": model, "temperature": 0.7, "max_completion_tokens": 6500,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "daily_english_lesson", "strict": True, "schema": SCHEMA}},
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(request_body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            usage["attempts"] = attempt
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
            actual = data.get("usage", {})
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[field] += actual.get(field, 0)
            usage["reasoning_tokens"] += actual.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            write_json(usage_path, usage)
            print("API usage: " + json.dumps(usage), flush=True)
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise ValueError("Model returned an incomplete or refused lesson")
            previous_content = choice["message"]["content"]
            lesson = json.loads(previous_content)
            write_json(usage_path.parent / "last-generated-lesson.json", lesson)
            validate(lesson, history)
            return lesson, usage
        except urllib.error.HTTPError as error:
            # Do not print response bodies or request headers containing credentials.
            if error.code not in (408, 429) and error.code < 500:
                raise RuntimeError(f"OpenAI HTTP {error.code}; check API key, model access and balance") from None
            last_error = f"OpenAI HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as error:
            last_error = str(error)[:200]
        print(f"Lesson attempt {attempt}/3 failed: {last_error}", flush=True)
        if attempt < 3:
            time.sleep(5 * attempt)
    raise RuntimeError("Lesson generation failed after three attempts: " + last_error)


def render(lesson, date, number):
    # Render from plain strings; model output cannot introduce HTML or remote assets.
    esc = lambda text: html.escape(text).replace("\n", "<br>")
    plain, blocks = [], []
    def heading(text):
        plain.extend(["", text, ""])
        blocks.append(f'<h2 style="margin:28px 0 12px;color:#00765f;font-size:21px">{esc(text)}</h2>')
    def para(text):
        plain.append(text + "\n")
        blocks.append(f'<p style="margin:10px 0;line-height:1.8">{esc(text)}</p>')
    para(f"Day {number:03d} · {date} · IELTS 6.5 / B2 · 美式英语 · 15–20 分钟")
    para("先朗读，再模仿，最后用自己的经历替换一遍。")
    c = lesson["concept"]
    heading("01 / 今日概念 · " + c["name_en"])
    para(c["name_zh"] + "\n" + c["explanation_zh"])
    for example in c["examples"]:
        para(example)
    para("易错提醒：" + c["common_mistake_zh"])
    heading("02 / 三个自然表达")
    for i, item in enumerate(lesson["vocabulary"], 1):
        para(f'{i}. {item["term"]}  {item["ipa_us"]}')
        para("发音提示：" + item["pronunciation_tip_zh"])
        para("意思：" + item["meaning_zh"])
        para("Explain it in English:\n" + item["explain_in_english"])
        para("使用场合：" + item["usage_note_zh"])
        for example in item["examples"]:
            para(example)
    s = lesson["scene"]
    heading("03 / 场景背诵 · " + s["title"])
    para(s["context_zh"])
    para(s["script_en"])
    para("中文理解：\n" + s["translation_zh"])
    para("背诵练习：" + s["practice_tip_zh"])
    r = lesson["reading"]
    heading("04 / 今日阅读 · " + r["title"])
    para("文体：" + r["genre"] + " · 原创学习材料")
    para(r["text_en"])
    para("中文提要：" + r["summary_zh"])
    para("读后自测（先回答，再看下方答案）：")
    for i, qa in enumerate(r["questions"], 1):
        para(f'{i}. {qa["question"]}')
    para("参考答案：\n" + "\n".join(f'{i}. {q["answer"]}' for i, q in enumerate(r["questions"], 1)))
    para("今日收尾：合上邮件，用英语解释三个新表达，再脱稿复述场景。")
    document = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
                '<body style="margin:0;background:#f3f6f5;color:#203331;font-family:Arial,\'Microsoft YaHei\',sans-serif">'
                '<main style="max-width:680px;margin:auto;padding:28px 22px;background:#fff">'
                '<p style="color:#00765f;letter-spacing:2px;font-size:12px">DAILY ENGLISH LEARNING</p>'
                f'<h1 style="font-size:27px;line-height:1.4">{esc(lesson["title"])}</h1>'
                + "".join(blocks) + '</main></body></html>')
    return "\n".join(plain), document


def smtp_settings():
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "ENGLISH_RECIPIENT")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Missing email configuration: " + ", ".join(missing))
    settings = {name: os.environ[name].strip() for name in required}
    port = int(settings["SMTP_PORT"])
    if port not in (465, 587, 25):
        raise RuntimeError("SMTP_PORT must be 465 (TLS), 587 or 25 (STARTTLS)")
    if not re.fullmatch(r"[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+", settings["ENGLISH_RECIPIENT"]):
        raise RuntimeError("ENGLISH_RECIPIENT must be one valid email address")
    return settings


def connect_smtp(settings):
    for attempt in range(1, 4):
        server = None
        try:
            host, port = settings["SMTP_HOST"], int(settings["SMTP_PORT"])
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=45, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(host, port, timeout=45)
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(settings["SMTP_USER"], settings["SMTP_PASSWORD"])
            return server
        except (OSError, smtplib.SMTPException) as error:
            if server:
                server.close()
            if isinstance(error, smtplib.SMTPAuthenticationError):
                raise RuntimeError("SMTP authentication failed; check SMTP_USER and SMTP_PASSWORD/app password") from None
            if attempt == 3:
                raise RuntimeError(f"SMTP connection failed after three attempts ({type(error).__name__})") from None
            time.sleep(5 * attempt)


def send(state, record, output, persist_enabled):
    if record["status"] == "sent":
        print("Today's lesson was already accepted by the mail server; skipping.")
        return
    if record["status"] in ("sending", "delivery_uncertain"):
        raise RuntimeError("Previous delivery is uncertain. Check the mailbox before manually resetting status to prepared.")
    settings = smtp_settings()
    text, document = render(record["lesson"], record["date"], record["number"])
    message = EmailMessage()
    message["From"] = settings["SMTP_USER"]
    message["To"] = settings["ENGLISH_RECIPIENT"]
    message["Subject"] = f'Daily English | {record["date"]} | {record["lesson"]["title"]}'
    message["Date"] = format_datetime(datetime.now(CHINA))
    identity = hashlib.sha256((os.getenv("GITHUB_REPOSITORY", "daily-english") + record["date"]
                               + settings["ENGLISH_RECIPIENT"]).encode()).hexdigest()[:24]
    domain = settings["SMTP_USER"].rsplit("@", 1)[-1]
    message["Message-ID"] = f"<english-{identity}@{domain}>"
    message.set_content(text)
    message.add_alternative(document, subtype="html")
    server = connect_smtp(settings)
    path = state / "lessons" / (record["date"] + ".json")
    try:
        record["status"] = "sending"
        write_json(path, record)
        # Persist intent BEFORE DATA: an interrupted run cannot silently duplicate email.
        persist(state, persist_enabled, "Mark English lesson delivery in progress")
        try:
            server.send_message(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
            record["status"] = "prepared"  # Explicit rejection: safe to retry later.
            write_json(path, record)
            persist(state, persist_enabled, "Record rejected English email delivery")
            raise RuntimeError("SMTP explicitly rejected the email; check sender/recipient permissions") from None
        except (OSError, smtplib.SMTPException):
            record["status"] = "delivery_uncertain"
            write_json(path, record)
            persist(state, persist_enabled, "Record uncertain English email delivery")
            raise RuntimeError("SMTP connection broke during submission; verify inbox before resending") from None
        record["status"] = "sent"
        record["accepted_at"] = datetime.now(CHINA).isoformat()
        write_json(path, record)
        persist(state, persist_enabled, "Record successful English lesson delivery")
        print("SMTP server accepted today's English lesson for delivery.", flush=True)
    finally:
        # QUIT failure must not turn a successful DATA acknowledgement into a resend.
        server.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "send"))
    parser.add_argument("--state-dir", type=Path, default=Path("english-state"))
    parser.add_argument("--output-dir", type=Path, default=Path("english-output"))
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--date", default=today())
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y-%m-%d")
    if args.preview and (args.persist or args.mode == "send"):
        parser.error("Preview must not persist state or send email")
    state, output = args.state_dir, args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    history_path = state / "history.json"
    history = read_json(history_path, [])
    path = state / "lessons" / (args.date + ".json")
    record = read_json(path)
    if args.mode == "send":
        if record is None:
            raise RuntimeError("No prepared lesson for this date")
        send(state, record, output, args.persist)
        write_json(output / "lesson.json", record)
    else:
        if record is None:
            if not args.preview:
                smtp_settings()  # Fail on missing settings before spending model tokens.
            lesson, usage = generate(history, args.date, output / "usage.json")
            record = {"date": args.date, "number": len(history) + 1, "status": "prepared",
                      "lesson": lesson, "usage": usage}
            row = {"date": args.date, "concept_key": lesson["concept"]["key"],
                   "concept_name": lesson["concept"]["name_en"],
                   "terms": [v["term"] for v in lesson["vocabulary"]],
                   "scene": lesson["scene"]["title"], "reading": lesson["reading"]["title"]}
            if not args.preview:
                write_json(path, record)
                write_json(history_path, history + [row])
                persist(state, args.persist, "Archive prepared English lesson " + args.date)
        else:
            print("Reusing saved lesson; no model call is needed.")
        text, document = render(record["lesson"], args.date, record["number"])
        (output / "lesson.txt").write_text(text, encoding="utf-8")
        (output / "lesson.html").write_text(document, encoding="utf-8")
        write_json(output / "lesson.json", record)
        write_json(output / "usage.json", record["usage"])
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f'### Daily English · {args.date}\n\n'
                          f'- Status: {record["status"]}' + (' (preview only)' if args.preview else '') + '\n'
                          f'- Model: {record["usage"]["model"]}\n'
                          f'- Generation token total: {record["usage"]["total_tokens"]}\n'
                          '- Email acceptance confirms SMTP submission, not inbox placement.\n')


if __name__ == "__main__":
    main()
