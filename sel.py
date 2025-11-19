from seleniumwire import webdriver
# from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import uuid
import os
import time



def create_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--proxy-server=http://ng.decodo.com:42001")
    # options.add_argument("--headless=new")
    # options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")

    # Create a brand-new temp unique profile for Selenium
    # profile_path = f"./profiles/{uuid.uuid4()}"
    # profile_path = os.path.abspath(f"./profiles/{uuid.uuid4()}")
    # os.makedirs(profile_path, exist_ok=True)
    # options.add_argument(f"--user-data-dir={profile_path}")
    # options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


    # If you want to use Default Chrome profile instead:
    # options.add_argument("--user-data-dir=/Users/user/Library/Application Support/Google/Chrome")
    # options.add_argument("--profile-directory=Default")
    # Configure selenium-wire options with proxy
    proxy_url = f"http://spunpat7r0:o6H1g7i8tKWzcjKk=y@ng.decodo.com:42001"
    seleniumwire_options = {}

    # seleniumwire_options = {
    #     "proxy": {
    #         "http": proxy_url,
    #         "https": proxy_url
    #     }
    # }
    driver = webdriver.Chrome(options=options)
    return driver

start_bet_ts = time.time()
print(f"Starting bet placement")
driver = create_driver()
driver.get("https://www.sportybet.com/ng/sport/football/England/Premier_League/Leeds_United_vs_Aston_Villa/sr:match:61300743")
elapsed = time.time() - start_bet_ts
print(f"Bet placement took {elapsed:.2f}s")
# driver.get("https://whatsmyip.com/")



print("Loaded:", driver.title)
driver.quit()
