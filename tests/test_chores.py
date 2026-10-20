from slothcommit import chores
from slothcommit.git import Commit


def test_format_commit_basic():
    msg = chores.format_commit(
        {"type": "feat", "scope": "cli.py", "subject": "Add --dry-run flag.", "body": ["prints instead of committing"]}
    )
    assert msg == "feat(cli): add --dry-run flag\n\n- prints instead of committing"


def test_format_commit_rejects_unknown_type_and_strips_repeated_prefix():
    msg = chores.format_commit({"type": "yolo", "scope": "", "subject": "fix: handle None", "body": []})
    assert msg == "chore: handle None"


def test_format_commit_keeps_acronyms_and_truncates_header():
    msg = chores.format_commit({"type": "fix", "scope": "", "subject": "API " + "x" * 100, "body": []})
    assert msg.startswith("fix: API")
    assert len(msg) <= 72


def test_format_commit_body_dedup_one_sentence_and_wrap():
    msg = chores.format_commit(
        {
            "type": "fix",
            "scope": "gpa",
            "subject": "guard zero credits",
            "body": ["guard zero credits", "returns 0.0 when credits are zero. This avoids a crash.", "- " + "word " * 30],
        }
    )
    lines = msg.splitlines()
    assert "- returns 0.0 when credits are zero" in lines
    assert "guard zero credits" not in msg.split("\n\n", 1)[1]
    assert all(len(line) <= 72 for line in lines)


def test_no_body_flag():
    assert chores.format_commit({"type": "docs", "scope": "readme", "subject": "x y", "body": ["a"]}, with_body=False) == "docs(readme): x y"


def test_forced_type_from_file_list():
    assert chores.forced_type([("M", "README.md"), ("A", "docs/usage.md")]) == "docs"
    assert chores.forced_type([("A", "tests/test_gpa.py")]) == "test"
    assert chores.forced_type([("M", ".github/workflows/ci.yml")]) == "ci"
    assert chores.forced_type([("M", "gpa.py"), ("M", "tests/test_gpa.py")]) is None
    assert chores.forced_type([]) is None
    assert chores.forced_type([("A", "pkg/new_module.py")]) == "feat"
    assert chores.forced_type([("A", "pkg/new.py"), ("M", "pkg/old.py")]) is None


def test_commit_schema_pins_type_when_forced():
    schema = chores.commit_schema([("M", "README.md")])
    assert schema["properties"]["type"]["enum"] == ["docs"]
    # and the shared schema is not mutated
    assert len(chores.COMMIT_SCHEMA["properties"]["type"]["enum"]) == len(chores.COMMIT_TYPES)


def test_build_commit_messages_fewshot_and_hint():
    msgs = chores.build_commit_messages("diff here", [("A", "x.py")], hint="closes #3")
    roles = [m["role"] for m in msgs]
    assert roles[-1] == "user" and roles.count("assistant") == len(chores._FEWSHOT)
    assert "diff here" in msgs[-1]["content"]
    assert "x.py (new file)" in msgs[-1]["content"]
    assert "closes #3" in msgs[-1]["content"]


def _c(sha, subject, ins=1, dels=0, date="2026-10-20"):
    return Commit(sha=sha, date=date, subject=subject, insertions=ins, deletions=dels)


def test_changelog_groups_by_type_in_fixed_order():
    md = chores.changelog_markdown(
        [_c("a1", "fix(io): close file"), _c("b2", "feat: add week report"), _c("c3", "random message")]
    )
    assert md.index("### Features") < md.index("### Bug fixes") < md.index("### Other")
    assert "- **io:** close file (`a1`)" in md
    assert "- random message (`c3`)" in md


def test_week_prompt_languages():
    commits = [_c("a1", "feat: x")]
    assert "first person" in chores.build_week_prompt(commits, "7 days ago", "en").lower()
    assert "简体中文" in chores.build_week_prompt(commits, "7 days ago", "zh")


def test_week_report_with_and_without_summary():
    commits = [_c("a1", "feat: x", 10, 2, "2026-10-19"), _c("b2", "fix: y", 1, 1, "2026-10-20")]
    rep = chores.week_report(commits, {"summary": "I did things."}, "7 days ago")
    assert "2 commits across 2 day(s), +11 / -3 lines" in rep
    assert "I did things." in rep
    rep_zh = chores.week_report(commits, None, "7 days ago", "zh")
    assert "本周小结" in rep_zh and "更新日志" in rep_zh


def test_copied_example_detection_and_fallback():
    assert chores.copied_example({"subject": "Add  install instructions"})
    assert chores.copied_example({"subject": "add timeout and raise errors for http requests"})
    assert not chores.copied_example({"subject": "add gpa calculator"})
    assert not chores.copied_example({"subject": "add install script for windows users"})
    fb = chores.fallback_commit([("A", "pkg/backends.py"), ("A", "pkg/cli.py")])
    assert chores.format_commit(fb) == "feat: add backends.py, cli.py"
    assert chores.commit_schema([("M", "a.py")], allow_body=False)["properties"]["body"]["maxItems"] == 0
    fb = chores.fallback_commit([("M", "README.md")])
    assert chores.format_commit(fb) == "docs: update README.md"
