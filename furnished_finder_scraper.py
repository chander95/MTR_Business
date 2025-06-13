# furnished_finder_scraper.py
"""
Scrapes Furnished Finder search results to get listing URLs and basic card info,
then navigates to individual listing pages for comprehensive data.

Designed to be robust against dynamic content and some anti-bot measures.

Requires:
    selenium
    webdriver-manager
    beautifulsoup4
    requests (for initial URL validation or if some API calls are found)
"""

from __future__ import annotations
import random
import time
import re
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin 

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException

from webdriver_manager.chrome import ChromeDriverManager

# Import configurations and utility function
# Assuming config.py and utils.py are in the same directory or accessible via PYTHONPATH
from config import USER_AGENTS, FF_BASE_URL, \
                   UTILITIES_INCLUDED_KEYWORDS, UTILITIES_EXCLUDED_KEYWORDS
from utils import clean_price 

class FurnishedFinderScraper:
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.base_url = FF_BASE_URL
        self.initial_headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.5',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.google.com/'
        }

    def _build_driver(self) -> webdriver.Chrome:
        """
        Builds and returns a Selenium Chrome WebDriver with stealth options.
        """
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option('useAutomationExtension', False)
        
        opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        
        driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': self.initial_headers})
        
        return driver

    def _start_driver(self):
        """Initializes the WebDriver if not already running."""
        if not self.driver:
            self.driver = self._build_driver()

    def _quit_driver(self):
        """Quits the WebDriver if it's running."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def get_listing_urls(self, city: str, state: str, max_pages: int = 1) -> List[Dict[str, Any]]:
        """
        Scrapes search result pages for a given city/state to collect individual listing URLs
        AND basic card information (title, location, price, availability) using Selenium directly.
        """
        self._start_driver()
        print("WebDriver initialized for search.") 

        all_listings_from_search: List[Dict[str, Any]] = []
        unique_urls: set[str] = set() 

        search_path = f"housing/us--{state.lower()}--{city.lower()}"
        base_search_url = urljoin(self.base_url, search_path)


        print(f"Starting search for {city}, {state} from {base_search_url}")

        for page in range(1, max_pages + 1):
            url = f"{base_search_url}?p={page}" # Append page parameter
            print(f"Navigating to search page: {url}")
            try:
                self.driver.get(url)

                # --- CRUCIAL WAIT: Target the main listings grid container (#serp_default_view) ---
                # And also wait for at least one listing card (div.w-full.max-w-full) to be present
                main_container_selector = '#serp_default_view' 
                listing_card_selector = 'div.w-full.max-w-full.rounded-md.border-transparent[data-testid="property-cards"]'

                WebDriverWait(self.driver, 30).until( # Increased timeout for robustness
                    EC.all_of( 
                        EC.presence_of_element_located((By.CSS_SELECTOR, main_container_selector)),
                        EC.presence_of_element_located((By.CSS_SELECTOR, listing_card_selector))
                    )
                )
                print(f"Main container and at least one listing card loaded on page {page}.")

                # --- NEW STRATEGY: Use Selenium to find all card elements, then extract content ---
                # This directly interacts with the rendered DOM, bypassing potential BeautifulSoup sync issues.
                selenium_card_elements = self.driver.find_elements(By.CSS_SELECTOR, listing_card_selector)
                
                if not selenium_card_elements:
                    print(f"No listing cards found on {city}, page {page} with selector '{listing_card_selector}'. Ending pagination.")
                    break

                for card_element in selenium_card_elements:
                    full_url = None
                    try:
                        # Attempt to find the link directly using Selenium within the card element
                        link_element = card_element.find_element(By.CSS_SELECTOR, 'a[data-testid="native-link"]')
                        full_url = urljoin(self.base_url, link_element.get_attribute('href'))
                    except NoSuchElementException:
                        # Fallback: if data-testid="native-link" is not found, try a more general XPath
                        try:
                            link_element = card_element.find_element(By.XPATH, './/a[contains(@href, "/property/")]')
                            full_url = urljoin(self.base_url, link_element.get_attribute('href'))
                        except NoSuchElementException:
                            print(f"Could not find valid <a> tag with href in card element. Skipping card.")
                            continue # Skip if no valid link found in this card

                    if full_url in unique_urls:
                        continue 
                    unique_urls.add(full_url)

                    # Now, get the HTML of the current card element to parse other details with BeautifulSoup
                    card_soup = BeautifulSoup(card_element.get_attribute('outerHTML'), "lxml")

                    # --- Extracting details from the search result card using card_soup ---
                    title = "N/A"
                    title_elem = card_soup.select_one('div[data-testid^="property-card-"], h3.font-semibold, div.text-base.font-semibold') 
                    if title_elem:
                        title = title_elem.get_text(strip=True)

                    location = "N/A"
                    loc_span = card_soup.select_one('span.text-grey-dark.text-se')
                    if loc_span:
                        location = loc_span.get_text(strip=True)

                    price_raw = None
                    price_val = None
                    price_container = card_soup.select_one('div.flex.h-8.items-center.rounded-full.bg-white')
                    if price_container:
                        price_div = price_container.select_one('div.text-black') 
                        if price_div:
                            price_raw = price_div.get_text(strip=True)
                            price_val = clean_price(price_raw)
                    
                    availability_text = None
                    avail_span = card_soup.select_one('span.mb-2.mt-1.leading-tight')
                    if avail_span:
                        availability_text = avail_span.get_text(strip=True)


                    all_listings_from_search.append({
                        "title": title,
                        "location_card": location, 
                        "url": full_url,
                        "price_raw_card": price_raw,
                        "price_clean_card": price_val,
                        "availability_text_card": availability_text,
                        "scrape_time_card": time.time()
                    })
                
                print(f"Processed {len(selenium_card_elements)} listing cards from page {page}. Total unique URLs found: {len(unique_urls)}")

            except TimeoutException:
                print(f"⚠️ Timed-out waiting for elements on {city}, page {page} after 30 seconds. "
                      "This might mean no more results, slow loading, or aggressive blocking.")
                break
            except WebDriverException as e:
                print(f"An unexpected WebDriver error occurred while loading page {page}: {e}")
                break

            time.sleep(random.uniform(3, 7))

        self._quit_driver() 
        print("WebDriver quit after search.")
        return all_listings_from_search 

    def parse_listing_details(self, listing_url: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single FurnishedFinder listing page for comprehensive details.
        """
        self._start_driver()
        print(f"Navigating to listing details: {listing_url}")
        try:
            self.driver.get(listing_url)
            
            # Wait for the main title to ensure page is loaded (primary page load indicator)
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.text-2xl.font-semibold'))
            )
            # Add a specific wait for the call-to-action panel itself, as it contains critical info
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="call-to-action"]'))
            )
            print("Listing detail page loaded. Extracting full details...")

        except TimeoutException:
            print(f"⚠️ Timed-out waiting for main title or call-to-action panel on listing page {listing_url}.")
            self._quit_driver()
            return None
        except WebDriverException as e:
            print(f"An unexpected WebDriver error occurred while loading page {listing_url}: {e}")
            self._quit_driver()
            return None

        html = self.driver.page_source
        soup = BeautifulSoup(html, "lxml")

        listing_data = {
            'url': listing_url,
            'title': None,
            'price_monthly_raw': None,
            'price_monthly_clean': None,
            'utilities_included': None, 
            'bedrooms': None,
            'bathrooms': None,
            'description_space': None, 
            'description_neighborhood': None, 
            'amenities': [],
            'availability_calendar_raw': [], 
            'general_location_detail_page': None, 
            'host_name': None, 
            'property_type': None,
            'square_footage': None,
            'min_stay_months': None, 
            'property_id': None, 
            'last_updated': None,
            'landlord_tenure': None, 
            'availability_status_text': None, 
            'closest_facilities_listed': [], 
            'reviews_count': 0, 
            'photos_urls': [], 
            'scrape_time_detail': time.time()
        }

        # --- EXTRACTING DETAILS FROM THE LISTING PAGE ---

        # Main Title (h1.text-2xl.font-semibold)
        try:
            title_tag = soup.select_one('h1.text-2xl.font-semibold')
            if title_tag:
                listing_data['title'] = title_tag.get_text(strip=True)
        except Exception:
            pass 

        # Property ID (p tag containing "Property ID : ")
        try:
            prop_id_tag = soup.find('p', class_='font-semibold', string=lambda text: text and 'Property ID' in text)
            if prop_id_tag:
                raw_id = prop_id_tag.get_text(strip=True)
                match = re.search(r'Property ID:\s*(\S+)', raw_id)
                if match:
                    listing_data['property_id'] = match.group(1)
                else:
                    listing_data['property_id'] = raw_id 
        except Exception:
            pass 

        # Last Updated (p tag containing "Last updated ")
        try:
            last_updated_tag = soup.find('p', class_='text-sm', string=lambda text: text and 'Last updated' in text)
            if last_updated_tag:
                listing_data['last_updated'] = last_updated_tag.get_text(strip=True).replace('Last updated ', '')
        except Exception:
            pass 

        # Location from detail page (p tag like "Apartment in Cambridge , Massachusetts")
        try:
            overview_section = soup.select_one('div[data-testid="section-pdp_overview"]')
            if overview_section:
                loc_tag = overview_section.find('p', class_='text-sm', string=lambda text: text and ',' in text and ('Massachusetts' in text or 'MA' in text))
                if loc_tag:
                    listing_data['general_location_detail_page'] = loc_tag.get_text(strip=True)
        except Exception:
            pass
        
        # Landlord Tenure (Parsing from the "About the landlord" section)
        try:
            about_landlord_section = soup.find('h2', string=lambda t: t and 'About the landlord' in t)
            if about_landlord_section:
                landlord_info_block = about_landlord_section.find_next_sibling('div') 
                if landlord_info_block:
                    tenure_span = landlord_info_block.find('span', class_='font-semibold', string=lambda t: t and 'Tenure:' in t)
                    if tenure_span:
                        listing_data['landlord_tenure'] = tenure_span.get_text(strip=True).replace('Tenure:', '').strip()
                    else: 
                        raw_text = landlord_info_block.get_text(strip=True)
                        match = re.search(r'Tenure:\s*(\d+\s*year(?:s)?(?:,\s*\d+\s*month(?:s)?)?)', raw_text, re.IGNORECASE)
                        if match:
                            listing_data['landlord_tenure'] = match.group(1).strip()
                        else: 
                            match_broad = re.search(r'Tenure:\s*([^E]+)', raw_text) 
                            if match_broad:
                                cleaned_tenure = match_broad.group(1).strip()
                                cleaned_tenure = re.sub(r'\s*[A-Z]{2,}\s*,\s*[A-Z]{2}$', '', cleaned_tenure).strip()
                                cleaned_tenure = re.sub(r'\s*[A-Z]{2}$', '', cleaned_tenure).strip() 
                                listing_data['landlord_tenure'] = cleaned_tenure
        except Exception:
            pass

        # Price, Utilities, Minimum Stay, Availability Status (All extracted from the main call-to-action panel)
        try:
            call_to_action_panel = soup.select_one('div[data-testid="call-to-action"]')
            if call_to_action_panel:
                # Price extraction
                price_tag = call_to_action_panel.select_one('div.text-2xl.font-semibold.text-nowrap.text-black, div.text-4xl.font-semibold.text-nowrap.text-black')
                if price_tag:
                    listing_data['price_monthly_raw'] = price_tag.get_text(strip=True)
                    listing_data['price_monthly_clean'] = clean_price(listing_data['price_monthly_raw'])

                # First, get the inner div which contains these elements (the one without classes but inside the gap-4 p-5 div)
                inner_info_wrapper = call_to_action_panel.select_one('.flex.w-full.flex-col.justify-evenly.gap-4.p-5 > div:not([class]):first-child')

                if inner_info_wrapper:
                    # Find all divs with the common classes that might contain utilities, min stay, availability
                    potential_info_divs = inner_info_wrapper.find_all('div', class_=['text-grey-dark', 'text-sm', 'font-semibold', 'text-green'])

                    for div_elem in potential_info_divs:
                        div_text = div_elem.get_text(strip=True)
                        
                        # Utilities
                        if re.search(r'Utilities:\s*', div_text, re.IGNORECASE):
                            utilities_text_lower = div_text.lower()
                            
                            found_utilities_keyword = False
                            for keyword in UTILITIES_INCLUDED_KEYWORDS:
                                if keyword in utilities_text_lower:
                                    listing_data['utilities_included'] = True
                                    found_utilities_keyword = True
                                    break
                            if not found_utilities_keyword:
                                for keyword in UTILITIES_EXCLUDED_KEYWORDS:
                                    if keyword in utilities_text_lower:
                                        listing_data['utilities_included'] = False
                                        found_utilities_keyword = True
                                        break
                        
                        # Minimum Stay
                        elif re.search(r'Minimum stay:\s*', div_text, re.IGNORECASE):
                            min_stay_text = div_text
                            match = re.search(r'(\d+)\s*month', min_stay_text, re.IGNORECASE)
                            if match:
                                listing_data['min_stay_months'] = int(match.group(1))
                            elif '30 days' in min_stay_text.lower():
                                listing_data['min_stay_months'] = 1
                            else:
                                num_match = re.search(r'(\d+)', min_stay_text)
                                if num_match:
                                    listing_data['min_stay_months'] = int(num_match.group(1))

                        # Availability Status Text
                        elif any(keyword in div_text for keyword in ['Available', 'Booked', 'Unavailable']):
                            listing_data['availability_status_text'] = div_text
                
        except Exception:
            pass

        # Square Footage (span containing "Sq. Ft.")
        try:
            sq_ft_tag = soup.find('span', string=lambda text: text and 'Sq. Ft.' in text)
            if sq_ft_tag:
                listing_data['square_footage'] = sq_ft_tag.get_text(strip=True).replace('Sq. Ft.', '').strip()
        except Exception:
            pass

        # Property Type (e.g., "Studio", often next to Sq.Ft. or in "Rooms & beds")
        try:
            type_tag = soup.find('span', class_='text-xs', string=lambda text: text and any(pt in text.lower() for pt in ['studio', 'apartment', 'house', 'condo', 'room', 'townhome']))
            if type_tag:
                listing_data['property_type'] = type_tag.get_text(strip=True)
        except Exception:
            pass

        # Bedrooms 
        if listing_data['property_type'] and 'studio' in listing_data['property_type'].lower():
            listing_data['bedrooms'] = 0.0
        else:
            try:
                rooms_beds_header = soup.find('h2', string=lambda text: text and 'Rooms & beds' in text)
                if rooms_beds_header:
                    bedroom_span = rooms_beds_header.find_next_sibling('span', class_='font-semibold', string=lambda text: text and 'bedrooms' in text)
                    if bedroom_span:
                        match = re.search(r'(\d+)\s*bedroom', bedroom_span.get_text(strip=True), re.IGNORECASE)
                        if match:
                            listing_data['bedrooms'] = float(match.group(1))
                    elif listing_data['property_type'] and 'bedroom' in listing_data['property_type'].lower():
                        match = re.search(r'(\d+)\s*bedroom', listing_data['property_type'], re.IGNORECASE)
                        if match: 
                            listing_data['bedrooms'] = float(match.group(1))
            except Exception:
                pass

        # Bathrooms (span/p containing "bathroom" text)
        try:
            rooms_beds_header = soup.find('h2', string=lambda text: text and 'Rooms & beds' in text)
            if rooms_beds_header:
                bath_tag = rooms_beds_header.find_next_sibling('span', class_='font-semibold', string=lambda text: text and 'bathroom' in text)
                if not bath_tag:
                    bath_tag = rooms_beds_header.find_next('span', class_='text-sa', string=lambda text: text and 'Bath' in text)
                
                if bath_tag:
                    match = re.search(r'(\d+\.?\d*)', bath_tag.get_text(strip=True))
                    if match:
                        listing_data['bathrooms'] = float(match.group(1))
                    elif 'private bath' in bath_tag.get_text(strip=True).lower():
                        listing_data['bathrooms'] = 1.0
        except Exception:
            pass

        # Closest Facilities (Demand Drivers listed on page)
        try:
            facilities_section_header = soup.find('h2', string=lambda text: text and 'Closest facilities' in text)
            if facilities_section_header:
                facilities_container = facilities_section_header.find_next_sibling('div', class_='grid') 
                if facilities_container:
                    facility_items = facilities_container.find_all('div', class_='flex items-center')
                    for item in facility_items:
                        name_tag = item.find('span', class_='text-black')
                        distance_tag = item.find('span', class_='min-w-fit')
                        if name_tag and distance_tag:
                            listing_data['closest_facilities_listed'].append({
                                'name': name_tag.get_text(strip=True),
                                'distance_text': distance_tag.get_text(strip=True)
                            })
        except Exception:
            pass

        # Description - Space (Direct targeting of the <p> tag with correct class as per screenshot)
        try:
            space_header_elem = soup.find('span', class_='text-lg font-semibold', string='Space')
            if space_header_elem:
                description_p_tag = space_header_elem.find_next_sibling('p', class_='text-base text-grey-dark')
                if description_p_tag:
                    listing_data['description_space'] = description_p_tag.get_text(separator="\n", strip=True)
        except Exception:
            pass

        # Description - Neighborhood overview (Direct targeting of the <p> tag with correct class as per screenshot)
        try:
            neighborhood_header_elem = soup.find('span', class_='text-lg font-semibold', string='Neighborhood overview')
            if neighborhood_header_elem:
                description_p_tag = neighborhood_header_elem.find_next_sibling('p', class_='text-base text-grey-dark')
                if description_p_tag:
                    listing_data['description_neighborhood'] = description_p_tag.get_text(separator="\n", strip=True)
        except Exception:
            pass

        # Amenities List
        try:
            amenities_section = soup.select_one('div[data-testid="section-pdp_amenities"]')
            if amenities_section:
                amenity_list_container = amenities_section.select_one('div.grid.grid-cols-2') 
                if not amenity_list_container: 
                    amenity_list_container = amenities_section.find('div', class_='flex.flex-col.gap-4') 
                
                if amenity_list_container:
                    amenity_elements = amenity_list_container.select('span.text-black, div.amenity-item, div.flex.items-center > span:not([class])') 
                    filtered_amenities = []
                    category_keywords = {
                        "kitchen", "interior", "safety", "bathroom", "laundry", "entertainment", "suitability", 
                        "parking", "outside", "what this property offers", "see all", "cleaning products", 
                        "essentials", "access", "features", "beds", "guest access", "sleeping arrangements",
                        "living area", "heating", "cooling", "internet", "home type",
                        "house rules", "availability", "reviews", "property fees" 
                    }
                    for item in amenity_elements:
                        text = item.get_text(strip=True)
                        if text and text.lower() not in category_keywords and not text.endswith(":") and len(text) > 2: 
                             text = re.sub(r'\(See all\s*\d+\s*\)', '', text, flags=re.IGNORECASE).strip()
                             text = re.sub(r'^\d+\s*', '', text).strip()
                             if text: 
                                filtered_amenities.append(text)
                    listing_data['amenities'] = sorted(list(set(filtered_amenities))) 
        except Exception:
            pass

        # Availability Calendar (Capturing visible month details)
        try:
            calendar_container = soup.select_one('div[data-testid="calendar"]')
            if calendar_container:
                month_year_header = calendar_container.select_one('div.rdp-caption span.text-lg')
                current_month_name = month_year_header.get_text(strip=True) if month_year_header else 'Unknown Month'
                
                current_month_availability = {'month_year': current_month_name, 'available_dates': [], 'unavailable_dates': []}

                available_days_elements = calendar_container.select('table.w-full td button:not([disabled])') 
                for day_btn in available_days_elements:
                    day_number = day_btn.get_text(strip=True)
                    if day_number.isdigit():
                        current_month_availability['available_dates'].append(f"{day_number} {current_month_name}")

                unavailable_days_elements = calendar_container.select('table.w-full td button[disabled]')
                for day_btn in unavailable_days_elements:
                    day_number = day_btn.get_text(strip=True)
                    if day_number.isdigit():
                        current_month_availability['unavailable_dates'].append(f"{day_number} {current_month_name}")
                
                if current_month_availability['available_dates'] or current_month_availability['unavailable_dates']:
                    listing_data['availability_calendar_raw'].append(current_month_availability)

        except Exception:
            pass

        # Reviews Count
        try:
            reviews_section = soup.select_one('div[data-testid="section-pdp_reviews"]')
            if reviews_section:
                no_reviews_text_tag = reviews_section.find('span', string="Be the first to leave a review")
                if no_reviews_text_tag:
                    listing_data['reviews_count'] = 0
                else:
                    reviews_count_elem = reviews_section.find('span', string=re.compile(r'\((\d+)\s*review[s]?\)'))
                    if reviews_count_elem:
                        match = re.search(r'\((\d+)\s*review[s]?\)', reviews_count_elem.get_text())
                        if match:
                            listing_data['reviews_count'] = int(match.group(1))
                    elif listing_data['reviews_count'] == 0: 
                        actual_reviews = reviews_section.select('div.review-card') 
                        if actual_reviews:
                            listing_data['reviews_count'] = len(actual_reviews)
        except Exception:
            pass

        # Photos (Prioritizing data-testid and robust img selection, improved filtering)
        try:
            gallery_div = soup.select_one('div[data-testid="property-photos-gallery"]')
            if not gallery_div:
                gallery_div = soup.select_one('div.image-gallery-container') 
            if not gallery_div: 
                gallery_div = soup.find('div', class_=re.compile(r'swiper-container|gallery-wrapper|gallery-container|image-carousel', re.IGNORECASE))
            
            if gallery_div:
                photo_elements = gallery_div.select('img[src*="http"], img[data-src*="http"]')
                
                for img_tag in photo_elements:
                    src = img_tag.get('src') or img_tag.get('data-src') 
                    if src and 'data:image' not in src: 
                        if not re.search(r'(thumbnail|thumb|_w_\d{2,3}|_h_\d{2,3}|/small/|/tiny/|/placeholder/|\?crop)', src, re.IGNORECASE): 
                             listing_data['photos_urls'].append(src)
                listing_data['photos_urls'] = sorted(list(set(listing_data['photos_urls']))) 
        except Exception:
            pass

        # Host Name (Targeting the specific h3 within the landlord info block, as per Image 6-12-25 at 12.38 PM.jpg)
        try:
            about_landlord_section = soup.find('h2', string=lambda t: t and 'About the landlord' in t)
            if about_landlord_section:
                landlord_details_container = about_landlord_section.find_next_sibling('div', class_='flex flex-col gap-4') 
                if not landlord_details_container: 
                    landlord_details_container = about_landlord_section.find_next_sibling('div')

                if landlord_details_container:
                    host_name_tag = landlord_details_container.find('h3', class_='font-semibold text-lg text-black')
                    if not host_name_tag: 
                         host_name_tag = landlord_details_container.find('h3', class_='font-semibold')

                    if host_name_tag:
                        listing_data['host_name'] = host_name_tag.get_text(strip=True)
        except Exception:
            pass


        time.sleep(random.uniform(2, 5))

        self._quit_driver()
        print("WebDriver quit after detail page.")
        return listing_data

