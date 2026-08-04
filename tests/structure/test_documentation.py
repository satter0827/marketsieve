from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
DESIGN = DOCS / "design"
NOTES = DOCS / "notes"

DESIGN_DOCUMENTS = {
    "README.md",
    "architecture.md",
    "domain.md",
    "interfaces.md",
    "lifecycle.md",
    "operations.md",
    "quality.md",
    "requirements.md",
}
NOTE_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def test_documentation_has_one_formal_design_tree() -> None:
    assert (DOCS / "README.md").is_file()
    assert (DOCS / "roadmap.md").is_file()
    assert not (DOCS / "architecture.md").exists()

    design_files = {path.name for path in DESIGN.glob("*.md")}
    assert design_files >= DESIGN_DOCUMENTS


def test_design_index_covers_every_design_document() -> None:
    index = (DESIGN / "README.md").read_text(encoding="utf-8")

    for name in DESIGN_DOCUMENTS - {"README.md"}:
        assert f"({name})" in index


def test_temporary_notes_use_dated_names() -> None:
    invalid = sorted(
        path.name
        for path in NOTES.glob("*.md")
        if path.name != "README.md" and NOTE_NAME.fullmatch(path.name) is None
    )

    assert invalid == []


def test_documentation_local_links_resolve() -> None:
    broken: list[str] = []

    for source in DOCS.rglob("*.md"):
        content = source.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(content):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative_target = target.partition("#")[0]
            if relative_target and not (source.parent / relative_target).resolve().exists():
                broken.append(f"{source.relative_to(ROOT)} -> {target}")

    assert broken == []
