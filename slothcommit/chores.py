"""The actual chores: commit messages and weekly reports.

Everything that isn't "ask Gemma" lives here as plain, testable Python, so
the model only does the part that genuinely needs language understanding.
"""

from __future__ import annotations

import json
import re
import textwrap
from collections import OrderedDict

from slothcommit.git import Commit

CC_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$")

COMMIT_TYPES = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore"]

COMMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": COMMIT_TYPES},
        "scope": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["type", "scope", "subject", "body"],
}

COMMIT_INSTRUCTIONS = """Write a Conventional Commit for this staged git diff. Describe only what the diff shows.
type: feat (adds new functionality), fix (prevents a crash, error or wrong result), docs (README/comments only), \
test (tests only), refactor (same behaviour, restructured code), perf, style, build, ci, chore.
scope: the main file or module name from the Files line, without extension.
subject: imperative, lowercase, 3-10 words saying WHAT the change does for the user of the code. \
Never write vague subjects like "add new file", "update code" or "add functionality".
body: up to 3 short concrete facts from the diff.
"""

# Two tiny, unrelated examples. A 1B model learns the format far better from
# examples than from rules, and since they never change, llama-server caches them.
_FEWSHOT = [
    (
        [("A", "src/timer.js")],
        """ src/timer.js | 9 +++++++++
@@ -0,0 +1,9 @@
+export function pomodoro(minutes = 25, onDone) {
+  const ms = minutes * 60 * 1000;
+  const id = setTimeout(onDone, ms);
+  return () => clearTimeout(id);
+}""",
        {
            "type": "feat",
            "scope": "timer",
            "subject": "add cancellable pomodoro timer",
            "body": ["pomodoro() defaults to 25 minutes", "returns a function that cancels the timer"],
        },
    ),
    (
        [("M", "README.md")],
        """ README.md | 6 ++++++
@@ -1,3 +1,9 @@
 # weather-bot
+
+## Install
+
+```bash
+pip install -r requirements.txt
+```""",
        {"type": "docs", "scope": "readme", "subject": "add install instructions", "body": []},
    ),
    (
        [("M", "src/http.py")],
        """ src/http.py | 3 ++-
@@ -10,7 +10,8 @@ def fetch(url):
-    resp = requests.get(url)
+    resp = requests.get(url, timeout=10)
+    resp.raise_for_status()
     return resp.json()""",
        {
            "type": "fix",
            "scope": "http",
            "subject": "add request timeout and raise on http errors",
            "body": [
                "requests.get now times out after 10 seconds",
                "non-2xx responses raise instead of returning bad json",
            ],
        },
    ),
]

_STATUS = {"A": "new file", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied"}
DOC_EXT = (".md", ".rst", ".txt", ".adoc")
CI_PREFIXES = (".github/workflows/", ".gitlab-ci", ".circleci/")


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith(("tests/", "test/")) or "/tests/" in path or name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.ts"))


def _is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_EXT) or path.startswith("docs/")


def forced_type(files: list[tuple[str, str]]) -> str | None:
    """When the file list alone settles the commit type, don't let the model guess.

    Returns e.g. "docs" if only Markdown changed. ``None`` means "let Gemma decide".
    """
    paths = [p for _, p in files]
    if not paths:
        return None
    if all(_is_doc(p) for p in paths):
        return "docs"
    if all(_is_test(p) for p in paths):
        return "test"
    if all(p.startswith(CI_PREFIXES) for p in paths):
        return "ci"
    if all(s.startswith("A") for s, _ in files):
        return "feat"  # only brand-new code files: new functionality, not a "fix" or "refactor"
    return None


def describe_files(files: list[tuple[str, str]]) -> str:
    return "Files: " + ", ".join(f"{p} ({_STATUS.get(s[:1], 'changed')})" for s, p in files)


