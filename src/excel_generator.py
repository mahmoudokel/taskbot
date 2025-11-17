"""Excel workbook builder for the Dynamic Pricing System.

This module builds a production-ready Excel workbook that stitches together
configuration, pricing scenarios, outputs, approvals, and audit data for the
poultry dynamic pricing workflow. The workbook is created with openpyxl to
allow rich formatting, data validation, and named ranges while leveraging
``xlsxwriter`` utilities for range helpers.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from xlsxwriter.utility import xl_range  # type: ignore

from . import config

logger = logging.getLogger(__name__)

HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN_BORDER = Border(
    left=Side(border_style="thin", color="CCCCCC"),
    right=Side(border_style="thin", color="CCCCCC"),
    top=Side(border_style="thin", color="CCCCCC"),
    bottom=Side(border_style="thin", color="CCCCCC"),
)


class ExcelGenerator:
    """Create the full Excel reporting workbook with sample data and formatting."""

    workbook_name = "Poultry_Dynamic_Pricing_System.xlsx"

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workbook_path = self.output_dir / self.workbook_name

    def build_workbook(self) -> Path:
        """Generate the workbook with all required sheets and formatting."""
        logger.info("Building Excel workbook at %s", self.workbook_path)
        wb = Workbook()
        wb.remove(wb.active)

        config_lists = self._build_configuration_sheet(wb)
        self._build_dashboard_sheet(wb)
        self._build_scenarios_sheet(wb, config_lists)
        self._build_price_output_sheet(wb, config_lists)
        self._build_costs_sheet(wb)
        self._build_inventory_sheet(wb, config_lists)
        self._build_approved_prices_sheet(wb, config_lists)
        self._build_sales_history_sheet(wb, config_lists)
        self._build_competitor_prices_sheet(wb, config_lists)
        self._build_reports_sheet(wb)
        self._build_data_validation_sheet(wb)

        wb.save(self.workbook_path)
        logger.info("Workbook created successfully: %s", self.workbook_path)
        return self.workbook_path

    # Sheet builders -----------------------------------------------------------------
    def _build_dashboard_sheet(self, wb: Workbook) -> None:
        headers = ["Metric", "Value", "Trend", "Last Updated"]
        rows = [
            ["Total Revenue (SAR)", 1_250_000, "▲", date(2024, 6, 30)],
            ["Average Margin %", 0.1825, "▶", date(2024, 6, 30)],
            ["Forecast Accuracy", 0.91, "▲", date(2024, 6, 30)],
        ]
        currency_cols = {"B"}
        percent_cols = set()
        date_cols = {"D"}
        self._write_sheet(
            wb,
            "DASHBOARD",
            headers,
            rows,
            currency_cols=currency_cols,
            percent_cols=percent_cols,
            date_cols=date_cols,
            named_range_name="dashboard_table",
        )

    def _build_configuration_sheet(self, wb: Workbook) -> Dict[str, str]:
        ws = wb.create_sheet("CONFIGURATION")
        ws.freeze_panes = "A2"

        header = ["Parameter", "Value", "Notes"]
        rows = [
            ["VAT Rate", f"{config.VAT_RATE:.0%}", "Applied to all taxable prices"],
            ["Currency", config.CURRENCY, "All monetary fields in SAR"],
            ["Fresh Aging (days)", " - ".join(map(str, config.AGING_THRESHOLDS["fresh"])), "Quality gates"],
            ["Frozen Aging (days)", " - ".join(map(str, config.AGING_THRESHOLDS["frozen"])), "Quality gates"],
            ["Saudi Holidays", ", ".join(config.SAUDI_HOLIDAYS.keys()), "Configurable"],
            ["Ramadan Windows", ", ".join(str(year) for year, *_ in config.RAMADAN_DATES), "Forecast impact"],
        ]
        self._write_headers(ws, header)
        self._write_rows(ws, rows)
        self._format_sheet(ws, len(header), len(rows))

        # Supporting lists for data validation
        channel_start_row = len(rows) + 3
        self._add_lookup_list(ws, "Channels", list(config.CHANNELS), start_row=channel_start_row, start_col=1)
        category_start_row = channel_start_row
        self._add_lookup_list(ws, "Categories", list(config.PRODUCT_CATEGORIES), start_row=channel_start_row, start_col=3)
        regions = ["Central", "West", "East"]
        region_start_row = channel_start_row
        self._add_lookup_list(ws, "Regions", regions, start_row=channel_start_row, start_col=5)

        # Named ranges to reuse across other sheets
        channel_range = xl_range(channel_start_row + 1, 0, channel_start_row + len(config.CHANNELS), 0)
        category_range = xl_range(category_start_row + 1, 2, category_start_row + len(config.PRODUCT_CATEGORIES), 2)
        region_range = xl_range(region_start_row + 1, 4, region_start_row + len(regions), 4)
        wb.create_named_range("CHANNEL_LIST", ws, f"={ws.title}!{channel_range}")
        wb.create_named_range("CATEGORY_LIST", ws, f"={ws.title}!{category_range}")
        wb.create_named_range("REGION_LIST", ws, f"={ws.title}!{region_range}")

        return {
            "channels": "CHANNEL_LIST",
            "categories": "CATEGORY_LIST",
            "regions": "REGION_LIST",
        }

    def _build_scenarios_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = [
            "Scenario Name",
            "Channel",
            "Category",
            "Region",
            "Target Margin %",
            "Discount %",
            "Effective Date",
            "Notes",
        ]
        rows = [
            ["Baseline", "VSM", "Fresh-A", "Central", 0.18, 0.0, date(2024, 7, 1), "Default"],
            ["Eid Push", "Food Service", "Cutups Fresh", "West", 0.20, 0.05, date(2024, 7, 10), "Holiday uplift"],
            ["Aging Clearance", "Frozen", "Frozen-A", "East", 0.12, 0.08, date(2024, 7, 5), "Inventory aging"],
        ]
        self._write_sheet(
            wb,
            "SCENARIOS",
            headers,
            rows,
            percent_cols={"E", "F"},
            date_cols={"G"},
            named_range_name="scenario_table",
            data_validation={
                "B": lists["channels"],
                "C": lists["categories"],
                "D": lists["regions"],
            },
        )

    def _build_price_output_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = [
            "SKU",
            "Channel",
            "Category",
            "Region",
            "Base Cost (SAR)",
            "Suggested Price (SAR)",
            "VAT Included Price (SAR)",
            "Margin %",
            "Effective Date",
        ]
        rows = [
            [
                "Whole Chicken 900g",
                "VSM",
                "Fresh-A",
                "Central",
                12.5,
                15.9,
                18.285,
                0.21,
                date(2024, 7, 1),
            ],
            [
                "Breast Fillet 1kg",
                "Food Service",
                "Cutups Fresh",
                "West",
                24.0,
                29.5,
                33.925,
                0.19,
                date(2024, 7, 1),
            ],
            [
                "Drumsticks 1kg",
                "Frozen",
                "Frozen-A",
                "East",
                14.75,
                17.5,
                20.125,
                -0.02,
                date(2024, 7, 1),
            ],
        ]
        self._write_sheet(
            wb,
            "PRICE_OUTPUT",
            headers,
            rows,
            currency_cols={"E", "F", "G"},
            percent_cols={"H"},
            date_cols={"I"},
            conditional_negative_margin="H",
            named_range_name="price_output_table",
            data_validation={
                "B": lists["channels"],
                "C": lists["categories"],
                "D": lists["regions"],
            },
        )

    def _build_costs_sheet(self, wb: Workbook) -> None:
        headers = [
            "SKU",
            "Category",
            "Unit Cost (SAR)",
            "Freight (SAR)",
            "Packaging (SAR)",
            "Total Cost (SAR)",
            "Last Updated",
        ]
        rows = [
            ["Whole Chicken 900g", "Fresh-A", 11.0, 0.8, 0.7, 12.5, date(2024, 6, 28)],
            ["Breast Fillet 1kg", "Cutups Fresh", 21.0, 1.6, 1.4, 24.0, date(2024, 6, 28)],
            ["Drumsticks 1kg", "Frozen-A", 12.8, 1.2, 0.75, 14.75, date(2024, 6, 28)],
        ]
        self._write_sheet(
            wb,
            "COSTS",
            headers,
            rows,
            currency_cols={"C", "D", "E", "F"},
            date_cols={"G"},
            named_range_name="costs_table",
        )

    def _build_inventory_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = [
            "SKU",
            "Batch",
            "Category",
            "Age (Days)",
            "Aging Bucket",
            "On Hand Qty",
            "Region",
            "Cost (SAR)",
        ]
        rows = [
            ["Whole Chicken 900g", "WC-20240615", "Fresh-A", 5, "0-7", 420, "Central", 12.5],
            ["Breast Fillet 1kg", "BF-20240610", "Cutups Fresh", 12, "8-14", 260, "West", 24.0],
            ["Drumsticks 1kg", "DS-20240522", "Frozen-A", 38, "30-60", 310, "East", 14.75],
        ]
        self._write_sheet(
            wb,
            "INVENTORY",
            headers,
            rows,
            currency_cols={"H"},
            named_range_name="inventory_table",
            data_validation={
                "C": lists["categories"],
                "G": lists["regions"],
            },
        )

    def _build_approved_prices_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = ["SKU", "Channel", "Approved Price (SAR)", "Approval Date", "Approver"]
        rows = [
            ["Whole Chicken 900g", "VSM", 15.9, date(2024, 6, 30), "Pricing Manager"],
            ["Breast Fillet 1kg", "Food Service", 29.5, date(2024, 6, 30), "Director"],
            ["Drumsticks 1kg", "Frozen", 17.5, date(2024, 6, 30), "Pricing Manager"],
        ]
        self._write_sheet(
            wb,
            "APPROVED_PRICES",
            headers,
            rows,
            currency_cols={"C"},
            date_cols={"D"},
            named_range_name="approved_prices_table",
            data_validation={"B": lists["channels"]},
        )

    def _build_sales_history_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = [
            "Date",
            "SKU",
            "Channel",
            "Units Sold",
            "Net Sales (SAR)",
            "Promo Flag",
        ]
        rows = [
            [date(2024, 6, 20), "Whole Chicken 900g", "VSM", 180, 2860.0, "No"],
            [date(2024, 6, 21), "Breast Fillet 1kg", "Food Service", 140, 4130.0, "Yes"],
            [date(2024, 6, 22), "Drumsticks 1kg", "Frozen", 190, 3325.0, "No"],
        ]
        self._write_sheet(
            wb,
            "SALES_HISTORY",
            headers,
            rows,
            currency_cols={"E"},
            date_cols={"A"},
            named_range_name="sales_history_table",
            data_validation={"C": lists["channels"]},
        )

    def _build_competitor_prices_sheet(self, wb: Workbook, lists: Dict[str, str]) -> None:
        headers = [
            "Competitor",
            "Region",
            "SKU",
            "Channel",
            "Category",
            "Price (SAR)",
            "Date Captured",
        ]
        rows = [
            ["Retailer A", "Central", "Whole Chicken 900g", "VSM", "Fresh-A", 16.5, date(2024, 6, 25)],
            ["Distributor B", "East", "Drumsticks 1kg", "Frozen", "Frozen-A", 18.0, date(2024, 6, 25)],
            ["FoodService C", "West", "Breast Fillet 1kg", "Food Service", "Cutups Fresh", 30.0, date(2024, 6, 25)],
        ]
        self._write_sheet(
            wb,
            "COMPETITOR_PRICES",
            headers,
            rows,
            currency_cols={"F"},
            date_cols={"G"},
            named_range_name="competitor_prices_table",
            data_validation={
                "B": lists["regions"],
                "D": lists["channels"],
                "E": lists["categories"],
            },
        )

    def _build_reports_sheet(self, wb: Workbook) -> None:
        headers = ["Report Name", "Generated On", "Owner", "Location"]
        rows = [
            ["Weekly Pricing Pack", date(2024, 6, 30), "Pricing Analyst", "\\\\share\\pricing\\weekly"],
            ["Executive Dashboard", date(2024, 6, 30), "FP&A", "PowerBI Workspace"],
            ["Ops Playbook", date(2024, 6, 30), "Sales Ops", "SharePoint/Playbooks"],
        ]
        self._write_sheet(
            wb,
            "REPORTS",
            headers,
            rows,
            date_cols={"B"},
            named_range_name="reports_table",
        )

    def _build_data_validation_sheet(self, wb: Workbook) -> None:
        headers = ["Check", "Status", "Details"]
        rows = [
            ["Schema", "OK", "All required columns present"],
            ["Nulls", "OK", "No missing values in mandatory fields"],
            ["Ranges", "OK", "Prices within configured thresholds"],
        ]
        self._write_sheet(
            wb,
            "DATA_VALIDATION",
            headers,
            rows,
            named_range_name="data_validation_table",
        )

    # Helpers ------------------------------------------------------------------------
    def _write_sheet(
        self,
        wb: Workbook,
        name: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[object]],
        *,
        currency_cols: Iterable[str] | None = None,
        percent_cols: Iterable[str] | None = None,
        date_cols: Iterable[str] | None = None,
        conditional_negative_margin: str | None = None,
        named_range_name: str | None = None,
        data_validation: Dict[str, str] | None = None,
    ) -> None:
        ws = wb.create_sheet(name)
        self._write_headers(ws, headers)
        self._write_rows(ws, rows)
        self._apply_number_formats(ws, currency_cols, percent_cols, date_cols)
        self._format_sheet(ws, len(headers), len(rows))
        if conditional_negative_margin:
            self._apply_negative_margin_rule(ws, conditional_negative_margin, len(rows))
        if named_range_name:
            self._create_named_range(wb, ws, named_range_name, len(headers), len(rows))
        if data_validation:
            self._apply_data_validation(ws, data_validation, len(rows))

    def _write_headers(self, ws, headers: Sequence[str]) -> None:
        for col_idx, title in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=title)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center")

    def _write_rows(self, ws, rows: Sequence[Sequence[object]]) -> None:
        for row in rows:
            ws.append(list(row))

    def _apply_number_formats(
        self,
        ws,
        currency_cols: Iterable[str] | None,
        percent_cols: Iterable[str] | None,
        date_cols: Iterable[str] | None,
    ) -> None:
        currency_cols = set(currency_cols or [])
        percent_cols = set(percent_cols or [])
        date_cols = set(date_cols or [])

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
            for cell in row:
                col_letter = get_column_letter(cell.col_idx)
                if col_letter in currency_cols:
                    cell.number_format = "#,##0.00"  # SAR
                if col_letter in percent_cols:
                    cell.number_format = "0.00%"
                if col_letter in date_cols and isinstance(cell.value, date):
                    cell.number_format = "DD-MMM-YYYY"
                cell.border = THIN_BORDER
                cell.alignment = Alignment(vertical="center")

    def _format_sheet(self, ws, column_count: int, row_count: int) -> None:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(column_count)}{row_count + 1}"
        self._auto_size_columns(ws)

    def _auto_size_columns(self, ws) -> None:
        for col_idx, column_cells in enumerate(ws.columns, start=1):
            max_length = 0
            for cell in column_cells:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            adjusted_width = max_length + 2
            ws.column_dimensions[get_column_letter(col_idx)].width = adjusted_width

    def _apply_negative_margin_rule(self, ws, column_letter: str, row_count: int) -> None:
        range_str = f"{column_letter}2:{column_letter}{row_count + 1}"
        ws.conditional_formatting.add(
            range_str,
            CellIsRule(operator="lessThan", formula=["0"], stopIfTrue=True, fill=PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")),
        )

    def _create_named_range(self, wb: Workbook, ws, name: str, column_count: int, row_count: int) -> None:
        range_ref = xl_range(1, 0, row_count + 1, column_count - 1)
        wb.create_named_range(name, ws, f"={ws.title}!{range_ref}")

    def _apply_data_validation(self, ws, validations: Dict[str, str], row_count: int) -> None:
        for col_letter, named_range in validations.items():
            dv = DataValidation(type="list", formula1=f"={named_range}", allow_blank=True, showDropDown=True)
            ws.add_data_validation(dv)
            dv.ranges.append(f"{col_letter}2:{col_letter}{row_count + 1}")

    def _add_lookup_list(self, ws, title: str, values: Sequence[str], *, start_row: int, start_col: int) -> None:
        header_cell = ws.cell(row=start_row, column=start_col, value=title)
        header_cell.fill = HEADER_FILL
        header_cell.font = HEADER_FONT
        for offset, value in enumerate(values, start=1):
            ws.cell(row=start_row + offset, column=start_col, value=value)


def main() -> None:
    """Generate the Excel workbook in the configured output directory."""
    generator = ExcelGenerator()
    generator.build_workbook()


if __name__ == "__main__":
    main()
