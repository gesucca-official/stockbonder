#!/usr/bin/env python3
"""
Fetch listed companies for Borsa Italiana, Xetra, LSE, NYSE, or NASDAQ and their
fundamental metrics at run time.

Data sources:
- NYSE/NASDAQ listings: Nasdaq Trader Symbol Directory.
- Borsa Italiana/Xetra/LSE listings and all fundamentals: Yahoo Finance via yfinance.

Yahoo/yfinance is practical and free for personal/research use, but it is not
an official financial-data license. Treat the output as a research snapshot,
not as investment advice or a data source for production trading.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

MARKET_ALIASES = {
    "nasdaq": "nasdaq",
    "ndq": "nasdaq",
    "nms": "nasdaq",
    "nyse": "nyse",
    "nyq": "nyse",
    "all": "all",
    "tutti": "all",
    "tutto": "all",
    "borsa": "borsa",
    "borsa-italiana": "borsa",
    "borsa_italiana": "borsa",
    "milano": "borsa",
    "milan": "borsa",
    "mil": "borsa",
    "mi": "borsa",
    "xetra": "xetra",
    "xetr": "xetra",
    "ger": "xetra",
    "de": "xetra",
    "germany": "xetra",
    "deutschland": "xetra",
    "lse": "lse",
    "london": "lse",
    "london-stock-exchange": "lse",
    "london_stock_exchange": "lse",
    "uk": "lse",
    "gb": "lse",
}

OUTPUT_FIELDS = [
    "market",
    "symbol",
    "yahoo_symbol",
    "isin",
    "name",
    "currency",
    "exchange",
    "quote_type",
    "country",
    "sector",
    "industry",
    "current_price",
    "market_cap",
    "enterprise_value",
    "pe_ttm",
    "pe_forward",
    "peg_ratio",
    "price_to_sales",
    "price_to_book",
    "ev_to_revenue",
    "ev_to_ebitda",
    "roe_pct",
    "roa_pct",
    "roic_pct",
    "debt_to_equity_ratio",
    "debt_to_equity_pct",
    "debt_to_assets_pct",
    "net_debt_to_ebitda",
    "interest_coverage",
    "current_ratio",
    "quick_ratio",
    "gross_margin_pct",
    "ebitda_margin_pct",
    "profit_margin_pct",
    "net_margin_pct",
    "operating_margin_pct",
    "asset_turnover",
    "equity_multiplier",
    "fcf_yield_pct",
    "revenue_growth_pct",
    "earnings_growth_pct",
    "dividend_yield_pct",
    "payout_ratio_pct",
    "dividend_rate",
    "beta",
    "trailing_eps",
    "book_value",
    "total_revenue",
    "gross_profit",
    "ebitda",
    "ebit",
    "operating_income",
    "net_income",
    "total_debt",
    "net_debt",
    "total_cash",
    "current_assets",
    "current_liabilities",
    "working_capital",
    "total_assets",
    "total_liabilities",
    "stockholders_equity",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
    "shares_outstanding",
    "float_shares",
    "held_percent_institutions_pct",
    "held_percent_insiders_pct",
    "analyst_count",
    "target_mean_price",
    "recommendation_key",
    "statements_loaded",
    "listing_source",
    "fundamental_source",
    "fetched_at_utc",
    "status",
    "error",
]


def log_progress(message: str, quiet: bool) -> None:
    if quiet:
        return
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}", file=sys.stderr, flush=True)


def format_elapsed(start: float) -> str:
    elapsed = max(0.0, time.monotonic() - start)
    if elapsed < 60:
        return f"{elapsed:.0f}s"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes}m{seconds:02d}s"


@dataclass(frozen=True)
class Listing:
    market: str
    symbol: str
    yahoo_symbol: str
    name: str | None
    exchange: str | None
    source: str
    quote: dict[str, Any] | None = None


def load_yfinance():
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit(
            "Dipendenza mancante: installa yfinance con "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return yf


def normalize_market(value: str) -> str:
    key = value.strip().lower()
    if key not in MARKET_ALIASES:
        accepted = ", ".join(sorted(MARKET_ALIASES))
        raise argparse.ArgumentTypeError(f"Mercato non supportato: {value!r}. Usa uno tra: {accepted}")
    return MARKET_ALIASES[key]


def download_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "market-fundamentals/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8-sig")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Impossibile scaricare {url}: {exc}") from exc


def parse_pipe_file(text: str) -> tuple[list[dict[str, str]], str | None]:
    rows: list[dict[str, str]] = []
    creation_time = None
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    for row in reader:
        first_value = next(iter(row.values()), "") or ""
        if first_value.startswith("File Creation Time"):
            creation_time = first_value.replace("File Creation Time:", "").strip()
            break
        rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})
    return rows, creation_time


def to_yahoo_us_symbol(symbol: str) -> str:
    # Yahoo Finance uses dashes for US class suffixes, e.g. BRK-B.
    return symbol.strip().replace(".", "-")


NON_COMMON_SECURITY_MARKERS = [
    " - right",
    " - rights",
    " - unit",
    " - units",
    " - warrant",
    " - warrants",
    " rights",
    " units",
    " warrant",
    " warrants",
    " preferred stock",
    " preference share",
    " preference shares",
    " preferred share",
    " preferred shares",
    " depositary share",
    " depositary shares",
    " notes due",
    " note due",
    " senior notes",
    " subordinated notes",
    " debenture",
    " debentures",
    " baby bond",
    " closed end fund",
    " closed-end fund",
]


def is_probably_non_common_security(name: str | None) -> bool:
    if not name:
        return False
    lowered = f" {name.lower()} "
    return any(marker in lowered for marker in NON_COMMON_SECURITY_MARKERS)


def is_borsa_gem_symbol(symbol: str) -> bool:
    base_symbol = symbol.strip().upper().removesuffix(".MI")
    return base_symbol.startswith("1")


def is_borsa_numeric_symbol(symbol: str) -> bool:
    base_symbol = symbol.strip().upper().removesuffix(".MI")
    return bool(base_symbol) and base_symbol[0].isdigit()


BORSA_CERTIFICATE_LIKE_SYMBOL_RE = re.compile(r"^[A-Z]{1,3}\d{3,}$")
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

BORSA_NON_SHARE_NAME_MARKERS = [
    " certificate",
    " certificates",
    " certificato",
    " certificati",
    " covered warrant",
    " warrant",
    " turbo",
    " bonus cap",
    " cash collect",
    " memory cash",
    " maxi cedola",
    " autocallable",
    " express certificate",
]


def borsa_quote_name(quote: dict[str, Any]) -> str | None:
    name = first_nonempty(quote.get("longName"), quote.get("shortName"), quote.get("displayName"))
    return str(name).strip() if name else None


def is_borsa_certificate_like_symbol(symbol: str) -> bool:
    base_symbol = symbol.strip().upper().removesuffix(".MI")
    return bool(BORSA_CERTIFICATE_LIKE_SYMBOL_RE.fullmatch(base_symbol))


def has_borsa_non_share_name(name: str | None) -> bool:
    if not name:
        return False
    lowered = f" {name.lower()} "
    return any(marker in lowered for marker in BORSA_NON_SHARE_NAME_MARKERS)


def should_include_borsa_quote(quote: dict[str, Any], include_borsa_gem: bool) -> bool:
    symbol = str(quote.get("symbol") or "")
    quote_type = str(quote.get("quoteType") or "").upper()
    if quote_type and quote_type != "EQUITY":
        return False
    if is_borsa_gem_symbol(symbol):
        return include_borsa_gem
    if is_borsa_numeric_symbol(symbol):
        return False
    name = borsa_quote_name(quote)
    if not name:
        return False
    if is_borsa_certificate_like_symbol(symbol):
        return False
    if has_borsa_non_share_name(name):
        return False
    return True


def should_include_xetra_quote(quote: dict[str, Any]) -> bool:
    quote_type = str(quote.get("quoteType") or "").upper()
    if quote_type and quote_type != "EQUITY":
        return False
    name = borsa_quote_name(quote)
    if not name:
        return False
    if has_borsa_non_share_name(name):
        return False
    return True


def is_lse_zero_prefixed_symbol(symbol: str) -> bool:
    core_symbol = symbol.strip().upper().removesuffix(".L")
    return core_symbol.startswith("0")


def should_include_lse_quote(quote: dict[str, Any]) -> bool:
    symbol = str(quote.get("symbol") or "")
    if is_lse_zero_prefixed_symbol(symbol):
        return False
    return should_include_xetra_quote(quote)


def list_nasdaq(include_etfs: bool, include_non_common: bool) -> list[Listing]:
    rows, _creation_time = parse_pipe_file(download_text(NASDAQ_LISTED_URL))
    listings: list[Listing] = []
    for row in rows:
        symbol = row.get("Symbol", "")
        if not symbol:
            continue
        if row.get("Test Issue") == "Y":
            continue
        if not include_etfs and row.get("ETF") == "Y":
            continue
        if not include_non_common and is_probably_non_common_security(row.get("Security Name")):
            continue
        listings.append(
            Listing(
                market="nasdaq",
                symbol=symbol,
                yahoo_symbol=to_yahoo_us_symbol(symbol),
                name=row.get("Security Name") or None,
                exchange="NASDAQ",
                source=NASDAQ_LISTED_URL,
            )
        )
    return listings


def list_nyse(include_etfs: bool, include_non_common: bool) -> list[Listing]:
    rows, _creation_time = parse_pipe_file(download_text(OTHER_LISTED_URL))
    listings: list[Listing] = []
    for row in rows:
        if row.get("Exchange") != "N":
            continue
        symbol = row.get("ACT Symbol", "")
        if not symbol:
            continue
        if row.get("Test Issue") == "Y":
            continue
        if not include_etfs and row.get("ETF") == "Y":
            continue
        if not include_non_common and is_probably_non_common_security(row.get("Security Name")):
            continue
        listings.append(
            Listing(
                market="nyse",
                symbol=symbol,
                yahoo_symbol=to_yahoo_us_symbol(symbol),
                name=row.get("Security Name") or None,
                exchange="NYSE",
                source=OTHER_LISTED_URL,
            )
        )
    return listings


def yahoo_screen_quotes(
    region: str,
    exchange: str,
    max_symbols: int | None,
    retries: int,
    retry_sleep: float,
    quiet: bool,
    require_market_cap: bool = False,
    quote_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    yf = load_yfinance()
    try:
        from yfinance import EquityQuery
    except ImportError as exc:
        raise SystemExit(
            "La versione installata di yfinance non include EquityQuery/screen. "
            "Aggiorna con `python -m pip install --upgrade yfinance`."
        ) from exc

    query_parts = [
        EquityQuery("eq", ["region", region]),
        EquityQuery("eq", ["exchange", exchange]),
    ]
    if require_market_cap:
        query_parts.append(EquityQuery("gt", ["intradaymarketcap", 0]))

    query = EquityQuery("and", query_parts)
    quotes: list[dict[str, Any]] = []
    offset = 0
    page_size = 250
    started_at = time.monotonic()
    log_progress(f"Yahoo screener {exchange}: avvio download lista", quiet)

    while True:
        remaining = None if max_symbols is None else max_symbols - len(quotes)
        if remaining is not None and remaining <= 0:
            break
        size = page_size if remaining is None or quote_filter is not None else min(page_size, remaining)
        response = None
        log_progress(f"Yahoo screener {exchange}: pagina offset={offset}, size={size}", quiet)
        for attempt in range(retries + 1):
            try:
                response = yf.screen(query, offset=offset, size=size, sortField="ticker", sortAsc=True)
                break
            except Exception as exc:
                if attempt >= retries:
                    raise RuntimeError(
                        f"Yahoo screener rate limit or request error for region={region}, exchange={exchange}: {exc}"
                    ) from exc
                log_progress(
                    f"Yahoo screener {exchange}: retry {attempt + 1}/{retries} tra {retry_sleep * (attempt + 1):.0f}s",
                    quiet,
                )
                time.sleep(retry_sleep * (attempt + 1))

        page = response.get("quotes") or []
        if not page:
            break
        accepted = [quote for quote in page if quote_filter is None or quote_filter(quote)]
        if remaining is None:
            quotes.extend(accepted)
        else:
            quotes.extend(accepted[:remaining])

        total = response.get("total")
        offset += len(page)
        total_text = f"/{total}" if isinstance(total, int) else ""
        log_progress(
            f"Yahoo screener {exchange}: lette {offset}{total_text}, accettate {len(quotes)}",
            quiet,
        )
        if max_symbols is not None and len(quotes) >= max_symbols:
            break
        if len(page) < size:
            break
        if isinstance(total, int) and offset >= total:
            break

    log_progress(f"Yahoo screener {exchange}: lista pronta ({len(quotes)} simboli, {format_elapsed(started_at)})", quiet)
    return quotes


def list_borsa(
    max_symbols: int | None,
    retries: int,
    retry_sleep: float,
    include_borsa_gem: bool,
    quiet: bool,
) -> list[Listing]:
    quotes = yahoo_screen_quotes(
        region="it",
        exchange="MIL",
        max_symbols=max_symbols,
        retries=retries,
        retry_sleep=retry_sleep,
        quiet=quiet,
        require_market_cap=True,
        quote_filter=lambda quote: should_include_borsa_quote(quote, include_borsa_gem=include_borsa_gem),
    )
    listings: list[Listing] = []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip()
        if not symbol:
            continue
        listings.append(
            Listing(
                market="borsa",
                symbol=symbol.removesuffix(".MI"),
                yahoo_symbol=symbol,
                name=first_nonempty(quote.get("longName"), quote.get("shortName"), quote.get("displayName")),
                exchange=str(quote.get("exchange") or "MIL"),
                source="Yahoo Finance screener: region=it, exchange=MIL",
                quote=quote,
            )
        )
    return listings


def list_xetra(max_symbols: int | None, retries: int, retry_sleep: float, quiet: bool) -> list[Listing]:
    quotes = yahoo_screen_quotes(
        region="de",
        exchange="GER",
        max_symbols=max_symbols,
        retries=retries,
        retry_sleep=retry_sleep,
        quiet=quiet,
        require_market_cap=True,
        quote_filter=should_include_xetra_quote,
    )
    listings: list[Listing] = []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip()
        if not symbol:
            continue
        listings.append(
            Listing(
                market="xetra",
                symbol=symbol.removesuffix(".DE"),
                yahoo_symbol=symbol,
                name=first_nonempty(quote.get("longName"), quote.get("shortName"), quote.get("displayName")),
                exchange=str(quote.get("exchange") or "GER"),
                source="Yahoo Finance screener: region=de, exchange=GER",
                quote=quote,
            )
        )
    return listings


def list_lse(max_symbols: int | None, retries: int, retry_sleep: float, quiet: bool) -> list[Listing]:
    quotes = yahoo_screen_quotes(
        region="gb",
        exchange="LSE",
        max_symbols=max_symbols,
        retries=retries,
        retry_sleep=retry_sleep,
        quiet=quiet,
        require_market_cap=True,
        quote_filter=should_include_lse_quote,
    )
    listings: list[Listing] = []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip()
        if not symbol:
            continue
        listings.append(
            Listing(
                market="lse",
                symbol=symbol.removesuffix(".L"),
                yahoo_symbol=symbol,
                name=first_nonempty(quote.get("longName"), quote.get("shortName"), quote.get("displayName")),
                exchange=str(quote.get("exchange") or "LSE"),
                source="Yahoo Finance screener: region=gb, exchange=LSE",
                quote=quote,
            )
        )
    return listings


def load_listings(
    market: str,
    include_etfs: bool,
    include_non_common: bool,
    include_borsa_gem: bool,
    retries: int,
    retry_sleep: float,
    limit: int | None,
    quiet: bool,
) -> list[Listing]:
    started_at = time.monotonic()
    if market == "all":
        listings: list[Listing] = []
        log_progress("Carico liste per tutti i mercati supportati", quiet)
        for child_market in ("borsa", "xetra", "lse", "nyse", "nasdaq"):
            listings.extend(
                load_listings(
                    market=child_market,
                    include_etfs=include_etfs,
                    include_non_common=include_non_common,
                    include_borsa_gem=include_borsa_gem,
                    retries=retries,
                    retry_sleep=retry_sleep,
                    limit=limit,
                    quiet=quiet,
                )
            )
        log_progress(f"Liste aggregate: {len(listings)} simboli totali ({format_elapsed(started_at)})", quiet)
        return listings
    if market == "nasdaq":
        log_progress("Carico lista NASDAQ da Nasdaq Trader", quiet)
        listings = list_nasdaq(include_etfs=include_etfs, include_non_common=include_non_common)
    elif market == "nyse":
        log_progress("Carico lista NYSE da Nasdaq Trader", quiet)
        listings = list_nyse(include_etfs=include_etfs, include_non_common=include_non_common)
    elif market == "borsa":
        log_progress("Carico lista Borsa Italiana da Yahoo Finance", quiet)
        listings = list_borsa(
            max_symbols=limit,
            retries=retries,
            retry_sleep=retry_sleep,
            include_borsa_gem=include_borsa_gem,
            quiet=quiet,
        )
    elif market == "xetra":
        log_progress("Carico lista Xetra da Yahoo Finance", quiet)
        listings = list_xetra(max_symbols=limit, retries=retries, retry_sleep=retry_sleep, quiet=quiet)
    elif market == "lse":
        log_progress("Carico lista LSE da Yahoo Finance", quiet)
        listings = list_lse(max_symbols=limit, retries=retries, retry_sleep=retry_sleep, quiet=quiet)
    else:
        raise ValueError(f"Unsupported market: {market}")

    listings = dedupe_listings(listings)
    if market not in ("borsa", "xetra", "lse") and limit is not None:
        listings = listings[:limit]
    log_progress(f"Lista {market}: {len(listings)} simboli ({format_elapsed(started_at)})", quiet)
    return listings


def dedupe_listings(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    result: list[Listing] = []
    for listing in listings:
        key = listing.yahoo_symbol.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(listing)
    return result


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def clean_isin(value: Any) -> str | None:
    if value in (None, "", "-"):
        return None
    isin = str(value).strip().upper()
    if not is_valid_isin(isin):
        return None
    return isin


def is_valid_isin(isin: str) -> bool:
    if not ISIN_RE.fullmatch(isin):
        return False

    digits = ""
    for char in isin:
        if char.isdigit():
            digits += char
        elif "A" <= char <= "Z":
            digits += str(ord(char) - 55)
        else:
            return False

    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return total % 10 == 0


def numeric(value: Any) -> float | None:
    value = clean_scalar(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def ratio_to_pct(value: Any) -> float | None:
    number = numeric(value)
    if number is None:
        return None
    return number * 100


def pct_to_ratio(value: Any) -> float | None:
    number = numeric(value)
    if number is None:
        return None
    return number / 100


def yield_to_pct(value: Any) -> float | None:
    number = numeric(value)
    if number is None:
        return None
    return number * 100 if abs(number) <= 1 else number


def safe_divide(numerator: Any, denominator: Any) -> float | None:
    num = numeric(numerator)
    den = numeric(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def safe_pct(numerator: Any, denominator: Any) -> float | None:
    ratio = safe_divide(numerator, denominator)
    if ratio is None:
        return None
    return ratio * 100


def free_cash_flow_from_components(operating_cash_flow: Any, capital_expenditure: Any) -> float | None:
    ocf = numeric(operating_cash_flow)
    capex = numeric(capital_expenditure)
    if ocf is None or capex is None:
        return None
    return ocf + capex if capex < 0 else ocf - capex


def latest_statement_value(statement: Any, *labels: str) -> float | None:
    if statement is None or not hasattr(statement, "empty") or statement.empty:
        return None
    for label in labels:
        if label not in statement.index:
            continue
        values = statement.loc[label]
        if hasattr(values, "dropna"):
            values = values.dropna()
            for value in values.tolist():
                number = numeric(value)
                if number is not None:
                    return number
        else:
            number = numeric(values)
            if number is not None:
                return number
    return None


def fetch_statement(statement_getter: Callable[[], Any]) -> Any:
    try:
        statement = statement_getter()
    except Exception:
        return None
    if statement is None or not hasattr(statement, "empty") or statement.empty:
        return None
    return statement


def fetch_isin(ticker: Any, retries: int, retry_sleep: float) -> str | None:
    for attempt in range(retries + 1):
        try:
            return clean_isin(ticker.get_isin())
        except Exception:
            if attempt >= retries:
                return None
            time.sleep(retry_sleep * (attempt + 1))
    return None


def metric(info: dict[str, Any], quote: dict[str, Any] | None, *keys: str) -> Any:
    for key in keys:
        if key in info and info[key] not in (None, "", [], {}):
            return info[key]
        if quote and key in quote and quote[key] not in (None, "", [], {}):
            return quote[key]
    return None


def fetch_one(
    listing: Listing,
    include_non_equity: bool,
    include_isin: bool,
    deep_fundamentals: bool,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    yf = load_yfinance()
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    info: dict[str, Any] = {}
    error = None
    ticker = yf.Ticker(listing.yahoo_symbol)

    for attempt in range(retries + 1):
        try:
            info = ticker.get_info() or {}
            break
        except Exception as exc:  # Yahoo can rate-limit or have missing symbols.
            error = str(exc)
            if attempt >= retries:
                info = {}
                break
            time.sleep(retry_sleep * (attempt + 1))

    quote = listing.quote or {}
    quote_type = clean_scalar(metric(info, quote, "quoteType", "quoteTypeDisp"))
    isin = fetch_isin(ticker, retries=retries, retry_sleep=retry_sleep) if include_isin and info else None

    if quote_type and quote_type != "EQUITY" and not include_non_equity:
        return {
            "market": listing.market,
            "symbol": listing.symbol,
            "yahoo_symbol": listing.yahoo_symbol,
            "isin": isin,
            "name": listing.name,
            "exchange": listing.exchange,
            "quote_type": quote_type,
            "listing_source": listing.source,
            "fundamental_source": "Yahoo Finance via yfinance",
            "fetched_at_utc": fetched_at,
            "status": "skipped_non_equity",
            "error": None,
            "_skip": True,
        }

    income_stmt = None
    balance_sheet = None
    cash_flow = None
    statements_loaded = False
    if deep_fundamentals and info:
        income_stmt = fetch_statement(lambda: ticker.ttm_income_stmt)
        if income_stmt is None:
            income_stmt = fetch_statement(lambda: ticker.financials)
        balance_sheet = fetch_statement(lambda: ticker.quarterly_balance_sheet)
        if balance_sheet is None:
            balance_sheet = fetch_statement(lambda: ticker.balance_sheet)
        cash_flow = fetch_statement(lambda: ticker.ttm_cash_flow)
        if cash_flow is None:
            cash_flow = fetch_statement(lambda: ticker.cash_flow)
        statements_loaded = any(statement is not None for statement in (income_stmt, balance_sheet, cash_flow))

    current_price = clean_scalar(metric(info, quote, "currentPrice", "regularMarketPrice", "postMarketPrice"))
    market_cap = metric(info, quote, "marketCap", "intradaymarketcap")

    total_revenue = first_nonempty(
        metric(info, quote, "totalRevenue", "totalrevenues.lasttwelvemonths"),
        latest_statement_value(income_stmt, "Total Revenue", "Operating Revenue"),
    )
    gross_profit = first_nonempty(
        metric(info, quote, "grossProfits", "grossprofit.lasttwelvemonths"),
        latest_statement_value(income_stmt, "Gross Profit"),
    )
    ebitda = first_nonempty(
        metric(info, quote, "ebitda", "ebitda.lasttwelvemonths"),
        latest_statement_value(income_stmt, "EBITDA", "Normalized EBITDA"),
    )
    ebit = first_nonempty(
        metric(info, quote, "ebit", "ebit.lasttwelvemonths"),
        latest_statement_value(income_stmt, "EBIT", "Operating Income", "Total Operating Income As Reported"),
    )
    operating_income = first_nonempty(
        metric(info, quote, "operatingIncome", "operatingincome.lasttwelvemonths"),
        latest_statement_value(income_stmt, "Operating Income", "Total Operating Income As Reported"),
    )
    net_income = first_nonempty(
        metric(info, quote, "netIncomeToCommon", "netincomeis.lasttwelvemonths"),
        latest_statement_value(
            income_stmt,
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income From Continuing And Discontinued Operation",
            "Net Income From Continuing Operation Net Minority Interest",
        ),
    )
    interest_expense = latest_statement_value(income_stmt, "Interest Expense", "Interest Expense Non Operating")

    total_debt = first_nonempty(
        metric(info, quote, "totalDebt", "totaldebt.lasttwelvemonths"),
        latest_statement_value(balance_sheet, "Total Debt"),
    )
    total_cash = first_nonempty(
        metric(info, quote, "totalCash", "totalcashandshortterminvestments.lasttwelvemonths"),
        latest_statement_value(
            balance_sheet,
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Federal Funds Sold",
        ),
    )
    net_debt = first_nonempty(
        metric(info, quote, "netDebt"),
        latest_statement_value(balance_sheet, "Net Debt"),
        None if numeric(total_debt) is None or numeric(total_cash) is None else numeric(total_debt) - numeric(total_cash),
    )
    current_assets = latest_statement_value(balance_sheet, "Current Assets", "Total Current Assets")
    current_liabilities = latest_statement_value(balance_sheet, "Current Liabilities", "Total Current Liabilities")
    working_capital = first_nonempty(
        latest_statement_value(balance_sheet, "Working Capital"),
        None
        if numeric(current_assets) is None or numeric(current_liabilities) is None
        else numeric(current_assets) - numeric(current_liabilities),
    )
    total_assets = latest_statement_value(balance_sheet, "Total Assets")
    total_liabilities = latest_statement_value(balance_sheet, "Total Liabilities Net Minority Interest")
    stockholders_equity = first_nonempty(
        latest_statement_value(balance_sheet, "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
        None if numeric(total_assets) is None or numeric(total_liabilities) is None else numeric(total_assets) - numeric(total_liabilities),
    )
    shares_outstanding = first_nonempty(
        metric(info, quote, "sharesOutstanding", "totalsharesoutstanding"),
        latest_statement_value(balance_sheet, "Ordinary Shares Number", "Share Issued"),
    )
    if numeric(market_cap) is None and numeric(current_price) is not None and numeric(shares_outstanding) is not None:
        market_cap = numeric(current_price) * numeric(shares_outstanding)
    book_value = first_nonempty(
        metric(info, quote, "bookValue", "bookvalueshare.lasttwelvemonths"),
        safe_divide(stockholders_equity, shares_outstanding),
    )

    operating_cash_flow = first_nonempty(
        metric(info, quote, "operatingCashflow", "cashfromoperations.lasttwelvemonths"),
        latest_statement_value(cash_flow, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    )
    capital_expenditure = first_nonempty(
        metric(info, quote, "capitalExpenditures", "capitalexpenditure.lasttwelvemonths"),
        latest_statement_value(cash_flow, "Capital Expenditure", "Capital Expenditure Reported"),
    )
    free_cash_flow = first_nonempty(
        free_cash_flow_from_components(operating_cash_flow, capital_expenditure),
        latest_statement_value(cash_flow, "Free Cash Flow"),
        metric(info, quote, "freeCashflow", "leveredfreecashflow.lasttwelvemonths"),
    )

    enterprise_value = first_nonempty(
        metric(info, quote, "enterpriseValue"),
        None
        if numeric(market_cap) is None or numeric(total_debt) is None or numeric(total_cash) is None
        else numeric(market_cap) + numeric(total_debt) - numeric(total_cash),
    )
    debt_to_equity_ratio = first_nonempty(
        pct_to_ratio(metric(info, quote, "debtToEquity", "totaldebtequity.lasttwelvemonths")),
        safe_divide(total_debt, stockholders_equity),
    )
    debt_to_equity_pct = first_nonempty(
        metric(info, quote, "debtToEquity", "totaldebtequity.lasttwelvemonths"),
        safe_pct(total_debt, stockholders_equity),
    )
    current_ratio = first_nonempty(
        metric(info, quote, "currentRatio", "currentratio.lasttwelvemonths"),
        safe_divide(current_assets, current_liabilities),
    )
    profit_margin_pct = first_nonempty(
        ratio_to_pct(metric(info, quote, "profitMargins", "netincomemargin.lasttwelvemonths")),
        safe_pct(net_income, total_revenue),
    )
    operating_margin_pct = first_nonempty(
        ratio_to_pct(metric(info, quote, "operatingMargins", "operatingmargin.lasttwelvemonths")),
        safe_pct(operating_income, total_revenue),
    )

    row = {
        "market": listing.market,
        "symbol": listing.symbol,
        "yahoo_symbol": listing.yahoo_symbol,
        "isin": isin,
        "name": first_nonempty(
            metric(info, quote, "longName"),
            metric(info, quote, "shortName"),
            metric(info, quote, "displayName"),
            listing.name,
        ),
        "currency": clean_scalar(metric(info, quote, "currency", "financialCurrency")),
        "exchange": clean_scalar(first_nonempty(metric(info, quote, "exchange"), listing.exchange)),
        "quote_type": quote_type,
        "country": clean_scalar(metric(info, quote, "country")),
        "sector": clean_scalar(metric(info, quote, "sector")),
        "industry": clean_scalar(metric(info, quote, "industry")),
        "current_price": clean_scalar(current_price),
        "market_cap": clean_scalar(market_cap),
        "enterprise_value": clean_scalar(enterprise_value),
        "pe_ttm": clean_scalar(metric(info, quote, "trailingPE", "trailingPe", "peratio.lasttwelvemonths")),
        "pe_forward": clean_scalar(metric(info, quote, "forwardPE")),
        "peg_ratio": clean_scalar(metric(info, quote, "pegRatio", "pegratio_5y")),
        "price_to_sales": first_nonempty(
            metric(info, quote, "priceToSalesTrailing12Months", "lastclosemarketcaptotalrevenue.lasttwelvemonths"),
            safe_divide(market_cap, total_revenue),
        ),
        "price_to_book": first_nonempty(
            metric(info, quote, "priceToBook", "pricebookratio.quarterly"),
            safe_divide(market_cap, stockholders_equity),
        ),
        "ev_to_revenue": first_nonempty(
            metric(info, quote, "enterpriseToRevenue", "lastclosetevtotalrevenue.lasttwelvemonths"),
            safe_divide(enterprise_value, total_revenue),
        ),
        "ev_to_ebitda": first_nonempty(
            metric(info, quote, "enterpriseToEbitda", "lastclosetevebitda.lasttwelvemonths"),
            safe_divide(enterprise_value, ebitda),
        ),
        "roe_pct": first_nonempty(
            ratio_to_pct(metric(info, quote, "returnOnEquity", "returnonequity.lasttwelvemonths")),
            safe_pct(net_income, stockholders_equity),
        ),
        "roa_pct": first_nonempty(
            ratio_to_pct(metric(info, quote, "returnOnAssets", "returnonassets.lasttwelvemonths")),
            safe_pct(net_income, total_assets),
        ),
        "roic_pct": safe_pct(ebit, first_nonempty(metric(info, quote, "investedCapital"), latest_statement_value(balance_sheet, "Invested Capital"))),
        "debt_to_equity_ratio": debt_to_equity_ratio,
        "debt_to_equity_pct": debt_to_equity_pct,
        "debt_to_assets_pct": safe_pct(total_debt, total_assets),
        "net_debt_to_ebitda": safe_divide(net_debt, ebitda),
        "interest_coverage": safe_divide(ebit, abs(numeric(interest_expense) or 0)),
        "current_ratio": clean_scalar(current_ratio),
        "quick_ratio": clean_scalar(metric(info, quote, "quickRatio", "quickratio.lasttwelvemonths")),
        "gross_margin_pct": first_nonempty(
            ratio_to_pct(metric(info, quote, "grossMargins", "grossprofitmargin.lasttwelvemonths")),
            safe_pct(gross_profit, total_revenue),
        ),
        "ebitda_margin_pct": first_nonempty(
            ratio_to_pct(metric(info, quote, "ebitdaMargins", "ebitdamargin.lasttwelvemonths")),
            safe_pct(ebitda, total_revenue),
        ),
        "profit_margin_pct": profit_margin_pct,
        "net_margin_pct": profit_margin_pct,
        "operating_margin_pct": operating_margin_pct,
        "asset_turnover": safe_divide(total_revenue, total_assets),
        "equity_multiplier": safe_divide(total_assets, stockholders_equity),
        "fcf_yield_pct": safe_pct(free_cash_flow, market_cap),
        "revenue_growth_pct": ratio_to_pct(metric(info, quote, "revenueGrowth", "quarterlyrevenuegrowth.quarterly")),
        "earnings_growth_pct": ratio_to_pct(metric(info, quote, "earningsGrowth", "epsgrowth.lasttwelvemonths")),
        "dividend_yield_pct": yield_to_pct(metric(info, quote, "dividendYield", "forward_dividend_yield")),
        "payout_ratio_pct": ratio_to_pct(metric(info, quote, "payoutRatio")),
        "dividend_rate": clean_scalar(metric(info, quote, "dividendRate", "trailingAnnualDividendRate")),
        "beta": clean_scalar(metric(info, quote, "beta")),
        "trailing_eps": clean_scalar(metric(info, quote, "trailingEps")),
        "book_value": clean_scalar(book_value),
        "total_revenue": clean_scalar(total_revenue),
        "gross_profit": clean_scalar(gross_profit),
        "ebitda": clean_scalar(ebitda),
        "ebit": clean_scalar(ebit),
        "operating_income": clean_scalar(operating_income),
        "net_income": clean_scalar(net_income),
        "total_debt": clean_scalar(total_debt),
        "net_debt": clean_scalar(net_debt),
        "total_cash": clean_scalar(total_cash),
        "current_assets": clean_scalar(current_assets),
        "current_liabilities": clean_scalar(current_liabilities),
        "working_capital": clean_scalar(working_capital),
        "total_assets": clean_scalar(total_assets),
        "total_liabilities": clean_scalar(total_liabilities),
        "stockholders_equity": clean_scalar(stockholders_equity),
        "operating_cash_flow": clean_scalar(operating_cash_flow),
        "capital_expenditure": clean_scalar(capital_expenditure),
        "free_cash_flow": clean_scalar(free_cash_flow),
        "shares_outstanding": clean_scalar(shares_outstanding),
        "float_shares": clean_scalar(metric(info, quote, "floatShares")),
        "held_percent_institutions_pct": ratio_to_pct(metric(info, quote, "heldPercentInstitutions")),
        "held_percent_insiders_pct": ratio_to_pct(metric(info, quote, "heldPercentInsiders")),
        "analyst_count": clean_scalar(metric(info, quote, "numberOfAnalystOpinions")),
        "target_mean_price": clean_scalar(metric(info, quote, "targetMeanPrice")),
        "recommendation_key": clean_scalar(metric(info, quote, "recommendationKey")),
        "statements_loaded": statements_loaded,
        "listing_source": listing.source,
        "fundamental_source": "Yahoo Finance via yfinance"
        + (" + statements" if statements_loaded else ""),
        "fetched_at_utc": fetched_at,
        "status": "ok" if info else "error",
        "error": error,
    }
    return row


def fetch_fundamentals(
    listings: list[Listing],
    include_non_equity: bool,
    include_sectorless: bool,
    include_isin: bool,
    deep_fundamentals: bool,
    workers: int,
    retries: int,
    retry_sleep: float,
    quiet: bool,
    checkpoint_path: str | None = None,
    checkpoint_format: str = "csv",
    checkpoint_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not listings:
        log_progress("Nessun simbolo da elaborare", quiet)
        return []

    listing_keys = {checkpoint_key_for_listing(listing) for listing in listings}
    raw_checkpoint_rows = list(checkpoint_rows or [])
    results: list[dict[str, Any]] = [
        row for row in raw_checkpoint_rows if checkpoint_key_for_row(row) in listing_keys
    ]
    ignored_checkpoint_rows = len(raw_checkpoint_rows) - len(results)
    if ignored_checkpoint_rows:
        log_progress(
            f"Checkpoint: ignoro {ignored_checkpoint_rows} record non presenti nella lista corrente",
            quiet,
        )
    checkpoint_keys = {key for row in results if (key := checkpoint_key_for_row(row))}
    pending_listings = [
        listing for listing in listings if checkpoint_key_for_listing(listing) not in checkpoint_keys
    ]
    if checkpoint_keys:
        log_progress(
            (
                f"Checkpoint caricato: {len(results)} record gia pronti, "
                f"{len(pending_listings)} simboli ancora da scaricare"
            ),
            quiet,
        )

    if not pending_listings:
        log_progress("Nessun nuovo fondamentale da scaricare", quiet)
        return sorted_rows(results)

    total = len(pending_listings)
    done = 0
    ok_count = 0
    error_count = 0
    skipped_count = 0
    sectorless_count = 0
    progress_step = max(1, min(50, total // 20 or 1))
    started_at = time.monotonic()

    mode = "profondi" if deep_fundamentals else "rapidi"
    isin_text = " con ISIN" if include_isin else ""
    sector_text = "" if include_sectorless else ", scarto righe senza settore"
    log_progress(f"Scarico fondamentali {mode}{isin_text} per {total} simboli con {workers} worker{sector_text}", quiet)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_one,
                listing,
                include_non_equity,
                include_isin,
                deep_fundamentals,
                retries,
                retry_sleep,
            ): listing
            for listing in pending_listings
        }
        for future in as_completed(futures):
            done += 1
            listing = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "market": listing.market,
                    "symbol": listing.symbol,
                    "yahoo_symbol": listing.yahoo_symbol,
                    "name": listing.name,
                    "exchange": listing.exchange,
                    "listing_source": listing.source,
                    "fundamental_source": "Yahoo Finance via yfinance",
                    "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": "error",
                    "error": str(exc),
                }

            skip = row.pop("_skip", False)
            status = row.get("status")
            if skip:
                skipped_count += 1
            elif not include_sectorless and not row.get("sector"):
                skipped_count += 1
                sectorless_count += 1
            else:
                results.append(row)
                if status == "ok":
                    ok_count += 1
                elif status == "error":
                    error_count += 1

            should_report = done == total or done % progress_step == 0
            if should_report:
                pct = (done / total) * 100
                log_progress(
                    (
                        f"Fondamentali {done}/{total} ({pct:.0f}%) "
                        f"ok={ok_count} errori={error_count} skip={skipped_count} "
                        f"senza_settore={sectorless_count} "
                        f"ultimo={listing.yahoo_symbol} elapsed={format_elapsed(started_at)}"
                    ),
                    quiet,
                )
                write_checkpoint(results, checkpoint_format, checkpoint_path, quiet)

    sectorless_summary = (
        f", {sectorless_count} senza settore scartati" if not include_sectorless else ""
    )
    log_progress(
        f"Fondamentali completati: {len(results)} record esportabili{sectorless_summary} ({format_elapsed(started_at)})",
        quiet,
    )
    return sorted_rows(results)


def fetch_listing_row(
    listing: Listing,
    include_isin: bool,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    isin = None
    if include_isin:
        yf = load_yfinance()
        ticker = yf.Ticker(listing.yahoo_symbol)
        try:
            ticker.get_info()
        except Exception:
            pass
        isin = fetch_isin(ticker, retries=retries, retry_sleep=retry_sleep)

    return {
        "market": listing.market,
        "symbol": listing.symbol,
        "yahoo_symbol": listing.yahoo_symbol,
        "isin": isin,
        "name": listing.name,
        "exchange": listing.exchange,
        "listing_source": listing.source,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "listed",
    }


def fetch_listing_rows(
    listings: list[Listing],
    include_isin: bool,
    workers: int,
    retries: int,
    retry_sleep: float,
    quiet: bool,
) -> list[dict[str, Any]]:
    if not include_isin:
        return [fetch_listing_row(item, False, retries, retry_sleep) for item in listings]

    total = len(listings)
    done = 0
    started_at = time.monotonic()
    progress_step = max(1, min(50, total // 20 or 1))
    rows: list[dict[str, Any]] = []
    log_progress(f"Scarico ISIN per {total} simboli list-only con {workers} worker", quiet)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_listing_row, listing, True, retries, retry_sleep): listing
            for listing in listings
        }
        for future in as_completed(futures):
            done += 1
            listing = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append(
                    {
                        "market": listing.market,
                        "symbol": listing.symbol,
                        "yahoo_symbol": listing.yahoo_symbol,
                        "name": listing.name,
                        "exchange": listing.exchange,
                        "listing_source": listing.source,
                        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "status": "error",
                        "error": str(exc),
                    }
                )
            if done == total or done % progress_step == 0:
                log_progress(
                    f"ISIN list-only {done}/{total} ultimo={listing.yahoo_symbol} elapsed={format_elapsed(started_at)}",
                    quiet,
                )

    return sorted(rows, key=lambda item: str(item.get("yahoo_symbol") or ""))


def write_csv(rows: list[dict[str, Any]], output_path: str | None) -> None:
    target = open(output_path, "w", encoding="utf-8", newline="") if output_path else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean_scalar(row.get(field)) for field in OUTPUT_FIELDS})
    finally:
        if output_path:
            target.close()


def write_jsonl(rows: list[dict[str, Any]], output_path: str | None) -> None:
    target = open(output_path, "w", encoding="utf-8") if output_path else sys.stdout
    try:
        for row in rows:
            payload = {field: clean_scalar(row.get(field)) for field in OUTPUT_FIELDS if field in row}
            target.write(json.dumps(payload, ensure_ascii=False) + "\n")
    finally:
        if output_path:
            target.close()


def write_json(rows: list[dict[str, Any]], output_path: str | None) -> None:
    payload = [{field: clean_scalar(row.get(field)) for field in OUTPUT_FIELDS if field in row} for row in rows]
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)


def write_rows(rows: list[dict[str, Any]], output_format: str, output_path: str | None) -> None:
    if output_format == "csv":
        write_csv(rows, output_path)
    elif output_format == "jsonl":
        write_jsonl(rows, output_path)
    elif output_format == "json":
        write_json(rows, output_path)
    else:
        raise ValueError(f"Unsupported output format: {output_format}")


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: str(item.get("yahoo_symbol") or ""))


def checkpoint_path_for(output_path: str | None) -> str | None:
    if not output_path:
        return None
    return f"{output_path}.partial"


def checkpoint_key_for_listing(listing: Listing) -> str:
    return f"{listing.market}:{listing.yahoo_symbol}".upper()


def checkpoint_key_for_row(row: dict[str, Any]) -> str | None:
    market = str(row.get("market") or "").strip()
    symbol = str(first_nonempty(row.get("yahoo_symbol"), row.get("symbol")) or "").strip()
    if not market or not symbol:
        return None
    return f"{market}:{symbol}".upper()


def dedupe_checkpoint_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in reversed(rows):
        key = checkpoint_key_for_row(row)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    result.reverse()
    return result


def read_rows(input_format: str, input_path: str) -> list[dict[str, Any]]:
    if input_format == "csv":
        with open(input_path, "r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if input_format == "jsonl":
        rows: list[dict[str, Any]] = []
        with open(input_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        rows.append(payload)
        return rows
    if input_format == "json":
        with open(input_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError("il checkpoint JSON deve contenere una lista")
        return [row for row in payload if isinstance(row, dict)]
    raise ValueError(f"Unsupported output format: {input_format}")


def prompt_yes_no(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        print(f"{question} {suffix} ", end="", file=sys.stderr, flush=True)
        answer = sys.stdin.readline()
        if answer == "":
            return default
        normalized = answer.strip().lower()
        if not normalized:
            return default
        if normalized in ("y", "yes", "s", "si"):
            return True
        if normalized in ("n", "no"):
            return False
        print("Rispondi con y/n.", file=sys.stderr, flush=True)


def load_checkpoint_rows(
    checkpoint_path: str | None,
    output_format: str,
    include_sectorless: bool,
    quiet: bool,
) -> list[dict[str, Any]]:
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return []

    try:
        rows = dedupe_checkpoint_rows(read_rows(output_format, checkpoint_path))
    except Exception as exc:
        log_progress(f"Checkpoint non leggibile ({checkpoint_path}): {exc}. Lo ignoro.", quiet)
        return []

    if not include_sectorless:
        rows = [row for row in rows if row.get("sector")]

    if not rows:
        log_progress(f"Checkpoint trovato ma senza righe riutilizzabili: {checkpoint_path}", quiet)
        return []

    if sys.stdin.isatty():
        resume = prompt_yes_no(
            (
                f"Trovato checkpoint {checkpoint_path} con {len(rows)} record. "
                "Vuoi riprendere da qui? Ctrl+C per annullare."
            ),
            default=True,
        )
    else:
        resume = True
        log_progress(
            f"Trovato checkpoint {checkpoint_path} con {len(rows)} record: riprendo automaticamente",
            quiet,
        )

    if resume:
        return rows

    log_progress("Checkpoint ignorato: il prossimo salvataggio lo sovrascrivera.", quiet)
    return []


def write_checkpoint(
    rows: list[dict[str, Any]],
    output_format: str,
    checkpoint_path: str | None,
    quiet: bool,
) -> None:
    if not checkpoint_path:
        return
    temp_path = f"{checkpoint_path}.tmp"
    checkpoint_rows = sorted_rows(dedupe_checkpoint_rows(rows))
    write_rows(checkpoint_rows, output_format=output_format, output_path=temp_path)
    os.replace(temp_path, checkpoint_path)
    log_progress(f"Checkpoint aggiornato: {len(checkpoint_rows)} record in {checkpoint_path}", quiet)


def remove_checkpoint(checkpoint_path: str | None, quiet: bool) -> None:
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return
    try:
        os.remove(checkpoint_path)
        log_progress(f"Checkpoint rimosso dopo export completato: {checkpoint_path}", quiet)
    except OSError as exc:
        log_progress(f"Export completato, ma non riesco a rimuovere il checkpoint {checkpoint_path}: {exc}", quiet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lista società quotate e metriche fondamentali correnti per Borsa Italiana, Xetra, LSE, NYSE o NASDAQ.",
    )
    parser.add_argument(
        "--market",
        required=True,
        type=normalize_market,
        help="Mercato: borsa, xetra, lse, nyse, nasdaq, all.",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl", "json"],
        default="csv",
        help="Formato output. Default: csv.",
    )
    parser.add_argument(
        "--output",
        help="Percorso file output. Se omesso, scrive su stdout.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita il numero di simboli. Utile per test veloci.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Richieste parallele a Yahoo Finance. Default prudente: 4.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry per ticker in caso di errore/rate limit. Default: 1.",
    )
    parser.add_argument(
        "--retry-sleep",
        type=float,
        default=2.0,
        help="Secondi di attesa base tra retry. Default: 2.",
    )
    parser.add_argument(
        "--include-etfs",
        action="store_true",
        help="Include ETF/ETP nelle liste NYSE/NASDAQ.",
    )
    parser.add_argument(
        "--include-non-common",
        action="store_true",
        help="Include rights, units, warrants, preferred e strumenti simili nelle liste NYSE/NASDAQ.",
    )
    parser.add_argument(
        "--include-borsa-gem",
        action="store_true",
        help="Include il Global Equity Market di Borsa Italiana, cioè i ticker .MI che iniziano per 1.",
    )
    parser.add_argument(
        "--include-non-equity",
        action="store_true",
        help="Mantiene anche quote Yahoo non classificate come EQUITY.",
    )
    parser.add_argument(
        "--include-sectorless",
        action="store_true",
        help="Mantiene anche ticker senza settore. Per default vengono scartati dall'export fondamentali.",
    )
    parser.add_argument(
        "--include-isin",
        action="store_true",
        help="Aggiunge la colonna ISIN con lookup per ticker. Piu lento e soggetto a disponibilita della fonte.",
    )
    parser.add_argument(
        "--deep-fundamentals",
        action="store_true",
        help="Scarica anche bilanci e cash flow Yahoo per riempire campi mancanti e calcolare metriche derivate.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Restituisce solo la lista dei simboli, senza fondamentali.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disabilita progress log su stderr.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit deve essere maggiore di zero")
    if args.workers <= 0:
        parser.error("--workers deve essere maggiore di zero")
    if args.retries < 0:
        parser.error("--retries non può essere negativo")

    checkpoint_path = None
    checkpoint_rows: list[dict[str, Any]] = []
    if not args.list_only:
        checkpoint_path = checkpoint_path_for(args.output)
        checkpoint_rows = load_checkpoint_rows(
            checkpoint_path=checkpoint_path,
            output_format=args.format,
            include_sectorless=args.include_sectorless,
            quiet=args.quiet,
        )

    log_progress(
        (
            f"Avvio export market={args.market} format={args.format} "
            f"limit={args.limit if args.limit is not None else 'nessuno'} "
            f"list_only={args.list_only} deep={args.deep_fundamentals} "
            f"isin={args.include_isin} include_sectorless={args.include_sectorless}"
        ),
        args.quiet,
    )

    listings = load_listings(
        market=args.market,
        include_etfs=args.include_etfs,
        include_non_common=args.include_non_common,
        include_borsa_gem=args.include_borsa_gem,
        retries=args.retries,
        retry_sleep=args.retry_sleep,
        limit=args.limit,
        quiet=args.quiet,
    )

    if args.list_only:
        log_progress(f"Preparo output lista-only per {len(listings)} simboli", args.quiet)
        rows = fetch_listing_rows(
            listings=listings,
            include_isin=args.include_isin,
            workers=args.workers,
            retries=args.retries,
            retry_sleep=args.retry_sleep,
            quiet=args.quiet,
        )
    else:
        rows = fetch_fundamentals(
            listings=listings,
            include_non_equity=args.include_non_equity,
            include_sectorless=args.include_sectorless,
            include_isin=args.include_isin,
            deep_fundamentals=args.deep_fundamentals,
            workers=args.workers,
            retries=args.retries,
            retry_sleep=args.retry_sleep,
            quiet=args.quiet,
            checkpoint_path=checkpoint_path,
            checkpoint_format=args.format,
            checkpoint_rows=checkpoint_rows,
        )

    destination = args.output or "stdout"
    log_progress(f"Scrivo {len(rows)} record in {destination}", args.quiet)
    write_rows(rows, output_format=args.format, output_path=args.output)
    remove_checkpoint(checkpoint_path, args.quiet)
    log_progress(f"Export completato: {len(rows)} record", args.quiet)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
