import json
from pathlib import Path

import pytest

from app.services.extractor import (
    _extract_sheet6_batches,
    _extract_sheet7_batches,
    _extract_sheet8_batches,
    _extract_sheet9_batches,
    extract,
)
from app.services.pdf_parser import save_parsed
from app.services.retrieval import (
    LoadedSearchProfile,
    RetrievalContext,
    SearchTopicProfile,
    _contiguous_batches,
    load_search_profile,
    tokenize,
)
from app.config import settings


def _source(profile: SearchTopicProfile) -> LoadedSearchProfile:
    return LoadedSearchProfile(
        name="test.json",
        version=1,
        digest="test-digest",
        topics={"csoc": profile},
    )


def test_tokenize_preserves_control_ids_and_builds_chinese_ngrams():
    tokens = tokenize("CCC_01 用户实体控制")

    assert "ccc_01" in tokens
    assert "ccc" in tokens
    assert "用户" in tokens
    assert "用户实" in tokens


def test_retrieval_unions_toc_direct_keywords_bm25_and_excludes_toc_page():
    pages = {
        1: "Table of Contents\nComplementary Subservice Organization Controls .... 56",
        2: "Subservice overview supplied by the report.",
        3: "Section IV. Complementary Subservice Organization Controls",
        4: "The controls expected to be\nimplemented by subservice organizations are below.",
        5: "Other Information",
        6: "Unrelated appendix.",
        7: "A third party provider implements required infrastructure controls.",
    }
    profile = SearchTopicProfile(
        keywords=[
            "Complementary Subservice Organization Controls",
            "controls expected to be implemented by subservice organizations",
            "third party provider controls",
        ],
    )
    context = RetrievalContext(
        pages,
        toc_max_pages=1,
        bm25_top_k=5,
        adjacent_page_window=0,
    )

    result = context.retrieve("csoc", profile, {2}, _source(profile))

    assert 1 not in result.page_numbers
    assert {2, 3, 4, 7}.issubset(result.page_numbers)
    assert 5 not in result.page_numbers
    assert "toc_range" in result.reasons[2]
    assert any(reason.startswith("keyword:") for reason in result.reasons[3])
    assert any(reason.startswith("keyword:") for reason in result.reasons[4])
    assert any(reason.startswith("bm25:") for reason in result.reasons[7])


def test_retrieval_expands_adjacent_pages_around_keyword_hits():
    pages = {
        1: "Introduction",
        2: "Relevant responsibility statement",
        3: "Other Information",
        4: "Appendix",
    }
    profile = SearchTopicProfile(
        keywords=["relevant responsibility statement"],
    )
    context = RetrievalContext(pages, toc_max_pages=0)

    result = context.retrieve("csoc", profile, set(), _source(profile))

    assert result.page_numbers == [1, 2, 3]
    assert "adjacent_to:2" in result.reasons[1]
    assert "adjacent_to:2" in result.reasons[3]


def test_keyword_matches_control_id_with_different_separator():
    profile = SearchTopicProfile(
        keywords=["CCC_01"],
    )
    context = RetrievalContext(
        {1: "Control CCC-01 governs production changes."},
        toc_max_pages=0,
        adjacent_page_window=0,
    )

    result = context.retrieve("change_mgmt", profile, set(), _source(profile))

    assert result.page_numbers == [1]
    assert "keyword:CCC_01" in result.reasons[1]


def test_contiguous_batches_keep_every_page_and_overlap_by_one():
    page_numbers = list(range(1, 26))

    batches = _contiguous_batches(page_numbers)

    assert batches == [list(range(1, 13)), list(range(12, 24)), [23, 24, 25]]
    assert set().union(*map(set, batches)) == set(page_numbers)


class _SequenceLLM:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)

    def call_json(self, _prompt: str):
        return self.responses.pop(0)


def test_sheet6_extra_batches_merge_only_their_topic():
    first = {
        "change_mgmt": {
            "has_process_description": "Yes",
            "page_refs": "EN Report:\nPage 10",
            "section_b_applicable": "Not applicable",
            "section_c_applicable": "Applicable",
            "risk_control_ids": ["CCC_01", "CCC_02"],
        },
        "access_mgmt": {
            "has_process_description": "Yes",
            "page_refs": "EN Report:\nPage 20",
            "section_b_applicable": "Not applicable",
            "section_c_applicable": "Applicable",
            "risk_control_ids": ["IVS_01", "APD_01", "APD_02"],
        },
        "job_scheduling": {
            "has_process_description": "Not applicable",
            "page_refs": "",
            "section_b_applicable": "Not applicable",
            "section_c_applicable": "Not applicable",
            "risk_control_ids": [],
        },
    }
    second = {
        **first,
        "change_mgmt": {
            "has_process_description": "Yes",
            "page_refs": "EN Report:\nPage 11",
            "section_b_applicable": "Not applicable",
            "section_c_applicable": "Applicable",
            "risk_control_ids": ["CCC_03", "CCC_04"],
        },
        "access_mgmt": {
            "has_process_description": "Not applicable",
            "page_refs": "",
            "section_b_applicable": "Not applicable",
            "section_c_applicable": "Not applicable",
            "risk_control_ids": [],
        },
    }
    llm = _SequenceLLM([first, second])

    result = _extract_sheet6_batches(
        llm,
        {
            "change_mgmt": ["batch one", "batch two"],
            "access_mgmt": ["access batch"],
            "job_scheduling": [],
        },
        "EN Report",
    )

    assert result.change_mgmt.page_refs == "EN Report:\nPage 10\nPage 11"
    assert result.change_mgmt.risk_control_ids == ["CCC_01\nCCC_03", "CCC_02\nCCC_04"]
    assert result.access_mgmt.risk_control_ids == ["IVS_01", "APD_01", "APD_02"]


