#!/usr/bin/env python3
"""
Calculate stock fitness scores from a fundamentals CSV and scoring configs.

Each config JSON maps one or more sectors to metric rules:
- sectors: list of sector names. An empty string marks the default config.
- industries: optional list of industry names. Industry configs take precedence.
- scores: list of metric rules

Each metric rule must contain:
- field: CSV column name
- weight: metric weight in the weighted average
- prefactor: multiplier applied before interpolation
- points: interpolation points as [value, score]
- penalty: fixed score penalty applied when the row has no usable value
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IDENTITY_FIELDS = [
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
]

FIXED_INFO_FIELDS = [
    "market_cap",
    "current_price",
]

SUMMARY_FIELDS = [
    "valid_score_weight_pct",
    "weighted_score_before_penalty",
    "missing_penalty",
    "fitness_score",
]

DERIVED_FIELDS = {
    "fcf_margin_pct",
    "operating_cash_flow_to_net_income",
    "cash_to_debt_pct",
    "net_cash_to_market_cap_pct",
}


@dataclass(frozen=True)
class ScoreRule:
    field: str
    weight: float
    prefactor: float
    points: list[tuple[float, float]]
    penalty: float


@dataclass(frozen=True)
class ScoreConfig:
    name: str
    path: Path
    sectors: tuple[str, ...]
    industries: tuple[str, ...]
    rules: list[ScoreRule]


@dataclass(frozen=True)
class ConfigSet:
    configs: list[ScoreConfig]
    industry_map: dict[str, ScoreConfig]
    sector_map: dict[str, ScoreConfig]
    default_config: ScoreConfig


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    if not text:
        return None

    try:
        number = float(text)
    except ValueError:
        return None

    return number if math.isfinite(number) else None


def clamp_score(value: float) -> float:
    return min(10.0, max(0.0, value))


def normalize_sector(value: Any) -> str:
    return str(value or "").strip().casefold()


def parse_optional_name_list(raw_items: Any, field_name: str, source_name: str) -> tuple[str, ...]:
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise ValueError(f"{source_name}: '{field_name}' deve contenere una lista")

    items = tuple(str(item or "").strip() for item in raw_items)
    if len({normalize_sector(item) for item in items}) != len(items):
        raise ValueError(f"{source_name}: valore duplicato in '{field_name}'")
    return items


def interpolate(value: float, points: list[tuple[float, float]]) -> float:
    ordered = sorted(points, key=lambda point: point[0])

    if value <= ordered[0][0]:
        return ordered[0][1]
    if value >= ordered[-1][0]:
        return ordered[-1][1]

    for (left_x, left_y), (right_x, right_y) in zip(ordered, ordered[1:]):
        if left_x <= value <= right_x:
            if right_x == left_x:
                return right_y
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)

    return ordered[-1][1]


def parse_points(raw_points: Any, field_name: str, source_name: str) -> list[tuple[float, float]]:
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise ValueError(f"{field_name}: 'points' deve contenere almeno due punti")

    points_by_x: dict[float, float] = {}
    for index, raw_point in enumerate(raw_points, start=1):
        if not isinstance(raw_point, list | tuple) or len(raw_point) != 2:
            raise ValueError(f"{field_name}: punto #{index} non valido, atteso [x, voto]")

        x = parse_number(raw_point[0])
        y = parse_number(raw_point[1])
        if x is None or y is None:
            raise ValueError(f"{field_name}: punto #{index} contiene valori non numerici")
        if x in points_by_x:
            print(
                f"Avviso: {source_name}/{field_name} contiene x duplicato nei points ({x}); "
                "uso l'ultimo valore.",
                file=sys.stderr,
            )

        points_by_x[x] = y

    points = list(points_by_x.items())
    if len(points) < 2:
        raise ValueError(f"{field_name}: servono almeno due punti x distinti")
    return points


def parse_rules(raw_rules: Any, source_name: str) -> list[ScoreRule]:
    if not isinstance(raw_rules, list):
        raise ValueError(f"{source_name}: 'scores' deve contenere una lista di regole")

    if not raw_rules:
        raise ValueError(f"{source_name}: 'scores' non puo essere vuoto")

    rules: list[ScoreRule] = []
    seen_fields: set[str] = set()
    for index, item in enumerate(raw_rules, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{source_name}: regola #{index}: atteso un oggetto JSON")

        field = str(item.get("field", "")).strip()
        if not field:
            raise ValueError(f"{source_name}: regola #{index}: campo 'field' mancante")
        if field in seen_fields:
            raise ValueError(f"{source_name}: field duplicato: {field}")

        weight = parse_number(item.get("weight"))
        prefactor = parse_number(item.get("prefactor"))
        penalty = parse_number(item.get("penalty", item.get("penality")))
        if weight is None:
            raise ValueError(f"{source_name}/{field}: 'weight' mancante o non numerico")
        if prefactor is None:
            raise ValueError(f"{source_name}/{field}: 'prefactor' mancante o non numerico")
        if penalty is None:
            raise ValueError(f"{source_name}/{field}: 'penalty' mancante o non numerico")

        rules.append(
            ScoreRule(
                field=field,
                weight=weight,
                prefactor=prefactor,
                points=parse_points(item.get("points"), field, source_name),
                penalty=penalty,
            )
        )
        seen_fields.add(field)

    return rules


def load_config_file(config_path: Path) -> ScoreConfig:
    with config_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    source_name = config_path.name
    if isinstance(payload, list):
        sectors = ("",)
        industries = ()
        raw_rules = payload
    elif isinstance(payload, dict):
        sectors = parse_optional_name_list(payload.get("sectors"), "sectors", source_name)
        industries = parse_optional_name_list(payload.get("industries"), "industries", source_name)
        if not sectors and not industries:
            raise ValueError(f"{source_name}: configura almeno 'sectors' o 'industries'")
        raw_rules = payload.get("scores")
    else:
        raise ValueError(f"{source_name}: struttura JSON non supportata")

    return ScoreConfig(
        name=source_name,
        path=config_path,
        sectors=sectors,
        industries=industries,
        rules=parse_rules(raw_rules, source_name),
    )


def load_configs(config_path: Path) -> ConfigSet:
    if config_path.is_dir():
        config_paths = sorted(config_path.glob("*.json"))
        if not config_paths:
            raise ValueError(f"Nessun file JSON trovato in {config_path}")
    else:
        config_paths = [config_path]

    configs = [load_config_file(path) for path in config_paths]
    industry_map: dict[str, ScoreConfig] = {}
    sector_map: dict[str, ScoreConfig] = {}
    default_config: ScoreConfig | None = None

    for config in configs:
        for industry in config.industries:
            normalized_industry = normalize_sector(industry)
            if normalized_industry == "":
                raise ValueError(f"{config.name}: industry vuota in 'industries'")

            existing_config = industry_map.get(normalized_industry)
            if existing_config is not None:
                raise ValueError(
                    f"Industry {industry!r} dichiarata sia in {existing_config.name} "
                    f"sia in {config.name}"
                )
            industry_map[normalized_industry] = config

        for sector in config.sectors:
            normalized_sector = normalize_sector(sector)
            if normalized_sector == "":
                if default_config is not None and default_config.path != config.path:
                    raise ValueError(
                        "Piu configurazioni dichiarano il settore vuoto di default: "
                        f"{default_config.name}, {config.name}"
                    )
                default_config = config
                continue

            existing_config = sector_map.get(normalized_sector)
            if existing_config is not None:
                raise ValueError(
                    f"Settore {sector!r} dichiarato sia in {existing_config.name} "
                    f"sia in {config.name}"
                )
            sector_map[normalized_sector] = config

    if default_config is None:
        if len(configs) == 1:
            default_config = configs[0]
        else:
            raise ValueError(
                "Nessuna configurazione di default: aggiungi una stringa vuota "
                "in 'sectors' a un JSON"
            )

    return ConfigSet(
        configs=configs,
        industry_map=industry_map,
        sector_map=sector_map,
        default_config=default_config,
    )


def select_config(row: dict[str, str], configs: ConfigSet) -> ScoreConfig:
    industry = normalize_sector(row.get("industry"))
    if industry in configs.industry_map:
        return configs.industry_map[industry]

    sector = normalize_sector(row.get("sector"))
    return configs.sector_map.get(sector, configs.default_config)


def format_number(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(value, 6)
    return f"{rounded:.6f}".rstrip("0").rstrip(".")


def safe_divide(numerator: Any, denominator: Any) -> float | None:
    num = parse_number(numerator)
    den = parse_number(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def safe_pct(numerator: Any, denominator: Any) -> float | None:
    ratio = safe_divide(numerator, denominator)
    if ratio is None:
        return None
    return ratio * 100


def cash_to_debt_pct(cash: Any, debt: Any) -> float | None:
    cash_number = parse_number(cash)
    debt_number = parse_number(debt)
    if cash_number is None or debt_number is None:
        return None
    if debt_number <= 0:
        if cash_number > 0:
            return 500.0
        if cash_number == 0:
            return 100.0
        return 0.0
    return cash_number / debt_number * 100


def operating_cash_flow_to_net_income(operating_cash_flow: Any, net_income: Any) -> float | None:
    net_income_number = parse_number(net_income)
    if net_income_number is None:
        return None
    if net_income_number <= 0:
        return 0.0

    operating_cash_flow_number = parse_number(operating_cash_flow)
    if operating_cash_flow_number is None:
        return None
    return operating_cash_flow_number / net_income_number


def derived_field_values(row: dict[str, str]) -> dict[str, float | None]:
    net_debt = parse_number(row.get("net_debt"))
    net_cash = None if net_debt is None else -net_debt
    return {
        "fcf_margin_pct": safe_pct(row.get("free_cash_flow"), row.get("total_revenue")),
        "operating_cash_flow_to_net_income": operating_cash_flow_to_net_income(
            row.get("operating_cash_flow"),
            row.get("net_income"),
        ),
        "cash_to_debt_pct": cash_to_debt_pct(row.get("total_cash"), row.get("total_debt")),
        "net_cash_to_market_cap_pct": safe_pct(net_cash, row.get("market_cap")),
    }


def with_derived_fields(row: dict[str, str]) -> dict[str, str]:
    enriched = dict(row)
    for field, value in derived_field_values(row).items():
        if parse_number(enriched.get(field)) is None and value is not None:
            enriched[field] = format_number(value)
    return enriched


def score_row(row: dict[str, str], config: ScoreConfig) -> dict[str, str]:
    output: dict[str, str] = {"fitness_config": config.name}
    weighted_sum = 0.0
    valid_weight = 0.0
    missing_penalty = 0.0
    total_weight = sum(rule.weight for rule in config.rules)

    for rule in config.rules:
        raw_value = parse_number(row.get(rule.field))
        if raw_value is None:
            output[f"{rule.field}_score"] = ""
            missing_penalty += rule.penalty
            continue

        normalized_value = raw_value * rule.prefactor
        partial_score = clamp_score(interpolate(normalized_value, rule.points))
        output[f"{rule.field}_score"] = format_number(partial_score)

        weighted_sum += partial_score * rule.weight
        valid_weight += rule.weight

    weighted_score = weighted_sum / valid_weight if valid_weight else 0.0
    valid_weight_pct = (valid_weight / total_weight * 100.0) if total_weight else 0.0
    fitness_score = clamp_score(weighted_score - missing_penalty)

    output["valid_score_weight_pct"] = format_number(valid_weight_pct)
    output["weighted_score_before_penalty"] = format_number(weighted_score)
    output["missing_penalty"] = format_number(missing_penalty)
    output["fitness_score"] = format_number(fitness_score)
    return output


def configured_fields(configs: ConfigSet) -> list[str]:
    fields: list[str] = []
    seen_fields: set[str] = set()
    for config in configs.configs:
        for rule in config.rules:
            if rule.field in seen_fields:
                continue
            fields.append(rule.field)
            seen_fields.add(rule.field)
    return fields


def build_output_fields(input_fields: list[str], configs: ConfigSet) -> list[str]:
    fields: list[str] = []

    for field in IDENTITY_FIELDS:
        if field in input_fields:
            fields.append(field)

    for field in FIXED_INFO_FIELDS:
        if field in input_fields and field not in fields:
            fields.append(field)

    fields.append("fitness_config")

    for field in configured_fields(configs):
        if field not in fields:
            fields.append(field)
        fields.append(f"{field}_score")

    fields.extend(SUMMARY_FIELDS)
    return fields


def write_scores(
    input_path: Path,
    output_path: Path | None,
    configs: ConfigSet,
) -> int:
    with input_path.open("r", encoding="utf-8-sig", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        if not reader.fieldnames:
            raise ValueError("Il CSV di input non contiene intestazioni")

        missing_columns = [
            field
            for field in configured_fields(configs)
            if field not in reader.fieldnames and field not in DERIVED_FIELDS
        ]
        if missing_columns:
            joined_columns = ", ".join(missing_columns)
            print(
                "Avviso: colonne configurate ma assenti nel CSV; "
                f"le tratto come metriche mancanti: {joined_columns}",
                file=sys.stderr,
            )

        output_fields = build_output_fields(reader.fieldnames, configs)
        target = (
            output_path.open("w", encoding="utf-8", newline="")
            if output_path
            else sys.stdout
        )

        row_count = 0
        try:
            writer = csv.DictWriter(target, fieldnames=output_fields, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                enriched_row = with_derived_fields(row)
                output_row = {field: enriched_row.get(field, "") for field in output_fields}
                output_row.update(score_row(enriched_row, select_config(enriched_row, configs)))
                writer.writerow(output_row)
                row_count += 1
        finally:
            if output_path:
                target.close()

    return row_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calcola un voto fitness 0-10 per stock da CSV fondamentali e JSON di scoring.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="CSV generato da market_fundamentals.py.",
    )
    parser.add_argument(
        "--config",
        "--config-dir",
        dest="config_path",
        default=Path("config"),
        type=Path,
        help="Directory con JSON di scoring, oppure singolo JSON. Default: config.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Percorso del CSV di output. Se omesso, scrive su stdout.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        configs = load_configs(args.config_path)
        row_count = write_scores(args.input, args.output, configs)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    if args.output:
        print(f"Export completato: {row_count} record -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
