# process_ff_data.py
"""
Processes raw JSON listing data scraped from Furnished Finder,
flattens it, and saves it into a clean CSV file.
Includes extraction of minimum distance to a facility.
"""

import os
import json
import csv
import re 

def process_and_save_to_csv(input_dir: str, output_csv_path: str):
    """
    Reads JSON files from an input directory, processes the data,
    and writes it to a CSV file.

    Args:
        input_dir (str): Path to the directory containing raw JSON listing files.
        output_csv_path (str): Path to the output CSV file.
    """
    print(f"Starting data processing from '{input_dir}'...")

    csv_headers = [
        'property_id',
        'url',
        'title',
        'price_monthly_clean',
        'bedrooms',
        'bathrooms',
        'property_type',
        'square_footage',
        'min_stay_months',
        'utilities_included',
        'availability_status_text',
        'landlord_tenure',
        'host_name',
        'last_updated',
        'general_location_detail_page',
        'description_space',
        'description_neighborhood',
        'amenities', 
        'closest_facilities_listed', # This will still be just names
        'min_distance_miles', # NEW FIELD: Minimum distance to a listed facility
        'reviews_count',
        'photos_count', 
        'first_photo_url' 
    ]

    all_processed_listings = []

    output_dir = os.path.dirname(output_csv_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    json_files_processed_count = 0
    for filename in os.listdir(input_dir):
        if filename.endswith('.json') and filename.startswith('listing_detail_'):
            file_path = os.path.join(input_dir, filename)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    json_files_processed_count += 1
                    
                    # Safely get photos_urls
                    photos_urls = raw_data.get('photos_urls', [])
                    
                    # Calculate min_distance_miles
                    min_distance = None
                    if raw_data.get('closest_facilities_listed'):
                        distances = []
                        for facility in raw_data['closest_facilities_listed']:
                            dist_text = facility.get('distance_text')
                            if dist_text:
                                match = re.search(r'(\d+\.?\d*)\s*miles?', dist_text)
                                if match:
                                    distances.append(float(match.group(1)))
                        if distances:
                            min_distance = min(distances)
                    
                    # Process and flatten the data for CSV
                    processed_row = {
                        'property_id': raw_data.get('property_id'),
                        'url': raw_data.get('url'),
                        'title': raw_data.get('title'),
                        'price_monthly_clean': raw_data.get('price_monthly_clean'),
                        'bedrooms': raw_data.get('bedrooms'),
                        'bathrooms': raw_data.get('bathrooms'),
                        'property_type': raw_data.get('property_type'),
                        'square_footage': raw_data.get('square_footage'),
                        'min_stay_months': raw_data.get('min_stay_months'),
                        'utilities_included': raw_data.get('utilities_included'),
                        'availability_status_text': raw_data.get('availability_status_text'),
                        'landlord_tenure': raw_data.get('landlord_tenure'),
                        'host_name': raw_data.get('host_name'),
                        'last_updated': raw_data.get('last_updated'),
                        'general_location_detail_page': raw_data.get('general_location_detail_page'),
                        'description_space': raw_data.get('description_space'),
                        'description_neighborhood': raw_data.get('description_neighborhood'),
                        
                        'amenities': ", ".join(raw_data.get('amenities', [])),
                        
                        'closest_facilities_listed': ", ".join([
                            f['name'] for f in raw_data.get('closest_facilities_listed', []) if 'name' in f
                        ]),
                        'min_distance_miles': min_distance, # Add the new field
                        
                        'reviews_count': raw_data.get('reviews_count'),
                        
                        'photos_count': len(photos_urls), 
                        'first_photo_url': photos_urls[0] if photos_urls else None 
                    }
                    all_processed_listings.append(processed_row)

            except json.JSONDecodeError as e:
                print(f"Error decoding JSON from {filename}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred while processing {filename}: {e}")

    if not all_processed_listings:
        print("No valid JSON listing files found or processed. CSV will not be created.")
        return

    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
            
            writer.writeheader()
            writer.writerows(all_processed_listings)
        print(f"\nSuccessfully processed {json_files_processed_count} JSON files.")
        print(f"Data saved to CSV: '{output_csv_path}'")
    except IOError as e:
        print(f"Error writing to CSV file {output_csv_path}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while writing CSV: {e}")

if __name__ == "__main__":
    INPUT_JSON_DIR = 'data/raw_ff_listings'
    OUTPUT_CSV_FILE = 'data/processed_ff_listings.csv'

    process_and_save_to_csv(INPUT_JSON_DIR, OUTPUT_CSV_FILE)