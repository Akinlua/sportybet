#!/usr/bin/env python3

import time
import os
import tempfile
import uuid
import json
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class WebsiteOpener:
    """A class to handle opening websites with Selenium Wire for proxy authentication."""

    def __init__(self, headless=False, proxy=None, config_file="config.json"):
        """
        Initialize the WebsiteOpener.
        
        Args:
            headless (bool): Whether to run Chrome in headless mode
            proxy (str): Proxy URL in format "host:port" or "user:pass@host:port"
            config_file (str): Path to config.json file containing proxy settings
        """
        self.proxy = proxy
        self.config_file = config_file
        self.setup_driver(headless)
    
    def get_proxy_from_config(self):
        """Extract proxy URL from config.json file."""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            if config.get('use_proxies', False) and config.get('accounts'):
                # Get the first active account's proxy
                for account in config['accounts']:
                    if account.get('active', False) and account.get('proxy'):
                        return account['proxy']
            
            return None
        except Exception as e:
            print(f"Error reading config file: {e}")
            return None
    
    def setup_driver(self, headless):
        """Set up the Chrome WebDriver with Selenium Wire for proxy authentication."""

        # Get proxy from config if not provided
        if not self.proxy:
            self.proxy = self.get_proxy_from_config()
        
        # Set up Chrome options
        options = Options()
        # if headless:
        # options.add_argument("--headless=new")
        
        # Additional options for better compatibility
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-images")
        options.add_argument("--disable-javascript")  # Only if not needed
        options.add_argument("--memory-pressure-off")
        options.add_argument("--max_old_space_size=4096")
        
        # Add user agent
        options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
        
        # Set page load strategy
        options.page_load_strategy = 'eager'
        
        # Set up Selenium Wire options for proxy authentication
        seleniumwire_options = {}
        
        if self.proxy:
            print(f"Configuring proxy: {self.proxy}")
            
            # Parse the proxy URL to extract components
            if self.proxy.startswith("http://"):
                proxy_url = self.proxy
            else:
                proxy_url = f"http://{self.proxy}"
            
            # Configure selenium-wire options with proxy
            seleniumwire_options = {
                "proxy": {
                    "http": proxy_url,
                    "https": proxy_url
                }
            }
            
            print(f"Configured Selenium Wire proxy: {proxy_url}")
        
        # Initialize the Chrome driver with Selenium Wire
        try:
            self.driver = webdriver.Chrome(
                # service=Service(ChromeDriverManager().install()),
                seleniumwire_options=seleniumwire_options,
                options=options
            )
            print(f"Driver successful: {self.driver}")
        except Exception as e:
            print(f"Error setting up ChromeDriver: {e}")
            raise

    def open_url(self, url):
        """
        Open the specified URL in the browser.
        
        Args:
            url (str): The URL to open
        """
        try:
            self.driver.get(url)
            print(f"Successfully opened: {url}")
            return True
        except Exception as e:
            print(f"Error opening URL: {e}")
            return False
    
    def close(self):
        """Close the browser and clean up resources."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def close_browser(self):
        """Close the browser if it's open"""
        if hasattr(self, 'driver') and self.driver:
            try:
                print("Closing Selenium WebDriver...")
                self.driver.quit()
                self.driver = None
                print("WebDriver closed successfully")
            except Exception as e:
                print(f"Error closing WebDriver: {e}")


def main():
    """Main function to demonstrate usage with proxy from config.json."""
    # Example URL to test proxy
    url = "https://www.nairabet.com"
    
    # Create an instance of WebsiteOpener (will automatically use proxy from config.json)
    opener = WebsiteOpener(headless=False)
    
    try:
        # Open the URL
        if opener.open_url(url):
            # Wait for page to load
            time.sleep(3)
            
            # Print the page content to see the IP address
            try:
                body_text = opener.driver.find_element("tag name", "body").text
                print(f"Page content: {body_text}")
            except Exception as e:
                print(f"Error reading page content: {e}")
        
    except Exception as e:
        print(f"Error during execution: {e}")
    finally:
        # Close the browser
        opener.close()


if __name__ == "__main__":
    main() 