def commit_schema(files: list[tuple[str, str]], allow_body: bool = True) -> dict:
    """The JSON schema Gemma must follow, narrowed by what we already know.

    ``allow_body=False`` (used when a big diff had to be condensed) forbids
    bullet points: with only the outline of the change, a small model's
    "details" are mostly invented.
    """
    schema = json.loads(json.dumps(COMMIT_SCHEMA))
    if not allow_body:
        schema["properties"]["body"]["maxItems"] = 0
    forced = forced_type(files)
    if forced:
        schema["properties"]["type"]["enum"] = [forced]
    return schema


def build_commit_messages(diff: str, files: list[tuple[str, str]], hint: str | None = None) -> list[dict]:
    messages = []
    for ex_files, ex_diff, ex_answer in _FEWSHOT:
        messages.append({"role": "user", "content": f"{COMMIT_INSTRUCTIONS}\n{describe_files(ex_files)}\nDiff:\n{ex_diff}"})
        messages.append({"role": "assistant", "content": json.dumps(ex_answer)})
    hint_line = f"Author's note: {hint}\n" if hint else ""
    messages.append(
        {"role": "user", "content": f"{COMMIT_INSTRUCTIONS}\n{hint_line}{describe_files(files)}\nDiff:\n{diff}"}
    )
    return messages


def copied_example(data: dict, threshold: float = 0.6) -> bool:
    """True if Gemma parroted a few-shot example instead of reading the diff.

    A 1B model does this on big, unfamiliar diffs, sometimes word for word and
    sometimes with a light thesaurus pass ("add timeout and raise errors for
    http requests"). We compare word overlap with each example's subject.
    Better to notice than to commit "add cancellable pomodoro timer" to a repo
    with no timer in it.
    """
    words = set(re.findall(r"[a-z0-9]+", str(data.get("subject", "")).lower()))
    if not words:
        return False
    for ex in _FEWSHOT:
        ex_words = set(re.findall(r"[a-z0-9]+", ex[2]["subject"]))
        if len(words & ex_words) / len(words | ex_words) >= threshold:
            return True
    return False


def fallback_commit(files: list[tuple[str, str]]) -> dict:
    """A boring-but-true message built from the file list alone."""
    added = [p for s, p in files if s.startswith("A")]
    verb = "add" if added and len(added) == len(files) else "update"
    names = [p.rsplit("/", 1)[-1] for _, p in files]
    what = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    ctype = forced_type(files) or ("feat" if verb == "add" else "chore")
    return {"type": ctype, "scope": "", "subject": f"{verb} {what}", "body": []}


def _clean_subject(subject: str) -> str:
    subject = " ".join(subject.split()).strip().rstrip(".")
    # Strip a type prefix the model sometimes repeats inside the subject.
    m = CC_RE.match(subject)
    if m and m.group("type") in COMMIT_TYPES:
        subject = m.group("subject")
    if subject[:1].isupper() and not subject[:2].isupper():  # keep acronyms like "API"
        subject = subject[0].lower() + subject[1:]
    return subject


def _clean_scope(scope: str) -> str:
    scope = (scope or "").strip().lower().rsplit("/", 1)[-1]
    if "." in scope:  # "gpa.py" -> "gpa"
        scope = scope.rsplit(".", 1)[0]
    return re.sub(r"[^a-z0-9_-]", "", scope)[:20]


def format_commit(data: dict, with_body: bool = True, max_header: int = 72) -> str:
    """Turn Gemma's JSON into a valid Conventional Commit message."""
    ctype = data.get("type", "chore")
    if ctype not in COMMIT_TYPES:
        ctype = "chore"
    scope = _clean_scope(data.get("scope", ""))
    subject = _clean_subject(data.get("subject") or "update files")
    header = f"{ctype}({scope}): {subject}" if scope else f"{ctype}: {subject}"
    if len(header) > max_header:
        header = header[: max_header - 1].rstrip() + "…"
    body = []
    seen = {subject.lower()}
    for line in data.get("body") or []:
        line = " ".join(str(line).split()).lstrip("-*• ").strip()
        line = line.split(". ")[0].rstrip(".")  # one fact per bullet, not an essay
        if line and line.lower() not in seen:
            seen.add(line.lower())
            body.append(textwrap.fill(line, width=72, initial_indent="- ", subsequent_indent="  "))
    if with_body and body:
        return header + "\n\n" + "\n".join(body)
    return header


