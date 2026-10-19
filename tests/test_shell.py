import pytest

from wa import shell


def test_generate_shell_init_rejects_unsupported_shell():
    with pytest.raises(ValueError, match="Unsupported shell"):
        shell.generate_shell_init("fish")


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_generate_shell_init_contains_wa_function(shell_name):
    script = shell.generate_shell_init(shell_name)
    assert "wa() {" in script
    assert "WA_SHELL_PIPE" in script
    assert "command wa" in script


def test_emit_is_a_noop_without_shell_pipe(monkeypatch):
    monkeypatch.delenv("WA_SHELL_PIPE", raising=False)
    shell.emit("cd /somewhere")  # must not raise


def test_emit_appends_to_pipe_file(shell_pipe):
    shell.emit("cd /somewhere")
    shell.emit("export FOO=bar")

    assert shell_pipe.read_text() == "cd /somewhere\nexport FOO=bar\n"


def test_emit_cd_quotes_path(shell_pipe):
    shell.emit_cd("/path with spaces")
    assert shell_pipe.read_text() == "cd '/path with spaces'\n"


def test_emit_export_quotes_value(shell_pipe):
    shell.emit_export("GREETING", "hello world")
    assert shell_pipe.read_text() == "export GREETING='hello world'\n"


def test_quote_handles_embedded_single_quotes():
    assert shell.quote("it's here") == "'it'\\''s here'"
