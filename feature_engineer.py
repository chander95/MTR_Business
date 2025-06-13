# feature_engineer.py
"""
Engineers new features from the processed Furnished Finder listing data.
Takes data from data/processed_ff_listings.csv and outputs to
data/engineered_ff_listings.csv.
"""

import pandas as pd
import numpy as np
import os
import re
from datetime import datetime

def engineer_features(input_csv_path: str, output_csv_path: str):
    """
    Reads a CSV, engineers new features, and saves the enhanced data to a new CSV.

    Args:
        input_csv_path (str): Path to the input CSV file (from data_processor.py).
        output_csv_path (str): Path to the output CSV file with engineered features.
    """
    print(f"Starting feature engineering from '{input_csv_path}'...")

    if not os.path.exists(input_csv_path):
        print(f"Error: Input CSV file not found at '{input_csv_path}'. "
              "Please run process_ff_data.py first.")
        return

    try:
        df = pd.read_csv(input_csv_path)
        print(f"Loaded {len(df)} listings for feature engineering.")
    except Exception as e:
        print(f"Error loading CSV from {input_csv_path}: {e}")
        return

    # --- Feature Engineering Logic ---

    # 1. is_available_now (Boolean)
    # FIX: Ensure the column is string type and handle NaN values before using .str accessor
    df['availability_status_text'] = df['availability_status_text'].astype(str).fillna('')
    df['is_available_now'] = df['availability_status_text'].str.contains(
        'available', case=False # na=False is no longer strictly needed after fillna
    )

    # 2. landlord_tenure_months (Numeric)
    # Converts "X years, Y months" string into total months.
    def parse_tenure_to_months(tenure_str):
        if pd.isna(tenure_str) or not isinstance(tenure_str, str):
            return np.nan
        years = 0
        months = 0
        
        # Look for years
        year_match = re.search(r'(\d+)\s*year', tenure_str, re.IGNORECASE)
        if year_match:
            years = int(year_match.group(1))
        
        # Look for months (ensure it's not part of "months" in "years")
        month_match = re.search(r'(\d+)\s*month', tenure_str, re.IGNORECASE)
        if month_match:
            months = int(month_match.group(1))
        
        return (years * 12) + months

    df['landlord_tenure_months'] = df['landlord_tenure'].apply(parse_tenure_to_months)

    # 3. age_of_listing_days (Numeric)
    # Calculates days since 'last_updated' to today.
    def calculate_listing_age(last_updated_str):
        if pd.isna(last_updated_str) or not isinstance(last_updated_str, str):
            return np.nan
        try:
            # Format: '05.07.2025' -> Month.Day.Year
            update_date = datetime.strptime(last_updated_str, '%m.%d.%Y')
            today = datetime.now()
            return (today - update_date).days
        except ValueError:
            return np.nan

    df['age_of_listing_days'] = df['last_updated'].apply(calculate_listing_age)

    # 4. price_per_sq_ft (Numeric)
    # Handle potential division by zero or NaN square_footage
    df['square_footage'] = pd.to_numeric(df['square_footage'], errors='coerce') # Ensure numeric
    df['price_per_sq_ft'] = np.where(
        (df['square_footage'].notna()) & (df['square_footage'] > 0),
        df['price_monthly_clean'] / df['square_footage'],
        np.nan
    )

    # 5. price_per_bedroom (Numeric)
    # Handle division by zero or NaN bedrooms (especially for studios where bedrooms is 0)
    df['bedrooms'] = pd.to_numeric(df['bedrooms'], errors='coerce') # Ensure numeric
    df['price_per_bedroom'] = np.where(
        (df['bedrooms'].notna()) & (df['bedrooms'] > 0), # Only calculate if bedrooms is greater than 0
        df['price_monthly_clean'] / df['bedrooms'],
        np.nan # Set to NaN for studios or if bedrooms is 0/null
    )

    # 6. has_description_space (Boolean)
    df['has_description_space'] = df['description_space'].notna() & (df['description_space'].astype(str).str.strip() != '')

    # 7. has_description_neighborhood (Boolean)
    df['has_description_neighborhood'] = df['description_neighborhood'].notna() & (df['description_neighborhood'].astype(str).str.strip() != '')

    # 8. has_host_name (Boolean)
    df['has_host_name'] = df['host_name'].notna() & (df['host_name'].astype(str).str.strip().str.lower() != 'n/a')

    # 9. has_photos (Boolean)
    df['has_photos'] = df['photos_count'] > 0

    # 10. has_reviews (Boolean)
    df['has_reviews'] = df['reviews_count'] > 0

    # 11. is_studio (Boolean)
    df['is_studio'] = df['property_type'].astype(str).str.contains('studio', na=False, case=False)

    # 12. min_stay_category (Categorical)
    def categorize_min_stay(months):
        if pd.isna(months):
            return 'Unknown'
        if months <= 3:
            return 'Short-Term'
        elif 3 < months <= 6:
            return 'Mid-Term'
        else:
            return 'Long-Term' # Greater than 6 months
    
    df['min_stay_category'] = df['min_stay_months'].apply(categorize_min_stay)


    # --- Save Engineered Data ---
    # Ensure output directory exists
    output_dir = os.path.dirname(output_csv_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        df.to_csv(output_csv_path, index=False, encoding='utf-8')
        print(f"Successfully engineered features and saved data to '{output_csv_path}'")
        print(f"Total listings processed: {len(df)}")
    except IOError as e:
        print(f"Error writing to CSV file {output_csv_path}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while saving engineered data: {e}")

if __name__ == "__main__":
    INPUT_PROCESSED_CSV = 'data/processed_ff_listings.csv'
    OUTPUT_ENGINEERED_CSV = 'data/engineered_ff_listings.csv'

    engineer_features(INPUT_PROCESSED_CSV, OUTPUT_ENGINEERED_CSV)