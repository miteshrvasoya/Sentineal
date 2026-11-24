"""Versioned prompt templates stored as files (`<id>.v<N>.md`) with `## system` and `## user` sections."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    system: str
    user: str

    def render(self, **vars: str) -> tuple[str, str]:
        """Substitute {{name}} placeholders (not str.format, so JSON braces in templates are safe)."""
        def sub(t: str) -> str:
            for k, v in vars.items():
                t = t.replace("{{" + k + "}}", str(v))
            left = re.findall(r"\{\{(\w+)\}\}", t)
            if left:
                raise KeyError(f"prompt {self.id}.v{self.version}: unfilled placeholders {left}")
            return t
        return sub(self.system), sub(self.user)


@lru_cache
def load_prompt(prompt_id: str, version: int | None = None) -> Prompt:
    files = sorted(DIR.glob(f"{prompt_id}.v*.md"), key=lambda p: int(re.search(r"\.v(\d+)\.md$", p.name).group(1)))  # type: ignore[union-attr]
    if not files:
        raise FileNotFoundError(f"no prompt named {prompt_id}")
    path = files[-1] if version is None else DIR / f"{prompt_id}.v{version}.md"
    text = path.read_text()
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", text.split("---")[1], re.M))
    body = text.split("---", 2)[2]
    sys_part = re.search(r"## system\s*\n(.*?)(?=\n## user)", body, re.S)
    user_part = re.search(r"## user\s*\n(.*)$", body, re.S)
    if not (sys_part and user_part):
        raise ValueError(f"{path.name} needs '## system' and '## user' sections")
    return Prompt(meta["id"], int(meta["version"]), sys_part.group(1).strip(), user_part.group(1).strip())
