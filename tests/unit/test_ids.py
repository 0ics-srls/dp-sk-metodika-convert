"""source_id: one rule shared (by copy) with the grab class. Identity comes from the unique URL path, never from the file stem (P81b-05)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from dp_sk_metodika_convert import ids

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.mfsr.sk/files/archiv/35/Priloha_c_1.pdf", "files_archiv_35_Priloha_c_1"),
        ("https://www.uvo.gov.sk/extdoc/53262", "extdoc_53262"),
        ("https://nbs.sk/dokument/0a1b2c3d-1111-2222-3333-444455556666/stiahnut?force=false?force=false", "dokument_0a1b2c3d-1111-2222-3333-444455556666"),
        (
            "https://www.uvo.gov.sk/fileadmin/dokumenty/vykladove_stanoviska/2015/vykladove_stanovisko_1-2021.pdf",
            "fileadmin_dokumenty_vykladove_stanoviska_2015_vykladove_stanovisko_1-2021",
        ),
        (
            "https://www.financnasprava.sk//_img/pfsedit/Dokumenty_PFS/Zverejnovanie_dok/Dane/Zavery_zo_zasadani/2014/2014.05.09_Zapis_metodika_dane_z_prijmov.pdf",
            "Dane_Zavery_zo_zasadani_2014_2014.05.09_Zapis_metodika_dane_z_prijmov",
        ),
        ("https://nbs.sk/_img/Documents/_Dohlad/Metodicke/stanovisko_2020.pdf?x=1#frag", "Documents__Dohlad_Metodicke_stanovisko_2020"),
    ],
)
def test_should_slug_the_url_path_below_the_host(url: str, expected: str) -> None:
    assert ids.source_id_from_url(url) == expected


@pytest.mark.unit
def test_should_percent_decode_and_keep_slovak_letters() -> None:
    assert ids.source_id_from_url("https://www.mfsr.sk/files/archiv/2013/Pou%C4%8Denie%20DP.pdf") == "files_archiv_2013_Poučenie_DP"


@pytest.mark.unit
def test_should_cap_a_long_path_at_200_characters_with_a_hash_suffix() -> None:
    long_a = ids.source_id_from_url("https://x.sk/" + "a" * 300 + "/one.pdf")
    long_b = ids.source_id_from_url("https://x.sk/" + "a" * 300 + "/two.pdf")

    assert len(long_a) == 200
    assert long_a != long_b
    assert re.search(r"_[0-9a-f]{8}$", long_a)
    assert ids.is_safe_source_id(long_a)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["../../x", "/etc/passwd", "a/b", "a\\b", "..", ".", "", "C:\\x", "a b", "x\x00y", "a:b", "x" * 201])
def test_should_reject_traversal_separators_and_unsafe_names(bad: str) -> None:
    assert not ids.is_safe_source_id(bad)
    with pytest.raises(ids.InvalidSourceId):
        ids.check_source_id(bad)


@pytest.mark.unit
@pytest.mark.parametrize("good", ["extdoc_53262", "2014.05.09_Zapis", "Poučenie_č_1", "dokument_0a1b-2c", "files_archiv_35_Priloha_c_1"])
def test_should_accept_slugs(good: str) -> None:
    assert ids.is_safe_source_id(good)
    assert ids.check_source_id(good) == good


@pytest.mark.unit
def test_the_715_recorded_mfsr_urls_give_715_distinct_source_ids() -> None:
    urls: list[str] = json.loads((FIXTURES / "mfsr-urls.json").read_text(encoding="utf-8"))

    new_ids = [ids.source_id_from_url(url) for url in urls]
    # CONTRAST: the legacy rule (slug of the file stem only) collapses these same URLs to 645 ids, so 70 documents overwrote one another
    legacy_stems = {re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(urlparse(url).path).stem) for url in urls}

    assert len(urls) == 715
    assert len(set(urls)) == 715
    assert len(legacy_stems) == 645
    assert len(set(new_ids)) == 715
    assert all(ids.is_safe_source_id(item) for item in new_ids)
