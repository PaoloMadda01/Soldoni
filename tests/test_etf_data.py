from datetime import date
import json

import pandas as pd
import pytest


def catalog_row(**changes):
    row = {
        "isin": "IE00B4L5Y983", "fundName": "iShares Core MSCI World UCITS ETF",
        "productView": ["all", "etf"], "localExchangeTicker": "SWDA",
        "investorClassCode": " ", "investorClassName": "- ",
        "seriesBaseCurrencyCode": "USD", "useOfProfits": "Accumulating",
        "productPageUrl": "/uk/individual/en/products/251882/world-fund",
        "ter": {"d": "0.20", "r": 0.2},
    }
    row.update(changes)
    return {"251882": row}


def test_exact_isin_selects_class_even_when_london_ticker_differs():
    from soldoni.data.etf_data import profile_from_catalog
    profile = profile_from_catalog(catalog_row(), "IWDA.L", "IE00B4L5Y983")
    assert profile.hedged is False
    assert profile.isin == "IE00B4L5Y983"
    assert profile.distribution == "Accumulo"
    assert profile.expense_ratio == pytest.approx(0.002)


@pytest.mark.parametrize("changes,expected,currency", [
    ({"investorClassCode": "Hedged", "seriesBaseCurrencyCode": "GBP"}, True, "GBP"),
    ({"fundName": "iShares S&P 500 EUR Hedged UCITS ETF (Acc)"}, True, "EUR"),
    ({"fundName": "iShares Interest Rate Hedged UCITS ETF"}, False, ""),
    ({"investorClassCode": None}, None, ""),
    ({"investorClassCode": "new class"}, None, ""),
])
def test_currency_hedging_uses_official_class_and_fund_policy(changes, expected, currency):
    from soldoni.data.etf_data import profile_from_catalog
    profile = profile_from_catalog(catalog_row(**changes), "SWDA.L")
    assert profile.hedged is expected
    assert profile.hedge_currency == currency


def test_unknown_isin_never_falls_back_to_a_different_share_class():
    from soldoni.data.etf_data import profile_from_catalog
    assert profile_from_catalog(catalog_row(), "SWDA.L", "IE00B3ZW0K18") is None


def test_ambiguous_catalog_match_is_not_accepted():
    from soldoni.data.etf_data import profile_from_catalog
    rows = catalog_row()
    rows["other"] = {**rows["251882"], "isin": "IE00B3ZW0K18"}
    with pytest.raises(ValueError, match="ambigu"):
        profile_from_catalog(rows, "SWDA.L")


def product_html(isin="IE00B4L5Y983"):
    fields = {"isin": isin, "productStructure": "Physical",
              "fundMethodologyTypeCode": "Optimised", "indexSeriesName": "MSCI World Index (Net)"}
    return "".join(f'<td data-id="keyFundFacts-{key}-data">{value}</td>'
                   for key, value in fields.items())


def test_product_metadata_checks_isin_and_describes_replication():
    from soldoni.data.etf_data import enrich_profile, profile_from_catalog
    profile = profile_from_catalog(catalog_row(), "SWDA.L")
    updated = enrich_profile(profile, product_html())
    assert updated.replication == "Fisica (campionamento)"
    assert updated.benchmark == "MSCI World Index (Net)"
    with pytest.raises(ValueError, match="ISIN"):
        enrich_profile(profile, product_html("IE00B3ZW0K18"))


CSV_HEADER = "Ticker,Name,Sector,Asset Class,Weight (%),Location,Market Currency,ISIN\n"
CSV_ROWS = (
    "AAPL,APPLE,Information Technology,Equity,5.29,United States,USD,US0378331005\n"
    "USD,USD CASH,Cash and/or Derivatives,Cash,-0.01,United States,USD,-\n"
    "ZZ,SMALL POSITION,Industrials,Equity,0.00,Japan,JPY,-\n"
)


def test_full_csv_keeps_small_positions_cash_and_the_actual_source_date():
    from soldoni.data.etf_data import parse_ishares_holdings
    csv = "\ufeffFund Holdings as of,10/Sept/2026\n\u00a0\n" + CSV_HEADER + CSV_ROWS
    result = parse_ishares_holdings(csv, "https://www.ishares.com/holdings.csv")
    assert result.as_of == date(2026, 9, 10)
    assert result.complete
    assert len(result.rows) == 3
    assert result.rows[0].isin == "US0378331005"
    assert result.rows[1].weight_pct == -0.01
    assert result.rows[2].weight_pct == 0.0


