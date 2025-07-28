from playwright.sync_api import sync_playwright 
import re
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta

# Configurable settings
# CHECK INTERVAL: wait time between each monitoring cycle.
CHECK_INTERVAL = timedelta(hours=2)

# Locker ID to monitor (unique identifier)
LOCKER_ID = ""

# Amazon credentials for authentication
AMAZON_EMAIL = ""
AMAZON_PASSWORD = ""

# Geographic coordinates to use for checking locker availability
LATITUDE = 44.4444  # Latitude
LONGITUDE = 44.444  # Longitude

def get_purchase_id(email: str, password: str) -> str:
    """
    Logs into Amazon and navigates to the checkout page to retrieve the purchase ID.
    
    Parameters:
        email (str): Email address for Amazon authentication.
        password (str): Password associated with the Amazon account.
    
    Returns:
        str: The purchase ID extracted from the checkout URL or None in case of an error.
    
    Functionality:
        - Uses Playwright for browser automation.
        - Launches the browser in headless mode (without GUI).
        - Logs into Amazon by entering credentials.
        - Navigates to the cart and proceeds to checkout.
        - Extracts the purchase ID from the URL using a regular expression.
    """
    with sync_playwright() as p:
        # Launch the Chromium browser in headless mode (without GUI)
        browser = p.chromium.launch(headless=True)
        try:
            # Open a new page in the browser
            page = browser.new_page()
            
            # Navigate to the Amazon login page
            page.goto("https://www.amazon.it/gp/sign-in.html")
            
            # Enter email and proceed to the next step
            page.fill("#ap_email", email)
            page.click("#continue")
            
            # Enter password and submit the login form
            page.fill("#ap_password", password)
            page.click("#signInSubmit")
            
            # Wait for the navigation header selector to confirm login success
            page.wait_for_selector("#nav-tools")

            # Navigate to the cart and proceed to checkout
            page.click("#nav-cart")
            page.click("input[data-feature-id=proceed-to-checkout-action]")

            # Wait for the URL to change, verifying that the checkout page has been reached
            page.wait_for_url(re.compile(r"/checkout/p/"), timeout=60000)

            # Use a regular expression to extract the purchase ID from the URL
            match = re.search(r"/p/p-(\d+-\d+-\d+)", page.url)
            return match.group(1) if match else None
            
        except Exception as e:
            # Handle any errors and print them to the console
            print(f"Error retrieving purchase ID: {str(e)}")
            return None
        finally:
            # Close the browser regardless of the operation's outcome
            browser.close()

class LockerMonitor:
    """
    Class containing methods to check locker availability.
    """
    
    @staticmethod
    async def check_availability(purchase_id: str, lat: float, lng: float) -> bool:
        """
        Checks the availability of a specific locker through an API call.
        
        Parameters:
            purchase_id (str): The purchase ID obtained earlier, required for API authentication.
            lat (float): Latitude for searching lockers nearby.
            lng (float): Longitude for searching lockers nearby.
        
        Returns:
            bool: True if the locker is available (eligible), False otherwise.
        
        Functionality:
            - Creates an asynchronous HTTP session using aiohttp.
            - Builds the request URL with the required parameters.
            - Makes a GET request and waits for the JSON response.
            - Checks the data structure and looks for the specified locker ID within the list.
            - Returns the boolean value of the "isEligible" field if the locker is found.
        """
        async with aiohttp.ClientSession() as session:
            try:
                # Construct the request URL with parameters
                url = (
                    f"https://www.amazon.it/location_selector/fetch_locations?"
                    f"longitude={lng}&latitude={lat}"
                    f"&clientId=amazon_it_checkout_generic_tspc_desktop"
                    f"&purchaseId={purchase_id}"
                    "&countryCode=IT&lowerSlotPreference=false"
                    "&sortType=RECOMMENDED&userBenefit=true"
                    "&showFreeShippingLabel=true&showPromotionDetail=false"
                    "&showAvailableLocations=false&pipelineType=Chewbacca"
                )
                
                # Execute the GET request to the defined URL with a custom header
                async with session.get(
                    url=url,
                    headers={"User-Agent": "LockerMonitor/2.0"}
                ) as response:
                    
                    # Convert the response to JSON format
                    data = await response.json()
                    
                    # Ensure the response is a dictionary; otherwise, report an error
                    if not isinstance(data, dict):
                        print("Invalid API response format")
                        return False
                        
                    # Extract the locker list, ensuring it is always a list
                    location_list = data.get("locationList", []) if isinstance(data, dict) else []
                    if not isinstance(location_list, list):
                        location_list = []
                    
                    # Iterate through the locker list to find the specified locker ID
                    for location in location_list:
                        if isinstance(location, dict) and location.get("id") == LOCKER_ID:
                            # Return the boolean value of the "isEligible" field
                            return bool(location.get("isEligible", False))
                    
                    # If the locker is not found in the list, print a message and return False
                    print("Locker not found in response")
                    return False
                    
            except json.JSONDecodeError:
                # Handle errors related to JSON parsing
                print("Error parsing JSON response")
                return False
            except Exception as e:
                # Generic error handling during the request
                print(f"Error checking locker availability: {str(e)}")
                return False
                
async def monitoring_cycle():
    """
    Main monitoring loop.
    
    Functionality:
        - Repeatedly executes (every CHECK_INTERVAL) the following steps:
            1. Retrieves a new purchase ID by logging into Amazon.
            2. Uses the purchase ID to check locker availability.
            3. Prints the locker status (AVAILABLE or FULL).
            4. Calculates the remaining time until the next cycle and waits for that duration.
    """
    while True:
        start_time = datetime.now()
        print(f"\n=== New cycle at {start_time} ===")
        
        # Obtain the purchase ID by running the function in a separate thread to avoid blocking asyncio events
        purchase_id = await asyncio.to_thread(
            get_purchase_id, 
            AMAZON_EMAIL, 
            AMAZON_PASSWORD
        )
        
        if purchase_id:
            # If the purchase ID was obtained, proceed with checking locker availability
            status = await LockerMonitor.check_availability(
                purchase_id=purchase_id,
                lat=LATITUDE,
                lng=LONGITUDE
            )
            
            # Print the current locker status
            print(f"Locker status {LOCKER_ID}: {'AVAILABLE' if status else 'FULL'}")
            
        # Calculate elapsed time in this cycle and determine how long to wait before the next check
        elapsed = datetime.now() - start_time
        wait_seconds = CHECK_INTERVAL.total_seconds() - elapsed.total_seconds()
        if wait_seconds > 0:
            print(f"Next check in {wait_seconds/60:.1f} minutes")
            await asyncio.sleep(wait_seconds)

if __name__ == "__main__":
    """
    Script entry point.
    
    Uses asyncio.run to start the asynchronous monitoring cycle.
    Catches KeyboardInterrupt to terminate the program gracefully.
    """
    try:
        asyncio.run(monitoring_cycle())
    except KeyboardInterrupt:
        print("\nMonitoring interrupted")
