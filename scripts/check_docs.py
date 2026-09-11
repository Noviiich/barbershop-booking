"""DOC-01: validate documentation structure and traceability."""

import re
from pathlib import Path


def main() -> None:
    root = Path.cwd()
    required = [
        "AGENTS.md",
        "docs/product/requirements.md",
        "docs/architecture/overview.md",
        "docs/architecture/domain-model.md",
        "docs/architecture/booking-flow.md",
        "docs/architecture/yandex-integration.md",
        "docs/testing-strategy.md",
        "docs/roadmap.md",
        "docs/adr/README.md",
    ]
    assert all((root / path).is_file() for path in required), "Missing required document"

    adrs = sorted((root / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert [path.name[:4] for path in adrs] == [f"{index:04d}" for index in range(1, 10)]

    files = [root / "AGENTS.md", *sorted((root / "docs").rglob("*.md"))]
    texts: dict[str, str] = {}
    fence = "`" * 3
    for path in files:
        raw = path.read_text(encoding="utf-8")
        assert raw.endswith("\n"), f"{path}: missing final newline"
        assert sum(line.startswith(fence) for line in raw.splitlines()) % 2 == 0, (
            f"{path}: unclosed fence"
        )
        assert not re.search(r"(?m)^(?:<{7}|={7}|>{7})", raw), f"{path}: merge marker"
        assert not any(line.rstrip() != line for line in raw.splitlines()), f"{path}: whitespace"
        body = re.sub(fence + r".*?" + fence, "", raw, flags=re.S)
        texts[path.relative_to(root).as_posix()] = body
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
            if re.match(r"^(?:https?://|mailto:|#)", target):
                continue
            local_target = target.split("#", 1)[0]
            assert (path.parent / local_target).is_file(), f"{path}: broken link {target}"

    for path in adrs:
        body = texts[path.relative_to(root).as_posix()]
        for label in (
            "Статус:",
            "Дата:",
            "## Контекст",
            "## Решение",
            "## Альтернативы",
            "## Последствия",
            "## Проверка",
        ):
            assert label in body, f"{path}: missing {label}"

    roadmap = texts["docs/roadmap.md"]
    steps = re.findall(r"(?ms)^## PR-(\d{2})[^\n]*\n(.*?)(?=^## |\Z)", roadmap)
    assert [number for number, _ in steps] == [f"{index:02d}" for index in range(27)]
    for number, body in steps:
        for label in (
            "Цель:",
            "Изменения:",
            "Acceptance criteria:",
            "Автоматический тест:",
            "Команды:",
            "Зависимости:",
        ):
            assert label in body, f"PR-{number}: missing {label}"
        dependencies = body.split("Зависимости:", 1)[1].split("\n", 1)[0]
        assert all(
            int(dependency) < int(number) for dependency in re.findall(r"PR-(\d{2})", dependencies)
        )

    test_id_pattern = (
        r"(?:DOC|BOOT|MIG|AUTH|CAT|TIME|SCH|DB|AUD|IDEM|TX|CON|AVL|LIFE|MOVE|API|OUT|"
        r"YAN|REC|OBS|SEC|OPS|PERF|REL)-\d{2}"
    )
    registry = set(
        re.findall(
            rf"^\| ({test_id_pattern}) \|",
            texts["docs/testing-strategy.md"],
            re.M,
        )
    )
    used = set(re.findall(test_id_pattern, "\n".join(texts.values())))
    assert used <= registry, f"Unknown test IDs: {used - registry}"

    print(
        f"DOC-01 OK: {len(files)} documents, {len(adrs)} ADR, "
        f"{len(steps)} PR steps, {len(registry)} test families"
    )


if __name__ == "__main__":
    main()