WEEK_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}

# Small models follow instructions far better in the language you want back,
# so each report language gets its own prompt instead of "please answer in X".
WEEK_PROMPTS = {
    "en": """Here are the git commits I made recently ({since}), newest first:

{commits}

Write a short, friendly "what I did this week" update I can paste into a standup or send to my advisor.
First person ("I ..."), 2-4 sentences, mention the main themes rather than every commit.
Do not invent work that is not in the list.""",
    "zh": """下面是我最近（{since}）的 git 提交记录，按时间从新到旧：

{commits}

请用简体中文、第一人称（“我……”）写一段 2-4 句的“本周工作小结”，可以直接发到组会群或发给导师。
概括主要工作方向，不要逐条复述，也不要编造列表里没有的工作。""",
}

REPORT_LABELS = {
    "en": {"title": "What I did", "changelog": "Changelog"},
    "zh": {"title": "本周小结", "changelog": "更新日志"},
}


SECTION_TITLES = OrderedDict(
    [
        ("feat", "Features"),
        ("fix", "Bug fixes"),
        ("perf", "Performance"),
        ("refactor", "Refactoring"),
        ("docs", "Docs"),
        ("test", "Tests"),
        ("build", "Build & CI"),
        ("ci", "Build & CI"),
        ("style", "Style"),
        ("chore", "Chores"),
        ("other", "Other"),
    ]
)


def classify(commit: Commit) -> tuple[str, str]:
    m = CC_RE.match(commit.subject)
    if m and m.group("type") in COMMIT_TYPES:
        scope = m.group("scope")
        text = m.group("subject")
        return m.group("type"), (f"**{scope}:** {text}" if scope else text)
    return "other", commit.subject


def changelog_markdown(commits: list[Commit]) -> str:
    """Deterministic changelog grouped by commit type. No model involved, so no hallucinations."""
    groups: dict[str, list[str]] = OrderedDict()
    for c in commits:
        ctype, text = classify(c)
        title = SECTION_TITLES[ctype]
        groups.setdefault(title, []).append(f"- {text} (`{c.sha}`)")
    ordered = [t for t in dict.fromkeys(SECTION_TITLES.values()) if t in groups]
    parts = []
    for title in ordered:
        parts.append(f"### {title}\n" + "\n".join(groups[title]))
    return "\n\n".join(parts)


def build_week_prompt(commits: list[Commit], since: str, language: str = "en", max_commits: int = 60) -> str:
    lines = [f"- {c.subject}" for c in commits[:max_commits]]
    if len(commits) > max_commits:
        lines.append(f"- ...and {len(commits) - max_commits} older commits")
    template = WEEK_PROMPTS.get(language, WEEK_PROMPTS["en"])
    return template.format(since=since, commits="\n".join(lines))


def stats_line(commits: list[Commit]) -> str:
    ins = sum(c.insertions for c in commits)
    dels = sum(c.deletions for c in commits)
    days = len({c.date for c in commits})
    return f"{len(commits)} commits across {days} day(s), +{ins} / -{dels} lines"


def week_report(commits: list[Commit], data: dict | None, since: str, language: str = "en") -> str:
    labels = REPORT_LABELS.get(language, REPORT_LABELS["en"])
    out = [f"## {labels['title']} (since {since})", "", f"_{stats_line(commits)}_", ""]
    summary = ((data or {}).get("summary") or "").strip()
    if summary:
        out += [summary, ""]
    out += [f"## {labels['changelog']}", "", changelog_markdown(commits)]
    return "\n".join(out).rstrip() + "\n"
