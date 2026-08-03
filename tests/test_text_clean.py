from src.retrieval.text_clean import strip_jira_markup


def test_strips_code_block_with_language_tag():
    text = "Root cause is here.\n{code:java}\npublic void x() { throw new IOException(); }\n{code}\nSee above."
    cleaned = strip_jira_markup(text)
    assert "{code" not in cleaned
    assert "public void x()" not in cleaned
    assert "Root cause is here." in cleaned
    assert "See above." in cleaned


def test_strips_noformat_block():
    text = "Steps:\n{noformat}\nA = load '/etc/passwd';\ndump A;\n{noformat}\nDone."
    cleaned = strip_jira_markup(text)
    assert "{noformat" not in cleaned
    assert "load '/etc/passwd'" not in cleaned
    assert "Steps:" in cleaned
    assert "Done." in cleaned


def test_strips_urls():
    cleaned = strip_jira_markup("See https://issues.apache.org/jira/browse/PIG-1 for details.")
    assert "https://" not in cleaned
    assert "See" in cleaned
    assert "for details." in cleaned


def test_strips_stack_trace_lines():
    text = (
        "It fails with an exception.\n"
        "java.lang.RuntimeException: boom\n"
        "\tat org.apache.pig.Foo.bar(Foo.java:42)\n"
        "Caused by: java.io.IOException\n"
        "\t... 3 more\n"
        "That's the bug."
    )
    cleaned = strip_jira_markup(text)
    assert "\tat org.apache.pig.Foo.bar" not in cleaned
    assert "Caused by:" not in cleaned
    assert "... 3 more" not in cleaned
    assert "It fails with an exception." in cleaned
    assert "That's the bug." in cleaned


def test_empty_and_none_input():
    assert strip_jira_markup(None) == ""
    assert strip_jira_markup("") == ""
    assert strip_jira_markup("   ") == ""
