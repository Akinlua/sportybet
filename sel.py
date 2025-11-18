from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import uuid
import os

def create_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # options.add_argument("--headless=new")
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")

    # Create a brand-new temp unique profile for Selenium
    # profile_path = f"./profiles/{uuid.uuid4()}"
    profile_path = os.path.abspath(f"./profiles/{uuid.uuid4()}")
    os.makedirs(profile_path, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_path}")
    options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


    # If you want to use Default Chrome profile instead:
    # options.add_argument("--user-data-dir=/Users/user/Library/Application Support/Google/Chrome")
    # options.add_argument("--profile-directory=Default")

    driver = webdriver.Chrome(options=options)
    return driver

driver = create_driver()
driver.get("https://www.sportybet.com/ng/sport/basketball/International/ABA_Liga_2/KK_Siroki_vs_KK_TFT_Skopje/sr:match:62379028")

print("Loaded:", driver.title)
driver.quit()
