# Dynamic Pricing System for Poultry Business

This repository provides a production-ready scaffold for a dynamic pricing system tailored to poultry products. It includes configuration, data processing, demand forecasting, price optimization, competitor analysis, and Excel export utilities.

## Project Structure
- `poultry_pricing/`
  - `data/`: Input data files such as sales history, inventory, and costs.
  - `models/`: Serialized machine learning models.
  - `output/`: Generated price lists and forecasts.
  - `logs/`: Application logs.
- `src/`
  - `config.py`: Centralized configuration for channels, products, holidays, aging thresholds, and file paths.
  - `data_validation.py`: Validation utilities for raw datasets.
  - `data_processor.py`: Data loading, normalization, and enrichment routines.
  - `demand_forecasting.py`: Baseline demand forecasting components.
  - `price_optimizer.py`: Pricing logic leveraging costs, forecasts, and business rules.
  - `competitor_analysis.py`: Summaries of competitor pricing intelligence.
  - `excel_generator.py`: Excel export helper for optimized price lists.
  - `main.py`: CLI entry point orchestrating the workflow.
- `requirements.txt`: Python dependencies for the pricing stack.

## Getting Started
1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Place required data files in `poultry_pricing/data/`.
4. Run the workflow:
   ```bash
   python -m src.main
   ```

## Notes
- Update `src/config.py` to reflect operational holidays, Ramadan dates, and margin assumptions as needed.
- Model training, evaluation, and deployment hooks can be extended within the existing module scaffolding.
