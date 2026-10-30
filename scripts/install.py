#!/usr/bin/env python3
"""Install repository skills without replacing existing project instructions."""
import argparse
import os
from pathlib import Path
import shutil
import sys

KIT = Path(__file__).resolve().parents[1]
START = "<!-- hackkit:start -->"
END = "<!-- hackkit:end -->"


def merged(path, body):
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if START in old or END in old:
        if old.count(START) != 1 or old.count(END) != 1:
            raise ValueError(f"Invalid installation markers: {path}")
        a, b = old.index(START), old.index(END)
        if b < a:
            raise ValueError(f"Invalid installation markers: {path}")
        return old[:a] + body + old[b + len(END):]
    return old + ("\n\n" if old and not old.endswith("\n\n") else "") + body + "\n"


def install(target):
    target = target.resolve()
    if not target.is_dir():
        raise ValueError(f"Target must be an existing directory: {target}")
    relative = os.path.relpath(KIT, target).replace(os.sep, "/")
    if relative == ".." or relative.startswith("../"):
        raise ValueError("Clone this kit inside the task directory before installing.")
    # Preflight every destination before making changes.
    copies = []
    for source in sorted((KIT / "skills").rglob("*")):
        if not source.is_file():
            continue
        dest = target / ".agents" / "skills" / source.relative_to(KIT / "skills")
        if dest.exists():
            if not dest.is_file() or dest.read_bytes() != source.read_bytes():
                raise ValueError(f"Existing skill differs; resolve manually: {dest}")
        else:
            copies.append((source, dest))
    guide = (
        f"{START}\n## 해커톤 키트\n\n"
        f"작업 전 `{relative}/AGENTS.md`와 `{relative}/CONTEXT.md`를 읽는다.\n"
        "이 과제의 기존 지침과 실제 시험 운영 조건을 우선한다.\n"
        f"스킬 원본과 템플릿은 `{relative}/skills/`, `{relative}/templates/`에 있다.\n"
        "설치된 스킬은 `.agents/skills/`에서 선택해서 읽는다.\n"
        f"{END}"
    )
    updates = {}
    if target != KIT:
        updates[target / "AGENTS.md"] = merged(target / "AGENTS.md", guide)
    ignored = ["/.runs/"]
    if target != KIT:
        ignored.append(f"/{relative}/")
    ignored.extend(f"/.agents/skills/{p.name}/" for p in sorted((KIT / "skills").iterdir()) if p.is_dir())
    updates[target / ".gitignore"] = merge_ignore(target / ".gitignore", ignored)
    for source, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")
    print(f"Installed {len(copies)} new skill files into {target / '.agents/skills'}")
    print("Existing instructions preserved. Start a new Codex session to check discovery.")


def merge_ignore(path, patterns):
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    start, end = "# hackkit:start", "# hackkit:end"
    body = "\n".join([start, *patterns, end])
    if start in old or end in old:
        if old.count(start) != 1 or old.count(end) != 1 or old.index(start) > old.index(end):
            raise ValueError(f"Invalid installation markers: {path}")
        return old[:old.index(start)] + body + old[old.index(end) + len(end):]
    return old + ("\n" if old and not old.endswith("\n") else "") + body + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        install(args.target)
    except (ValueError, OSError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
