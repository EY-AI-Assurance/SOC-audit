"""Page-level retrieval for SOC report evidence.

The index is built once per report and shared by Sheet 6-9. Retrieval favors
recall: TOC ranges, direct keyword matches, and every BM25 keyword query
contribute to one union of pages. Scores are used only to select each query's
Top K pages; they are never fused to discard pages recalled by another signal.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


logger = logging.getLogger(__name__)

_DASH_TRANSLATION = str.maketrans({
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "﹘": "-",
    "﹣": "-",
    "－": "-",
})
_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_PAGE_BATCH_SIZE = 12
_PAGE_BATCH_OVERLAP = 1
_DEFAULT_BM25_TOP_K = 12
_DEFAULT_ADJACENT_PAGE_WINDOW = 1


class _BM25Index:
    """Small, dependency-free Okapi BM25 index for one report's pages."""

    def __init__(
        self,
        corpus: list[list[str]],
        k1: float = 1.2,
        b: float = 0.75,
    ):
        self.k1 = k1
        self.b = b
        self.document_lengths = [len(document) for document in corpus]
        self.average_document_length = (
            sum(self.document_lengths) / len(corpus)
            if corpus
            else 0.0
        )
        self.term_frequencies = [Counter(document) for document in corpus]

        document_frequency: Counter[str] = Counter()
        for frequencies in self.term_frequencies:
            document_frequency.update(frequencies.keys())

        corpus_size = len(corpus)
        self.inverse_document_frequency = {
            term: math.log(
                1.0 + (corpus_size - frequency + 0.5) / (frequency + 0.5)
            )
            for term, frequency in document_frequency.items()
        }

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores: list[float] = []
        for frequencies, document_length in zip(
            self.term_frequencies,
            self.document_lengths,
        ):
            length_ratio = (
                document_length / self.average_document_length
                if self.average_document_length
                else 0.0
            )
            score = 0.0
            for token in query_tokens:
                term_frequency = frequencies.get(token, 0)
                if not term_frequency:
                    continue
                denominator = term_frequency + self.k1 * (
                    1.0 - self.b + self.b * length_ratio
                )
                score += self.inverse_document_frequency.get(token, 0.0) * (
                    term_frequency * (self.k1 + 1.0) / denominator
                )
            scores.append(score)
        return scores


def normalize_text(text: str) -> str:
    """Normalize text for case-insensitive literal matching."""
    normalized = unicodedata.normalize("NFKC", text or "").translate(_DASH_TRANSLATION)
    return " ".join(normalized.casefold().split())


def _compact_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]", "", normalize_text(text))


def tokenize(text: str) -> list[str]:
    """Tokenize English/control IDs and create CJK bi/tri-grams."""
    normalized = unicodedata.normalize("NFKC", text or "").translate(_DASH_TRANSLATION).casefold()
    tokens = _WORD_PATTERN.findall(normalized)
    identifier_parts: list[str] = []
    for token in tokens:
        if "_" in token or "-" in token:
            identifier_parts.extend(
                part for part in re.split(r"[_-]+", token) if part
            )
    tokens.extend(identifier_parts)

    for run in _CJK_PATTERN.findall(normalized):
        if len(run) == 1:
            tokens.append(run)
            continue
        for size in (2, 3):
            if len(run) >= size:
                tokens.extend(run[index:index + size] for index in range(len(run) - size + 1))

    return tokens


class SearchTopicProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1)

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("values must be non-empty strings")
            normalized = normalize_text(value)
            if normalized not in seen:
                cleaned.append(value.strip())
                seen.add(normalized)
        return cleaned


class SearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    topics: dict[str, SearchTopicProfile]

    @field_validator("topics")
    @classmethod
    def _validate_topics(
        cls,
        topics: dict[str, SearchTopicProfile],
    ) -> dict[str, SearchTopicProfile]:
        if not topics:
            raise ValueError("at least one topic is required")
        if any(not name.strip() for name in topics):
            raise ValueError("topic names must be non-empty")
        return topics


@dataclass(frozen=True)
class LoadedSearchProfile:
    name: str
    version: int
    digest: str
    topics: dict[str, SearchTopicProfile]


@dataclass(frozen=True)
class RetrievalResult:
    topic: str
    page_numbers: list[int]
    batches: list[list[int]]
    reasons: dict[int, list[str]]


def load_search_profile(path: Path) -> LoadedSearchProfile:
    """Load and strictly validate one UTF-8 search profile."""
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
        profile = SearchProfile.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Invalid search profile '{path}': {exc}") from exc

    digest = sha256(raw_bytes).hexdigest()[:12]
    logger.info(
        "Loaded search profile: file=%s version=%d sha256=%s",
        path.name,
        profile.version,
        digest,
    )
    return LoadedSearchProfile(
        name=path.name,
        version=profile.version,
        digest=digest,
        topics=profile.topics,
    )


def load_search_profiles(directory: Path, sheet_numbers: set[int]) -> dict[int, LoadedSearchProfile]:
    profiles: dict[int, LoadedSearchProfile] = {}
    for sheet_number in sorted(sheet_numbers & {6, 7, 8, 9}):
        path = directory / f"sheet{sheet_number}.json"
        profiles[sheet_number] = load_search_profile(path)
    return profiles


