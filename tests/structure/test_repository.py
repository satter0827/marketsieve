from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_license_copies_match() -> None:
    root_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
    package_license = (ROOT / "packages" / "core" / "LICENSE").read_text(encoding="utf-8")

    assert package_license == root_license


def test_readmes_show_the_same_commands() -> None:
    commands = (
        "uv sync --locked",
        "uv run marketsieve --version",
        "uv run marketsieve doctor",
        "uv build --package marketsieve",
        "uv run pytest",
    )
    readmes = (
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.ja.md").read_text(encoding="utf-8"),
    )

    for command in commands:
        assert all(command in readme for readme in readmes)