# Example usage (for testing this module directly)
if __name__ == "__main__":
    import json
    import os
    os.makedirs('data/raw_ff_listings', exist_ok=True)

    scraper = FurnishedFinderScraper()

    # Step 1: Scrape search results first
    print("\n--- Step 1: Testing get_listing_urls for search results ---")
    test_search_city = "milford" 
    test_search_state = "ma"
    # Limit to 1 page for faster testing of the overall flow. You can increase max_pages for more results.
    search_results_cards = scraper.get_listing_urls(city=test_search_city, state=test_search_state, max_pages=1) 

    if search_results_cards:
        print(f"\nFound {len(search_results_cards)} listings from search results.")
        with open('data/raw_ff_listings/search_results_cards.json', 'w') as f:
            json.dump(search_results_cards, f, indent=4)
        print("Raw search card data saved to data/raw_ff_listings/search_results_cards.json")

        # Step 2 & 3: Iterate through found URLs and extract full details for each
        print("\n--- Step 2 & 3: Extracting full details for each individual listing ---")
        for i, card_info in enumerate(search_results_cards):
            listing_url = card_info['url']
            print(f"\nProcessing listing {i+1}/{len(search_results_cards)}: {listing_url}")
            full_listing_details = scraper.parse_listing_details(listing_url)

            if full_listing_details:
                property_id_for_filename = full_listing_details.get("property_id", f"listing_{i+1}")
                with open(f'data/raw_ff_listings/listing_detail_{property_id_for_filename}.json', 'w') as f:
                    json.dump(full_listing_details, f, indent=4)
                print(f"Raw listing detail data saved for {listing_url} to data/raw_ff_listings/listing_detail_{property_id_for_filename}.json")
            else:
                print(f"Failed to retrieve full listing details for {listing_url}.")
    else:
        print("No search results cards found, skipping detail page scraping.")

    print("\nScraper testing complete.")