def _contiguous_batches(
    page_numbers: list[int],
    max_pages: int = _PAGE_BATCH_SIZE,
    overlap: int = _PAGE_BATCH_OVERLAP,
) -> list[list[int]]:
    if not page_numbers:
        return []
    if max_pages <= overlap:
        raise ValueError("max_pages must be greater than overlap")

    runs: list[list[int]] = []
    current: list[int] = []
    for page_number in sorted(set(page_numbers)):
        if current and page_number != current[-1] + 1:
            runs.append(current)
            current = []
        current.append(page_number)
    if current:
        runs.append(current)

    batches: list[list[int]] = []
    for run in runs:
        start = 0
        while start < len(run):
            batch = run[start:start + max_pages]
            batches.append(batch)
            if start + max_pages >= len(run):
                break
            start += max_pages - overlap
    return batches


class RetrievalContext:
    """One shared page index for every retrieval topic in one report."""

    def __init__(
        self,
        pages: dict[int, str],
        toc_max_pages: int = 6,
        bm25_top_k: int = _DEFAULT_BM25_TOP_K,
        adjacent_page_window: int = _DEFAULT_ADJACENT_PAGE_WINDOW,
    ):
        if bm25_top_k < 1:
            raise ValueError("bm25_top_k must be positive")
        if adjacent_page_window < 0:
            raise ValueError("adjacent_page_window cannot be negative")
        self.pages = dict(sorted(pages.items()))
        self.page_numbers = list(self.pages)
        self.toc_max_pages = toc_max_pages
        self.bm25_top_k = bm25_top_k
        self.adjacent_page_window = adjacent_page_window
        self.normalized_pages = {
            page_number: normalize_text(text)
            for page_number, text in self.pages.items()
        }
        self.compact_pages = {
            page_number: _compact_text(text)
            for page_number, text in self.pages.items()
        }
        self.page_tokens = {
            page_number: tokenize(text)
            for page_number, text in self.pages.items()
        }
        self.page_token_sets = {
            page_number: set(tokens)
            for page_number, tokens in self.page_tokens.items()
        }
        corpus = [self.page_tokens[page_number] or ["__empty_page__"] for page_number in self.page_numbers]
        self.bm25 = _BM25Index(corpus) if corpus else None

    def _is_toc_page(self, page_number: int) -> bool:
        text = self.normalized_pages[page_number]
        lines = [normalize_text(line).strip(" .:-") for line in self.pages[page_number].splitlines()]
        if "table of contents" in text or "目录" in lines:
            return True
        if page_number > self.toc_max_pages:
            return False
        return "contents" in lines

    def _bm25_pages(self, query: str, top_k: int) -> list[int]:
        if self.bm25 is None:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_token_set = set(query_tokens)
        scores = self.bm25.get_scores(query_tokens)
        matches = [
            (page_number, float(scores[index]))
            for index, page_number in enumerate(self.page_numbers)
            if query_token_set & self.page_token_sets[page_number]
            and not self._is_toc_page(page_number)
        ]
        matches.sort(key=lambda item: (-item[1], item[0]))
        return [page_number for page_number, _score in matches[:top_k]]

    def retrieve(
        self,
        topic: str,
        profile: SearchTopicProfile,
        toc_pages: set[int],
        source: LoadedSearchProfile,
    ) -> RetrievalResult:
        reasons: dict[int, set[str]] = defaultdict(set)
        valid_toc_pages = sorted(
            page for page in toc_pages
            if page in self.pages and not self._is_toc_page(page)
        )
        for page_number in valid_toc_pages:
            reasons[page_number].add("toc_range")

        direct_keyword_pages: set[int] = set()
        bm25_query_pages: dict[str, list[int]] = {}
        for keyword in profile.keywords:
            normalized_keyword = normalize_text(keyword)
            compact_keyword = _compact_text(keyword)
            identifier_like = bool(re.fullmatch(r"[a-z0-9_-]+", normalized_keyword))
            for page_number, text in self.normalized_pages.items():
                if self._is_toc_page(page_number):
                    continue
                is_direct_match = normalized_keyword in text
                if identifier_like and compact_keyword:
                    is_direct_match = (
                        is_direct_match
                        or compact_keyword in self.compact_pages[page_number]
                    )
                if is_direct_match:
                    direct_keyword_pages.add(page_number)
                    reasons[page_number].add(f"keyword:{keyword}")

            matches = self._bm25_pages(keyword, self.bm25_top_k)
            bm25_query_pages[keyword] = matches
            for page_number in matches:
                reasons[page_number].add(f"bm25:{keyword}")

        union_pages = sorted(reasons)
        expanded_pages = set(union_pages)
        for page_number in union_pages:
            for candidate in range(
                page_number - self.adjacent_page_window,
                page_number + self.adjacent_page_window + 1,
            ):
                if (
                    candidate in self.pages
                    and not self._is_toc_page(candidate)
                ):
                    expanded_pages.add(candidate)
                    if candidate != page_number:
                        reasons[candidate].add(f"adjacent_to:{page_number}")

        final_pages = sorted(expanded_pages)
        serializable_reasons = {
            page_number: sorted(reasons[page_number])
            for page_number in final_pages
        }
        batches = _contiguous_batches(final_pages)

        print(
            f"[RETRIEVAL] profile={source.name} version={source.version} "
            f"sha256={source.digest} topic={topic}",
            flush=True,
        )
        print(f"[RETRIEVAL] toc_pages={valid_toc_pages}", flush=True)
        print(f"[RETRIEVAL] keyword_pages={sorted(direct_keyword_pages)}", flush=True)
        for keyword, matches in bm25_query_pages.items():
            print(f"[RETRIEVAL] bm25 keyword={keyword!r} pages={matches}", flush=True)
        print(f"[RETRIEVAL] union_pages={union_pages}", flush=True)
        print(f"[RETRIEVAL] expanded_pages={final_pages} batches={batches}", flush=True)

        return RetrievalResult(
            topic=topic,
            page_numbers=final_pages,
            batches=batches,
            reasons=serializable_reasons,
        )
