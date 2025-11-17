"""Comprehensive validation utilities for pricing system inputs."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

import pandas as pd

from . import config

logger = logging.getLogger(__name__)

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"

ValidationDict = Dict[str, object]


def _build_result(errors: List[str], warnings: List[str], summary: Mapping[str, object]) -> ValidationDict:
    """Normalize validation output structure.

    Status precedence: FAIL when errors exist, WARN when warnings exist, otherwise PASS.
    """

    status = STATUS_PASS
    if errors:
        status = STATUS_FAIL
    elif warnings:
        status = STATUS_WARN

    return {"status": status, "errors": errors, "warnings": warnings, "summary": dict(summary)}


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> Tuple[List[str], List[str]]:
    missing = [col for col in required if col not in df.columns]
    errors: List[str] = []
    if missing:
        errors.append(f"Missing columns: {', '.join(missing)}")
    return errors, []


def validate_costs(df: pd.DataFrame) -> ValidationDict:
    """Validate cost data integrity and completeness."""

    required = ["sku", "total_cost", "material_cost", "labor_cost", "overhead_cost"]
    errors, warnings = _require_columns(df, required)
    if errors:
        logger.error("Cost validation failed due to missing columns: %s", errors)
        return _build_result(errors, warnings, {"checked_rows": len(df)})

    duplicates = df[df["sku"].duplicated()]
    if not duplicates.empty:
        msg = f"Duplicate SKU codes: {duplicates['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    numeric_cols = [col for col in required if col != "sku"]
    non_positive = df[(df[numeric_cols] <= 0).any(axis=1)]
    if not non_positive.empty:
        msg = f"Non-positive costs for SKUs: {non_positive['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    component_sum = df[["material_cost", "labor_cost", "overhead_cost"]].sum(axis=1)
    mismatched = df[(component_sum - df["total_cost"]).abs() > 0.01]
    if not mismatched.empty:
        msg = f"Cost components do not sum to total for SKUs: {mismatched['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    missing_costs = df[df[numeric_cols].isna().any(axis=1)]
    if not missing_costs.empty:
        msg = f"Missing cost data for SKUs: {missing_costs['sku'].unique().tolist()}"
        warnings.append(msg)
        logger.warning(msg)

    summary = {
        "checked_rows": len(df),
        "duplicate_skus": len(duplicates),
        "component_mismatches": len(mismatched),
        "missing_cost_rows": len(missing_costs),
    }
    return _build_result(errors, warnings, summary)


def validate_inventory(df: pd.DataFrame) -> ValidationDict:
    """Validate inventory integrity, freshness, and unit consistency."""

    required = ["sku", "batch_number", "production_date", "expiry_date", "quantity", "uom"]
    errors, warnings = _require_columns(df, required)
    if errors:
        logger.error("Inventory validation failed due to missing columns: %s", errors)
        return _build_result(errors, warnings, {"checked_rows": len(df)})

    df = df.copy()
    df["production_date"] = pd.to_datetime(df["production_date"], errors="coerce")
    df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce")

    invalid_dates = df[df["expiry_date"] <= df["production_date"]]
    if not invalid_dates.empty:
        msg = f"Expiry dates not after production for batches: {invalid_dates['batch_number'].tolist()}"
        errors.append(msg)
        logger.error(msg)

    today = pd.Timestamp.today().normalize()
    df["days_to_expiry"] = (df["expiry_date"] - today).dt.days

    non_positive_qty = df[df["quantity"] <= 0]
    if not non_positive_qty.empty:
        msg = f"Non-positive quantities for batches: {non_positive_qty['batch_number'].tolist()}"
        errors.append(msg)
        logger.error(msg)

    duplicate_batches = df[df["batch_number"].duplicated()]
    if not duplicate_batches.empty:
        msg = f"Duplicate batch numbers detected: {duplicate_batches['batch_number'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    aging_ok, aging_warn = config.AGING_THRESHOLDS.get("fresh", (7, 14))
    aging_critical = df[df["days_to_expiry"] > aging_warn]
    aging_warning = df[(df["days_to_expiry"] > aging_ok) & (df["days_to_expiry"] <= aging_warn)]
    if not aging_warning.empty:
        msg = f"Fresh aging warning for batches: {aging_warning['batch_number'].tolist()}"
        warnings.append(msg)
        logger.warning(msg)
    if not aging_critical.empty:
        msg = f"Fresh aging critical for batches: {aging_critical['batch_number'].tolist()}"
        errors.append(msg)
        logger.error(msg)

    uom_inconsistencies = []
    for sku, group in df.groupby("sku"):
        if group["uom"].nunique() > 1:
            uom_inconsistencies.append(sku)
    if uom_inconsistencies:
        msg = f"UOM inconsistencies for SKUs: {uom_inconsistencies}"
        errors.append(msg)
        logger.error(msg)

    summary = {
        "checked_rows": len(df),
        "invalid_date_rows": len(invalid_dates),
        "non_positive_quantities": len(non_positive_qty),
        "aging_warnings": len(aging_warning),
        "aging_critical": len(aging_critical),
        "uom_inconsistencies": len(uom_inconsistencies),
    }
    return _build_result(errors, warnings, summary)


def validate_approved_prices(df: pd.DataFrame) -> ValidationDict:
    """Validate approved price lists against cost and policy constraints."""

    required = [
        "sku",
        "approved_price",
        "cost",
        "minimum_margin",
        "price_floor",
        "price_ceiling",
        "effective_date",
    ]
    errors, warnings = _require_columns(df, required)
    if errors:
        logger.error("Approved price validation failed due to missing columns: %s", errors)
        return _build_result(errors, warnings, {"checked_rows": len(df)})

    df = df.copy()
    df["effective_date"] = pd.to_datetime(df["effective_date"], errors="coerce")

    price_threshold = df["cost"] * (1 + df["minimum_margin"])
    below_threshold = df[df["approved_price"] < price_threshold]
    if not below_threshold.empty:
        msg = f"Approved prices below minimum margin for SKUs: {below_threshold['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    invalid_floor_ceiling = df[df["price_floor"] > df["price_ceiling"]]
    if not invalid_floor_ceiling.empty:
        msg = f"Price floor exceeds ceiling for SKUs: {invalid_floor_ceiling['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    future_effective = df[df["effective_date"] > pd.Timestamp.today()]
    if not future_effective.empty:
        msg = f"Effective dates in the future for SKUs: {future_effective['sku'].unique().tolist()}"
        warnings.append(msg)
        logger.warning(msg)

    missing_prices = df[df["approved_price"].isna() | (df["approved_price"] <= 0)]
    if not missing_prices.empty:
        msg = f"Missing or invalid approved prices for SKUs: {missing_prices['sku'].unique().tolist()}"
        errors.append(msg)
        logger.error(msg)

    summary = {
        "checked_rows": len(df),
        "below_margin": len(below_threshold),
        "invalid_floor_ceiling": len(invalid_floor_ceiling),
        "future_effective_dates": len(future_effective),
        "missing_prices": len(missing_prices),
    }
    return _build_result(errors, warnings, summary)


def validate_sales_history(df: pd.DataFrame) -> ValidationDict:
    """Validate historical sales data integrity."""

    required = ["sku", "date", "quantity", "unit_price", "revenue", "cost", "margin"]
    errors, warnings = _require_columns(df, required)
    if errors:
        logger.error("Sales history validation failed due to missing columns: %s", errors)
        return _build_result(errors, warnings, {"checked_rows": len(df)})

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Detect date gaps per SKU
    gap_warnings = 0
    for sku, group in df.groupby("sku"):
        ordered = group.sort_values("date")
        gaps = ordered["date"].diff().dt.days.dropna()
        if not gaps.empty and gaps.max() > 1:
            gap_warnings += 1
            msg = f"Date gaps detected for SKU {sku}"
            warnings.append(msg)
            logger.warning(msg)

    # Outliers: sales > 3 std deviations from mean per SKU
    outlier_rows = []
    for sku, group in df.groupby("sku"):
        mean = group["quantity"].mean()
        std = group["quantity"].std(ddof=0)
        if std == 0:
            continue
        outliers = group[group["quantity"] > mean + 3 * std]
        outlier_rows.append(outliers)
        if not outliers.empty:
            msg = f"Outlier sales volumes for SKU {sku}: rows {outliers.index.tolist()}"
            warnings.append(msg)
            logger.warning(msg)
    outlier_rows_df = pd.concat(outlier_rows) if outlier_rows else pd.DataFrame(columns=df.columns)

    revenue_mismatch = df[abs(df["revenue"] - (df["quantity"] * df["unit_price"])) > 0.01]
    if not revenue_mismatch.empty:
        msg = f"Revenue mismatch for rows: {revenue_mismatch.index.tolist()}"
        errors.append(msg)
        logger.error(msg)

    margin_mismatch = df[abs(df["margin"] - (df["revenue"] - df["cost"])) > 0.01]
    if not margin_mismatch.empty:
        msg = f"Margin mismatch for rows: {margin_mismatch.index.tolist()}"
        errors.append(msg)
        logger.error(msg)

    negative_margins = df[df["margin"] < 0]
    if not negative_margins.empty:
        msg = f"Negative margins for SKUs: {negative_margins['sku'].unique().tolist()}"
        warnings.append(msg)
        logger.warning(msg)

    summary = {
        "checked_rows": len(df),
        "date_gap_skus": gap_warnings,
        "outlier_rows": len(outlier_rows_df),
        "revenue_mismatch_rows": len(revenue_mismatch),
        "margin_mismatch_rows": len(margin_mismatch),
        "negative_margin_rows": len(negative_margins),
    }
    return _build_result(errors, warnings, summary)


def validate_competitor_prices(df: pd.DataFrame) -> ValidationDict:
    """Validate competitor pricing data for freshness and plausibility."""

    required = ["date", "sku", "competitor", "competitor_sku", "price", "our_price"]
    errors, warnings = _require_columns(df, required)
    if errors:
        logger.error("Competitor price validation failed due to missing columns: %s", errors)
        return _build_result(errors, warnings, {"checked_rows": len(df)})

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    stale_threshold = pd.Timestamp.today().normalize() - pd.Timedelta(days=7)
    stale_rows = df[df["date"] < stale_threshold]
    if not stale_rows.empty:
        msg = f"Stale competitor prices (>7 days) for SKUs: {stale_rows['sku'].unique().tolist()}"
        warnings.append(msg)
        logger.warning(msg)

    unrealistic_changes = []
    for key, group in df.sort_values("date").groupby(["competitor", "sku"]):
        pct_change = group["price"].pct_change()
        flagged = group[pct_change.abs() > 0.5]
        if not flagged.empty:
            unrealistic_changes.append(flagged)
            msg = f"Unrealistic price change >50% for competitor {key[0]} SKU {key[1]}"
            warnings.append(msg)
            logger.warning(msg)
    unrealistic_df = pd.concat(unrealistic_changes) if unrealistic_changes else pd.DataFrame(columns=df.columns)

    missing_mapping = df[df["competitor_sku"].isna() | (df["competitor_sku"] == "")]
    if not missing_mapping.empty:
        msg = f"Missing competitor SKU mapping for rows: {missing_mapping.index.tolist()}"
        errors.append(msg)
        logger.error(msg)

    df["price_gap"] = df["our_price"] - df["price"]
    summary = {
        "checked_rows": len(df),
        "stale_rows": len(stale_rows),
        "unrealistic_changes": len(unrealistic_df),
        "missing_mappings": len(missing_mapping),
        "avg_price_gap": df["price_gap"].mean() if not df.empty else 0,
    }
    return _build_result(errors, warnings, summary)


def generate_validation_report(
    datasets: Mapping[str, pd.DataFrame], output_path: str | Path | None = None
) -> ValidationDict:
    """Run all validations, summarize, and optionally emit an Excel report."""

    output_path = Path(output_path) if output_path else config.OUTPUT_DIR / "validation_report.xlsx"

    results = {
        "costs": validate_costs(datasets.get("costs", pd.DataFrame())),
        "inventory": validate_inventory(datasets.get("inventory", pd.DataFrame())),
        "approved_prices": validate_approved_prices(datasets.get("approved_prices", pd.DataFrame())),
        "sales_history": validate_sales_history(datasets.get("sales_history", pd.DataFrame())),
        "competitor_prices": validate_competitor_prices(datasets.get("competitor_prices", pd.DataFrame())),
    }

    issues: List[Dict[str, object]] = []
    for name, result in results.items():
        for err in result["errors"]:
            issues.append({"dataset": name, "severity": "ERROR", "message": err})
        for warn in result["warnings"]:
            issues.append({"dataset": name, "severity": "WARNING", "message": warn})

    summary_rows = [
        {"dataset": name, **res["summary"], "status": res["status"]} for name, res in results.items()
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="SUMMARY", index=False)
        pd.DataFrame(issues).to_excel(writer, sheet_name="ISSUES", index=False)

    overall_status = STATUS_PASS
    if any(res["status"] == STATUS_FAIL for res in results.values()):
        overall_status = STATUS_FAIL
    elif any(res["status"] == STATUS_WARN for res in results.values()):
        overall_status = STATUS_WARN

    logger.info("Validation report generated at %s with status %s", output_path, overall_status)
    return {"status": overall_status, "errors": [], "warnings": [], "summary": results}
