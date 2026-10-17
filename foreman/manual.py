"""Section-level retrieval over machine manuals (BM25, no external services)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

_HEADING = re.compile(r"^##\s+(?P<num>[\d.]+)\s+(?P<title>.+?)\s*\[p\.(?P<page>\d+)\]\s*$")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_XREF = re.compile(r"(?:procedure|section)\s+(\d+(?:\.\d+)?)", re.I)
_STOP = set("a an and are as at be by for from if in into is it of on or per the to with without".split())


@dataclass(frozen=True)
class Section:
    manual: str
    number: str
    title: str
    page: int
    text: str

    @property
    def ref(self) -> str:
        return f"§{self.number} p.{self.page}"


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class ManualIndex:
    def __init__(self, manuals_dir: Path) -> None:
        self.sections: list[Section] = []
        for path in sorted(manuals_dir.glob("*.md")):
            self.sections.extend(self._parse(path))
        if not self.sections:
            raise FileNotFoundError(f"no manual sections found in {manuals_dir}")
        self.title = next(
            (line[2:].strip() for line in (manuals_dir / sorted(p.name for p in manuals_dir.glob("*.md"))[0]).read_text(encoding="utf-8").splitlines() if line.startswith("# ")),
            "Machine manual",
        )
        self._bm25 = BM25Okapi([_tokens(f"{s.title} {s.title} {s.text}") for s in self.sections])

    @staticmethod
    def _parse(path: Path) -> list[Section]:
        out, cur, buf = [], None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _HEADING.match(line)
            if m:
                if cur:
                    out.append(Section(path.stem, cur["num"], cur["title"], int(cur["page"]), "\n".join(buf).strip()))
                cur, buf = m.groupdict(), []
                cur["num"] = cur["num"].rstrip(".")  # "## 1. Safety" -> "1"
            elif cur is not None:
                buf.append(line)
        if cur:
            out.append(Section(path.stem, cur["num"], cur["title"], int(cur["page"]), "\n".join(buf).strip()))
        return out

    def search(self, query: str, k: int = 4, prefixes: tuple[str, ...] = ()) -> list[tuple[Section, float]]:
        """BM25 over sections; `prefixes` restricts to chapters, e.g. ("5.", "6.") for troubleshooting + procedures."""
        scores = self._bm25.get_scores(_tokens(query))
        pairs = zip(self.sections, scores)
        if prefixes:
            pairs = ((s, sc) for s, sc in pairs if s.number.startswith(prefixes))
        ranked = sorted(pairs, key=lambda x: -x[1])
        return [(s, float(sc)) for s, sc in ranked[:k] if sc > 0]

    def cross_refs(self, section: Section) -> list[str]:
        """Section numbers this section points to, e.g. "per procedure 6.1" or "see section 5.2"."""
        refs = _XREF.findall(section.text)
        known = {s.number for s in self.sections}
        return [r for r in dict.fromkeys(refs) if r in known and r != section.number]

    def get(self, number: str) -> Section | None:
        return next((s for s in self.sections if s.number == number), None)
