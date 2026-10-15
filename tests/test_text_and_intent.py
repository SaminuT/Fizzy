import pytest

from fizzy import intent
from fizzy.pointing.match import score
from fizzy.pointing.tags import PointTag, TagFilter, parse_tag, strip_tags
from fizzy.speech.text import sentences, speakable, split_steps
from fizzy.speech.wake import split_wake


@pytest.mark.parametrize("q, target", [
    ("Where is the Save button?", "Save"),
    ("how do i open settings", "settings"),
    ("click on the File menu", "File"),
    ("Fizzy, where is my downloads folder?", "downloads folder"),
])
def test_pointing_questions(q, target):
    assert intent.wants_pointing(q)
    assert intent.target_phrase(q) == target


def test_not_a_pointing_question():
    assert not intent.wants_pointing("what does this paragraph mean")


def test_commands():
    assert intent.is_stop("Stop.")
    assert intent.is_repeat("say that again")
    assert intent.is_next("next step")
    assert not intent.is_next("what comes next in the story about the fox")


def test_tag_split_across_chunks():
    f = TagFilter()
    shown, tags = [], []
    for chunk in ["Click ", "Save {", "{point x=51", '2 y=330 label="Save"}', "} now. {braces} stay."]:
        text, found = f.feed(chunk)
        shown.append(text)
        tags += found
    shown.append(f.flush())
    assert "".join(shown) == "Click Save  now. {braces} stay."
    assert tags == [PointTag(512, 330, 1, "Save")]


def test_bad_tags_are_ignored():
    assert parse_tag("x=2000 y=10") is None
    assert parse_tag("y=10") is None
    assert parse_tag("x=1 y=2 screen=two").screen == 1
    assert strip_tags("a {{point x=1 y=2}}  b") == "a b"


def test_speakable_drops_markup():
    out = speakable("## Title\n**Bold** and `code` [link](http://x)\n```py\nx=1\n```")
    assert "**" not in out and "#" not in out and "http" not in out
    assert "the code is in the panel" in out


def test_sentences_keep_step_numbers():
    assert sentences("1. Open it. 2. Close it.")[:1] == ["1. Open it."]


def test_split_steps():
    intro, steps = split_steps("Do this:\n1. One\n2. Two\n   more on two\n3. Three")
    assert intro == "Do this:"
    assert steps == ["One", "Two\nmore on two", "Three"]


def test_match_prefers_exact_then_words():
    assert score("save", "Save") == 1.0
    assert score("save", "&Save (Ctrl+S)") == 1.0
    assert score("file", "Open the file menu") > 0.75
    assert score("file", "Edited3files") < 0.5


@pytest.mark.parametrize("heard, rest", [
    ("Fizzy.", ""),
    ("Hey Fizzy, what is this error?", "what is this error?"),
    ("fuzzy logic", None),
])
def test_wake_word(heard, rest):
    assert split_wake(heard) == rest
