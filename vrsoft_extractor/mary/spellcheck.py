from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

try:
    _SpellChecker: Any = import_module("spellchecker").SpellChecker
except ImportError:  # pragma: no cover - friendly fallback for old portable builds
    _SpellChecker = None


WORD_PATTERN = re.compile(r"(?u)\b[A-Za-zÀ-ÖØ-öø-ÿ]{3,}\b")
IGNORED_PATTERN = re.compile(
    r"```.*?```|`[^`]+`|https?://\S+|www\.\S+|(?:[A-Za-z]:\\|/)[^\s]+|\b\w+[_/.\\-]\w+\b",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class Misspelling:
    word: str
    start: int
    length: int
    suggestions: tuple[str, ...]


class LocalSpellChecker:
    def __init__(self, state_path: Path, domain_words: list[str] | None = None):
        self.state_path = state_path
        self._checker: Any = (
            _SpellChecker(language="pt", distance=1) if _SpellChecker is not None else None
        )
        self.personal_words = self._load_personal_words()
        if self._checker:
            self._checker.word_frequency.load_words(self.personal_words)
            self._checker.word_frequency.load_words(domain_words or [])

    @property
    def available(self) -> bool:
        return self._checker is not None

    def misspellings(
        self,
        text: str,
        *,
        include_suggestions: bool = True,
    ) -> list[Misspelling]:
        if not self._checker or not text.strip():
            return []
        ignored = [(match.start(), match.end()) for match in IGNORED_PATTERN.finditer(text)]
        result: list[Misspelling] = []
        for match in WORD_PATTERN.finditer(text):
            if any(start <= match.start() < end for start, end in ignored):
                continue
            word = match.group(0)
            if word.isupper() or any(character.isdigit() for character in word):
                continue
            if word.casefold() in self.personal_words:
                continue
            if word.casefold() not in self._checker:
                normalized = word.casefold()
                ranked: list[str] = []
                if include_suggestions:
                    candidates = self._checker.candidates(normalized) or set()
                    correction = self._checker.correction(normalized)
                    # Accent omissions such as "correcao" can be two edits away
                    # from the Portuguese dictionary entry. Keep the fast lookup
                    # first and widen it only when suggestions are explicitly needed.
                    if (
                        not candidates
                        and normalized.isascii()
                        and len(normalized) <= 14
                    ):
                        original_distance = self._checker.distance
                        try:
                            self._checker.distance = 2
                            candidates = self._checker.candidates(normalized) or set()
                            correction = self._checker.correction(normalized)
                        finally:
                            self._checker.distance = original_distance
                    ranked = sorted(
                        candidates,
                        key=lambda value: (value != correction, value),
                    )
                result.append(
                    Misspelling(word, match.start(), len(word), tuple(ranked[:6]))
                )
        return result

    def correct_text(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        replacements: list[tuple[int, int, str, str]] = []
        for issue in self.misspellings(text):
            if not issue.suggestions:
                continue
            replacement = _match_case(issue.word, issue.suggestions[0])
            if replacement.casefold() != issue.word.casefold():
                replacements.append(
                    (issue.start, issue.start + issue.length, issue.word, replacement)
                )
        corrected = text
        for start, end, _old, new in reversed(replacements):
            corrected = corrected[:start] + new + corrected[end:]
        return corrected, [(old, new) for _start, _end, old, new in replacements]

    def add_word(self, word: str) -> None:
        normalized = word.strip().casefold()
        if not normalized:
            return
        self.personal_words.add(normalized)
        if self._checker:
            self._checker.word_frequency.add(normalized)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(sorted(self.personal_words), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_personal_words(self) -> set[str]:
        if not self.state_path.exists():
            return set()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {str(word).casefold() for word in payload if str(word).strip()}


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