def test_sheet7_batches_dedupe_normalized_organization_names():
    llm = _SequenceLLM([
        {
            "has_subservice": True,
            "organizations": [{"name": "Hosting Provider", "services": "Compute"}],
        },
        {
            "has_subservice": True,
            "organizations": [{"name": " hosting provider ", "services": "Storage"}],
        },
    ])

    result = _extract_sheet7_batches(llm, ["batch one", "batch two"])

    assert len(result.organizations) == 1
    assert result.organizations[0].services == "Compute\nStorage"


def test_sheet9_batches_dedupe_overlap_items():
    item = {
        "objective_and_page": "Infrastructure Page 42",
        "subservice_org": "Hosting Provider",
        "relevant": "Yes",
        "description": "The provider monitors scheduled jobs.",
        "necessary": "",
        "reason": "",
        "response": "",
    }
    llm = _SequenceLLM([{"csocs": [item]}, {"csocs": [item]}])

    result = _extract_sheet9_batches(llm, ["batch one", "batch two"])

    assert len(result.csocs) == 1


def test_sheet8_batches_dedupe_short_overlap_items():
    item = {
        "objective_and_page": "Access Page 40",
        "description": "Users approve access requests."
    }
    llm = _SequenceLLM([{"cuecs": [item]}, {"cuecs": [item]}])

    result = _extract_sheet8_batches(llm, ["batch one", "batch two"])

    assert len(result.cuecs) == 1


def test_utf8_profile_loads_with_digest_and_invalid_profile_names_file(tmp_path: Path):
    valid_path = tmp_path / "sheet9.json"
    valid_path.write_text(
        json.dumps({
            "version": 1,
            "topics": {
                "csoc": {
                    "keywords": ["补充性子服务机构控制", "第三方服务商控制"]
                }
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_search_profile(valid_path)

    assert loaded.topics["csoc"].keywords == ["补充性子服务机构控制", "第三方服务商控制"]
    assert len(loaded.digest) == 12

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"version": 1, "topics": {"csoc": {"unknown": true}}}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid\.json"):
        load_search_profile(invalid_path)


def test_all_shipped_search_profiles_are_valid():
    expected_topics = {
        "sheet6.json": {"change_mgmt", "access_mgmt", "job_scheduling"},
        "sheet7.json": {"subservice"},
        "sheet8.json": {"cuec"},
        "sheet9.json": {"csoc"},
    }

    for filename, topics in expected_topics.items():
        loaded = load_search_profile(settings.search_terms_dir / filename)
        assert set(loaded.topics) == topics


class _Sheet7And9LLM:
    def __init__(self):
        self.sheet9_calls = 0

    def call_json(self, prompt: str):
        if "TABLE OF CONTENTS:" in prompt and '"csoc_pages"' in prompt:
            return {
                "system_name": "CenturyLink Cloud",
                "opinion_pages": [0, 0],
                "change_mgmt_pages": [0, 0],
                "access_mgmt_pages": [0, 0],
                "job_scheduling_pages": [0, 0],
                "subservice_pages": [0, 0],
                "cuec_pages": [0, 0],
                "csoc_pages": [0, 0],
            }
        if "Form 107-A Sheet 9" in prompt:
            self.sheet9_calls += 1
            return {
                "csocs": [{
                    "objective_and_page": "Infrastructure Page 7",
                    "subservice_org": "Hosting Provider",
                    "relevant": "Yes",
                    "description": "The provider monitors scheduled infrastructure jobs.",
                    "necessary": "",
                    "reason": "",
                    "response": "",
                }]
            }
        if "section discussing subservice organizations" in prompt:
            return {"has_subservice": False, "organizations": []}
        raise AssertionError(f"Unexpected prompt: {prompt[:120]}")


def test_sheet9_global_retrieval_runs_when_sheet7_returns_false(tmp_path: Path):
    parsed_path = tmp_path / "report.json"
    save_parsed({
        1: "Table of Contents",
        2: "Cover",
        3: "Scope",
        4: "Description",
        5: "Controls",
        6: "Tests",
        7: (
            "Complementary Subservice Organization Controls\n"
            "Controls expected to be implemented by subservice organizations."
        ),
    }, parsed_path)
    llm = _Sheet7And9LLM()

    result = extract(parsed_path, llm, sheets=[7, 9])

    assert result.sheet7 is not None
    assert result.sheet7.has_subservice is False
    assert result.sheet9 is not None
    assert len(result.sheet9.csocs) == 1
    assert llm.sheet9_calls >= 1
