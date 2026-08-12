import pandas as pd

import config
import logic_calculator as calc


def test_normalize_gubun_accepts_common_aliases():
    assert config.normalize_gubun("자재비") == "자재"
    assert config.normalize_gubun(" Labor ") == "노무"
    assert config.normalize_gubun("장비") == "장비"
    assert config.normalize_gubun("알 수 없음") is None


def test_to_number_series_handles_currency_and_negative_values():
    values = config.to_number_series(["₩1,250,000", "(15,000)", "12.5%", None])
    assert values.tolist() == [1_250_000.0, -15_000.0, 12.5, 0.0]


def test_category_audit_marks_only_unknown_rows():
    frame = pd.DataFrame(
        {
            "구분": ["자재비", "노무", "equipment", "기타"],
            "합계": ["1,000", 2_000, 3_000, 4_000],
        }
    )

    result = calc.audit_categories(frame)

    assert result["counted"] == {"자재": 1_000, "노무": 2_000, "장비": 3_000}
    assert result["unknown"] == {"기타": 4_000}
    assert result["unknown_rows"] == 1


def test_cost_summary_uses_normalized_categories():
    frame = pd.DataFrame(
        {
            "구분": ["자재비", "노무", "장비비"],
            "합계": ["1,000", "2,000", "3,000"],
        }
    )

    summary = pd.DataFrame(calc.calculate_cost_summary(frame, config.DEFAULT_RATES))

    material = summary.loc[summary["비목"] == "1. 재료비", "금액(원)"].iloc[0]
    equipment = summary.loc[summary["비목"] == " └ 기계경비(장비비)", "금액(원)"].iloc[0]
    assert material == "1,000"
    assert equipment == "3,000"