@pytest.mark.parametrize("bad", ["NaN", "inf", "", "not-a-number"])
def test_bad_weight_rejects_the_download_instead_of_dropping_a_holding(bad):
    from soldoni.data.etf_data import parse_ishares_holdings
    with pytest.raises(ValueError, match="peso"):
        parse_ishares_holdings(CSV_HEADER + CSV_ROWS.replace("5.29", bad), "source")


def test_missing_date_is_unknown_and_truncated_rows_are_errors():
    from soldoni.data.etf_data import parse_ishares_holdings
    assert parse_ishares_holdings(CSV_HEADER + CSV_ROWS, "source").as_of is None
    with pytest.raises(ValueError, match="riga"):
        parse_ishares_holdings(CSV_HEADER + "AAPL,APPLE,Technology\n", "source")
    with pytest.raises(ValueError):
        parse_ishares_holdings("<html>Access denied</html>", "source")


def test_yahoo_top_holdings_are_partial_without_an_invented_date():
    from soldoni.data.etf_data import yahoo_holdings
    frame = pd.DataFrame({"Name": ["Apple", "Microsoft"],
                          "Holding Percent": [0.0529, 0.0383]}, index=["AAPL", "MSFT"])
    result = yahoo_holdings("OTHER.L", fetch=lambda ticker: frame)
    assert result.complete is False
    assert result.as_of is None
    assert result.rows[0].weight_pct == pytest.approx(5.29)


def test_unknown_provider_does_not_guess_hedging_from_name_or_currency():
    from soldoni.data.etf_data import get_etf_profile
    profile = get_etf_profile("OTHER.L", "IE0007Y8Y157", catalog={})
    assert profile.hedged is None
    assert profile.isin == "IE0007Y8Y157"


def test_network_failure_is_explicit_and_logged(caplog):
    from soldoni.data.etf_data import get_etf_profile
    def fail(url):
        raise OSError("offline")
    with pytest.raises(ValueError, match="offline"):
        get_etf_profile("SWDA.L", catalog=catalog_row(), fetch=fail)
    assert "offline" in caplog.text


def test_discovery_classification_does_not_download_each_product_page():
    from soldoni.data.etf_data import get_etf_profile
    def unexpected_download(url):
        pytest.fail("Screening must use the shared catalog without downloading product pages")
    profile = get_etf_profile("SWDA.L", catalog=catalog_row(), fetch=unexpected_download,
                              details=False)
    assert profile.hedged is False


@pytest.mark.parametrize("value,expected", [("Ad Accumulazione", "Accumulo"),
                                            ("Distribuzione", "Distribuzione")])
def test_italian_catalog_income_policy_is_normalized(value, expected):
    from soldoni.data.etf_data import profile_from_catalog
    profile = profile_from_catalog(catalog_row(useOfProfits=value), "SWDA.MI")
    assert profile.distribution == expected


def test_csv_url_keeps_the_complete_official_product_path():
    from soldoni.data.etf_data import enrich_profile, profile_from_catalog
    profile = enrich_profile(profile_from_catalog(catalog_row(), "SWDA.L"), product_html())
    assert profile.holdings_url == (
        "https://www.ishares.com/ch/individual/en/products/251882/world-fund/"
        "1495092304805.ajax?dataType=fund&fileName=holdings&fileType=csv")


def test_german_catalog_uses_the_published_table_schema_and_income_labels():
    from soldoni.data.etf_data import get_ishares_catalog, profile_from_catalog
    row = catalog_row(localExchangeTicker="EUNL", useOfProfits="Thesaurierend")["251882"]
    payload = {"code": 200, "message": "OK", "status": "success", "data": {"tableData": {
        "columns": [{"name": key} for key in row], "data": [list(row.values())]}}}
    def fetch(url):
        assert "product-screener-v3.jsn?" in url
        assert "dcrPath=" in url
        return json.dumps(payload)
    profile = profile_from_catalog(get_ishares_catalog("DE", fetch), "EUNL.DE")
    assert profile.isin == "IE00B4L5Y983"
    assert profile.distribution == "Accumulo"
    assert profile.hedged is False
