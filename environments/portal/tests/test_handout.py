"""The handout's wording lives in config/handout.md — check the loader honours it and
that session values reach the paper escaped."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import handout  # noqa: E402
import views_admin  # noqa: E402

SESSION = {
    "id": "s1",
    "candidate_name": "Ada Lovelace",
    "access_code": "ABCD-1234",
    "terms_text": "Be excellent <to> each other.",
}

VALUES = {"url": "https://x.test/", "access_code": "ABCD-1234",
          "candidate_name": "Ada", "terms": "T&Cs"}


def _with_file(tmp_path, text, monkeypatch):
    p = tmp_path / "handout.md"
    p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(handout, "HANDOUT_FILE", str(p))
    monkeypatch.setattr(handout, "_REPO_FILE", str(tmp_path / "nope.md"))
    return p


def test_repo_config_is_the_shipped_content():
    """The real config/handout.md parses, and its wording is what renders."""
    c = handout.content(VALUES)
    assert c["source"] and c["source"].endswith("handout.md")
    assert c["title"] == "Technical Interview Platform"
    assert "thank you for joining us" in c["lead_html"]
    assert "Getting started" in c["body_html"]
    assert "{" not in c["body_html"]  # every placeholder was expanded


def test_frontmatter_slots_and_block_scalar(tmp_path, monkeypatch):
    _with_file(tmp_path, (
        "---\n# a comment\ntitle: T\nsubtitle: 'S'\nurl_label: Visit\n"
        "notice: |\n  line one\n  line two\n---\n\nhello\n\n## Sec\n\nbody\n"
    ), monkeypatch)
    c = handout.content(VALUES)
    assert (c["title"], c["subtitle"], c["url_label"]) == ("T", "S", "Visit")
    assert c["notice"] == "line one\nline two"
    assert c["code_label"] == handout.DEFAULTS["code_label"]  # unset key falls back
    assert "hello" in c["lead_html"] and "Sec" not in c["lead_html"]
    assert "<h3>Sec</h3>" in c["body_html"]


def test_placeholders_expand_and_escape(tmp_path, monkeypatch):
    _with_file(tmp_path, "## S\n\n{url} {access_code} {candidate_name} {terms} {icon:gemini}\n",
               monkeypatch)
    c = handout.content({**VALUES, "candidate_name": "A<b>&", "terms": "x < y"})
    assert "https://x.test/" in c["body_html"]
    assert "A&lt;b&gt;&amp;" in c["body_html"] and "<b>" not in c["body_html"]
    assert '<span class="terms">x &lt; y</span>' in c["body_html"]
    assert "<svg" in c["body_html"]


def test_unknown_icon_leaves_no_stray_braces(tmp_path, monkeypatch):
    _with_file(tmp_path, "## S\n\n- {icon:nope} a\n- {icon:ide} b\n", monkeypatch)
    body = handout.content(VALUES)["body_html"]
    assert "{icon" not in body
    assert body.count('<li class="ico">') == 2  # bullet is replaced either way


def test_icon_item_text_is_one_flex_child(tmp_path, monkeypatch):
    """`li.ico` is a flex row with `gap`, so every direct child gets a gap beside it and
    text runs stop wrapping as one paragraph. All the text must sit in a single <span>
    — a bullet with two bold phrases used to render as five flex items with four blanks
    scattered through the sentence."""
    _with_file(tmp_path, "## S\n\n- {icon:gemini} **Gemini** — Chat playground **and a\n"
                         "  key already provided** — call it from your own code.\n",
               monkeypatch)
    body = handout.content(VALUES)["body_html"]
    item = re.search(r'<li class="ico">(.*?)</li>', body, re.S).group(1)
    without_icon = re.sub(r"<svg.*?</svg>", "", item, flags=re.S).strip()
    assert without_icon.startswith("<span>") and without_icon.endswith("</span>")
    # both bold phrases, and every word between them, live inside that one span
    inner = without_icon[len("<span>"):-len("</span>")]
    assert "</span>" not in inner and "<span>" not in inner
    assert inner.count("<strong>") == 2
    assert "Chat playground" in inner and "call it from your own code." in inner


def test_missing_file_still_prints_the_essentials(tmp_path, monkeypatch):
    monkeypatch.setattr(handout, "HANDOUT_FILE", str(tmp_path / "gone.md"))
    monkeypatch.setattr(handout, "_REPO_FILE", str(tmp_path / "also-gone.md"))
    c = handout.content(VALUES)
    assert c["source"] is None
    assert c["title"] == handout.DEFAULTS["title"]
    assert "could not be read" in c["lead_html"]
    assert "T&amp;Cs" in c["body_html"]


def test_page_renders_session_values():
    html = views_admin.session_handout(SESSION, "https://interview.test/")
    assert "https://interview.test/" in html
    assert "ABCD-1234" in html
    assert "Be excellent &lt;to&gt; each other." in html
    assert "Ada Lovelace" in html  # <title>
