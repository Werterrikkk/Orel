"""Conservatively exclude cross-split near-duplicates, preserving source data."""

import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "data/datasets"
    report = json.loads((directory / "near-duplicates.json").read_text())
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for pair in report["pairs"]:
        left = pair["left_split"], pair["left"]
        right = pair["right_split"], pair["right"]
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    visited = set()
    summary_path = directory / "cleaning-report.json"
    excluded = json.loads(summary_path.read_text())["excluded"] if summary_path.exists() else []
    excluded_ids = {(item["split"], item["name"]) for item in excluded}
    priority = {"train": 0, "val": 1, "test": 2}
    for node in graph:
        if node in visited:
            continue
        component = set()
        queue = [node]
        while queue:
            current = queue.pop()
            if current in component:
                continue
            component.add(current)
            queue.extend(graph[current] - component)
        visited.update(component)
        retained_split = max((split for split, _ in component), key=priority.get)
        for split, name in component:
            if split == retained_split:
                continue
            for kind, filename in (("images", name), ("labels", f"{Path(name).stem}.txt")):
                source = directory / "ppe3" / kind / split / filename
                destination = directory / "excluded-near-duplicates" / kind / split / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    shutil.move(str(source), destination)
            if (split, name) not in excluded_ids:
                excluded.append({"split": split, "name": name})
                excluded_ids.add((split, name))
    summary = {
        "method": report["method"],
        "excluded": excluded,
        "remaining": {
            split: sum(
                path.suffix.lower() in {".jpg", ".jpeg", ".png"}
                for path in (directory / "ppe3/images" / split).iterdir()
            )
            for split in priority
        },
        "limitation": (
            "Conservative similarity filtering. "
            "No original camera/scene identifiers are available; "
            "scene independence is not established."
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    print(
        {
            "excluded": dict(Counter(item["split"] for item in excluded)),
            "remaining": summary["remaining"],
        }
    )


if __name__ == "__main__":
    main()
