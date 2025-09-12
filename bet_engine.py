from selenium_script import WebsiteOpener
import os
import time
import json
import re
import requests
import dotenv
import threading
import queue
import logging
import asyncio
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from utils.calculate_no_vig_prices import calculate_no_vig_prices
from utils.calculate_ev import calculate_ev
from scipy.optimize import minimize_scalar
import math
from captcha_solver import CaptchaSolver

dotenv.load_dotenv()

# # Set up logging
# def setup_logging():
#     """Set up structured logging for the betting system"""
#     # Create formatters
#     detailed_formatter = logging.Formatter(
#         '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
#     simple_formatter = logging.Formatter(
#         '%(asctime)s - %(levelname)s - %(message)s'
#     )
    
#     # Create handlers
#     console_handler = logging.StreamHandler()
#     console_handler.setLevel(logging.INFO)
#     console_handler.setFormatter(simple_formatter)
    
#     # File handlers for different components
#     bet_handler = logging.FileHandler('logs/betting.log')
#     bet_handler.setLevel(logging.INFO)
#     bet_handler.setFormatter(detailed_formatter)
    
#     odds_handler = logging.FileHandler('logs/odds.log')
#     odds_handler.setLevel(logging.INFO)
#     odds_handler.setFormatter(detailed_formatter)
    
#     auth_handler = logging.FileHandler('logs/auth.log')
#     auth_handler.setLevel(logging.INFO)
#     auth_handler.setFormatter(detailed_formatter)
    
#     error_handler = logging.FileHandler('logs/errors.log')
#     error_handler.setLevel(logging.ERROR)
#     error_handler.setFormatter(detailed_formatter)
    
#     # Create loggers
#     bet_logger = logging.getLogger('betting')
#     bet_logger.setLevel(logging.INFO)
#     bet_logger.addHandler(bet_handler)
#     bet_logger.addHandler(console_handler)
    
#     odds_logger = logging.getLogger('odds')
#     odds_logger.setLevel(logging.INFO)
#     odds_logger.addHandler(odds_handler)
#     odds_logger.addHandler(console_handler)
    
#     auth_logger = logging.getLogger('auth')
#     auth_logger.setLevel(logging.INFO)
#     auth_logger.addHandler(auth_handler)
#     auth_logger.addHandler(console_handler)
    
#     error_logger = logging.getLogger('errors')
#     error_logger.setLevel(logging.ERROR)
#     error_logger.addHandler(error_handler)
#     error_logger.addHandler(console_handler)
    
#     return bet_logger, odds_logger, auth_logger, error_logger

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Initialize loggers
# bet_logger, odds_logger, auth_logger, error_logger = setup_logging()

# Set up main logger for console output
logger = logging.getLogger('nairabet_betting')
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

class BetAccount:
    """
    Represents a single Nairabet account with its own login credentials and cookie jar
    """
    def __init__(self, username, password, active=True, max_concurrent_bets=3, min_balance=100, proxy=None):
        self.username = username
        self.password = password
        self.active = active
        self.max_concurrent_bets = max_concurrent_bets
        self.min_balance = min_balance
        self.proxy = proxy  # Format: "http://user:pass@host:port" or "http://host:port"
        self.cookie_jar = None
        self.current_bets = 0
        self.last_login_time = 0
        self.balance = 0
        
    def increment_bets(self):
        self.current_bets += 1
        
    def decrement_bets(self):
        self.current_bets = max(0, self.current_bets - 1)
        
    def can_place_bet(self):
        # auth_logger.info(f"Account {self.username} can place bet: {self.active} {self.cookie_jar is not None} {self.current_bets < self.max_concurrent_bets} {self.balance >= self.min_balance}")
        # auth_logger.info(f"current bets: {self.current_bets} max concurrent bets: {self.max_concurrent_bets} balance: {self.balance} min balance: {self.min_balance}")
        return (self.active and 
                self.current_bets < self.max_concurrent_bets)
        
    def set_cookie_jar(self, cookies):
        # Handle both formats: list of cookie dictionaries (from Selenium) or direct dictionary
        if isinstance(cookies, list):
            self.cookie_jar = {cookie["name"]: cookie["value"] for cookie in cookies}
        else:
            # Assume it's already a dictionary
            self.cookie_jar = cookies
        self.last_login_time = time.time()
        
    def needs_login(self, max_session_time=3600):  # 1 hour max session time
        return (self.cookie_jar is None or 
                (time.time() - self.last_login_time) > max_session_time)

    def get_proxies(self):
        """Return proxies dictionary for requests if proxy is configured"""
        if not self.proxy:
            return None
        return {
            'http': self.proxy,
            'https': self.proxy
        }

class BetEngine(WebsiteOpener):
    """
    Handles the bet placement process on Nairabet, including:
    - Searching for matches
    - Finding the right market
    - Calculating EV
    - Placing bets with positive EV using selenium
    """
    
    def __init__(self, headless=os.getenv("ENVIRONMENT")=="production", 
                 bet_host=os.getenv("NAIRABET_HOST", "https://www.nairabet.com"), 
                 bet_api_host=os.getenv("NAIRABET_API_HOST", "https://sports-api.nairabet.com"),
                 min_ev=float(os.getenv("MIN_EV", "0")),
                 config_file="config.json",
                 skip_initial_login=False):
        """
        Initialize BetEngine
        
        Parameters:
        - headless: Whether to run browser in headless mode
        - bet_host: Nairabet betting website host
        - bet_api_host: Nairabet API host for searching events
        - min_ev: Minimum expected value threshold for placing bets
        - config_file: Path to configuration file
        - skip_initial_login: Whether to skip initial login setup
        """
        super().__init__(headless)

        # Initialize popup handler state first (before any cleanup calls)
        self.__popup_handler_running = False
        self.__popup_handler_task = None

        # bet_logger.info(f"Initializing BetEngine with min_ev: {min_ev}")
        # Only initialize browser if needed for certain operations
        
        # Store initialization parameters
        self.__headless = headless
        self.__skip_initial_login = skip_initial_login
        
        # Set up logging
        # self.bet_logger, self.odds_logger, self.auth_logger, self.error_logger = setup_logging()
        
        # Initialize configuration
        self.__config = {}
        self.__bet_host = bet_host
        self.__bet_api_host = bet_api_host
        self.__min_ev = min_ev
        self.__min_stake = 10
        self.__max_stake = 1000
        self.__max_pinnacle_odds = 10.0
        self.__max_total_bets = 10

        # Browser state
        self.__browser_initialized = False
        self.__browser_open = False
        self._current_proxy = None
        
        # Track processed games to avoid reprocessing
        self.__processed_games = set()
        
        # Track placed bets to avoid duplicates (max 1000)
        self.__placed_bets = {}  # Key: bet_signature, Value: bet_details
        
        # Track found outcomes per game to avoid checking opposite outcomes
        self.__game_found_outcomes = {}  # Key: game_id, Value: set of found outcomes
        
        # Initialize bet queue for queued bet placement
        self.__bet_queue = queue.Queue()
        
        # Initialize cookie jar for search functionality
        self.__cookie_jar = None
        

        # Load configuration
        self.__load_config(config_file)
        
        # Initialize accounts
        self.__accounts = []
        self.__setup_accounts()
        
        # Initialize browser if not skipping initial login
        # if not skip_initial_login:
        #     self.__do_login()
        
        # Start bet worker thread for queued bet placement
        self.__start_bet_worker()
    
    def _initialize_browser_if_needed(self, account=None):
        """Initialize the browser if it hasn't been initialized yet
        
        Parameters:
        - account: Specific BetAccount to use for proxy configuration. If None, uses first available proxy.
        """
        # Check if we need to reinitialize browser for a different proxy or account
        current_proxy = getattr(self, '_current_proxy', None)
        current_account = getattr(self, '_current_account', None)
        target_proxy = None
        
        if self.__config.get("use_proxies", False):
            if account and account.proxy:
                target_proxy = account.proxy
            else:
                # Fallback to first available proxy
                for acc in self.__accounts:
                    if acc.proxy:
                        target_proxy = acc.proxy
                        break
        
        # If browser is initialized but we need a different proxy or account, clean up first
        logger.info(f"self.__browser_initialized: {self.__browser_initialized}")
        logger.info(f"current_proxy: {current_proxy} target_proxy: {target_proxy}")
        logger.info(f"current_account: {current_account} target_account: {account.username if account else None}")
        
        # Restart browser if switching to a different account or proxy
        if (self.__browser_initialized and 
            (current_proxy != target_proxy or current_account != account) and 
            account is not None):
            logger.info(f"Account or proxy change detected. Restarting browser for account: {account.username}")
            self._cleanup_browser_for_proxy_switch()
        
        if not self.__browser_initialized:
            logger.info("Initializing browser...")
            
            # Get proxy from the specified account or first available account if configured
            proxy = target_proxy
            if proxy:
                logger.info(f"Using proxy: {proxy}")
                if account:
                    logger.info(f"  └─ From account: {account.username}")
                else:
                    logger.info(f"  └─ From fallback account")
            else:
                if self.__config.get("use_proxies", False):
                    logger.warning("Proxy usage enabled but no proxy found in accounts")
                else:
                    logger.info("Proxy usage disabled in config")
            
            super().__init__(self.__headless, proxy)
            self.__browser_initialized = True
            self.__browser_open = True
            self._current_proxy = proxy  # Store current proxy for future comparison
            self._current_account = account  # Store current account for future comparison
            logger.info("Browser initialized")
            
            # Start background popup handler
            self.__start_popup_handler()
            
            # Check IP address if using proxy
            if proxy:
                proxy_dict = {'http': proxy, 'https': proxy}
                self.__check_ip_address(using_proxy=True, proxy_url=proxy_dict, account=account)
            else:
                self.__check_ip_address(using_proxy=False)
    
    def _cleanup_browser_for_proxy_switch(self):
        """Clean up the current browser instance to allow for proxy switching"""
        try:
            # Stop background popup handler
            self.__stop_popup_handler()
            
            if hasattr(self, 'driver') and self.driver:
                logger.info("Closing current browser for proxy switch...")
                self.driver.quit()
                self.driver = None
            
            self.__browser_initialized = False
            self.__browser_open = False
            self._current_proxy = None
            self._current_account = None
            logger.info("Browser cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during browser cleanup: {e}")
            # Force reset the flags even if cleanup failed
            self.__browser_initialized = False
            self.__browser_open = False
            self._current_proxy = None
            self._current_account = None

    async def __background_popup_handler(self):
        """
        Background async function that continuously checks for and handles popups
        Runs every 2 seconds while browser is open
        """
        logger.info("🔄 Starting background popup handler...")
        
        while self.__popup_handler_running and self.__browser_open:
            try:
                if hasattr(self, 'driver') and self.driver:
                    # Handle Accept/Cookie popups
                    # try:
                    #     accept_button = self.driver.find_element(By.XPATH, "//button[contains(text(),'Accept')]")
                    #     accept_button.click()
                    #     logger.info("🖱️ Clicked Accept button on popup")
                    #     await asyncio.sleep(0.5)
                    # except:
                    #     pass
                    
                    # Handle Kumulos confirmation popups
                    try:
                        confirm_button = self.driver.find_element(By.CSS_SELECTOR, "button.kumulos-action-button.kumulos-action-button-cancel")
                        confirm_button.click()
                        logger.info("🖱️ Clicked Kumulos confirm button")
                        await asyncio.sleep(0.5)
                    except:
                        try:
                            cancel_button = self.driver.find_element(By.CSS_SELECTOR, ".kumulos-action-button-cancel")
                            cancel_button.click()
                            logger.info("🖱️ Clicked Kumulos cancel button")
                            await asyncio.sleep(0.5)
                        except:
                            pass
                    
                    # # Remove background mask if present
                    # try:
                    #     self.driver.execute_script("""
                    #         const mask = document.querySelector('.kumulos-background-mask');
                    #         if (mask) mask.remove();
                    #     """)
                    #     logger.info("🧹 Removed Kumulos background mask")
                    # except:
                    #     pass
                        
            except Exception as e:
                logger.debug(f"Error in background popup handler: {e}")
            
            # Wait 2 seconds before next check
            await asyncio.sleep(2)
        
        logger.info("🛑 Background popup handler stopped")

    def __start_popup_handler(self):
        """Start the background popup handler in a separate thread"""
        if not self.__popup_handler_running:
            self.__popup_handler_running = True
            
            def run_popup_handler():
                """Run the async popup handler in a new event loop"""
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.__background_popup_handler())
                except asyncio.CancelledError:
                    pass
                finally:
                    loop.close()
            
            # Start popup handler in a separate thread
            self.__popup_handler_thread = threading.Thread(target=run_popup_handler, daemon=True)
            self.__popup_handler_thread.start()
            logger.info("🚀 Background popup handler started")

    def __stop_popup_handler(self):
        """Stop the background popup handler"""
        if self.__popup_handler_running:
            self.__popup_handler_running = False
            logger.info("🛑 Background popup handler stopped")
        
    def __load_config(self, config_file):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                self.__config = json.load(f)
                
            # Update min_ev from config if available
            if "bet_settings" in self.__config and "min_ev" in self.__config["bet_settings"]:
                self.__min_ev = float(self.__config["bet_settings"]["min_ev"])
                
            if "bet_settings" in self.__config and "min_stake" in self.__config["bet_settings"]:
                self.__min_stake = float(self.__config["bet_settings"]["min_stake"])
                
            if "bet_settings" in self.__config and "max_stake" in self.__config["bet_settings"]:
                self.__max_stake = float(self.__config["bet_settings"]["max_stake"])
                
            if "bet_settings" in self.__config and "max_pinnacle_odds" in self.__config["bet_settings"]:
                self.__max_pinnacle_odds = float(self.__config["bet_settings"]["max_pinnacle_odds"])
            else:
                self.__max_pinnacle_odds = 3.0  # Default value
                
            # Load odds-based stake ranges
            if "bet_settings" in self.__config and "odds_based_stakes" in self.__config["bet_settings"]:
                self.__odds_based_stakes = self.__config["bet_settings"]["odds_based_stakes"]
            else:
                # Default odds-based stake ranges
                self.__odds_based_stakes = {
                    "low_odds": {
                        "max_odds": 1.99,
                        "min_stake": 6000,
                        "max_stake": 12000
                    },
                    "medium_odds": {
                        "min_odds": 2.0,
                        "max_odds": 3.0,
                        "min_stake": 3000,
                        "max_stake": 7000
                    }
                }
                
                
            logger.info(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            # Create default config
            self.__config = {
                "accounts": [],
                "max_total_concurrent_bets": 5,
                "use_proxies": False,  # Global flag to enable/disable proxies
                "immediate_bet_placement": True,  # Place bets immediately instead of queuing
                "bet_settings": {
                    "min_ev": self.__min_ev,
                    "kelly_fraction": 0.3,
                    "min_stake": 10,
                    "max_stake": 1000000,
                    "max_pinnacle_odds": 3.0,
                    "odds_based_stakes": {
                        "low_odds": {
                            "max_odds": 1.99,
                            "min_stake": 6000,
                            "max_stake": 12000
                        },
                        "medium_odds": {
                            "min_odds": 2.0,
                            "max_odds": 3.0,
                            "min_stake": 3000,
                            "max_stake": 7000
                        }
                    },
                    "bankroll": 1000
                }
            }
            
    def __setup_accounts(self):
        """Initialize bet accounts from config"""
        # First, set up at least one account from environment variables if available
        env_username = os.getenv("NAIRABET_USERNAME")
        env_password = os.getenv("NAIRABET_PASSWORD")
        
        if env_username and env_password:
            self.__accounts.append(BetAccount(env_username, env_password))
            
        # Then add accounts from config
        if "accounts" in self.__config:
            for account_data in self.__config["accounts"]:
                # Skip if username/password is missing or account already exists
                if not account_data.get("username") or not account_data.get("password"):
                    continue
                    
                # Check if this account is already added from env vars
                if (env_username and env_password and 
                    account_data.get("username") == env_username and 
                    account_data.get("password") == env_password):
                    continue
                    
                self.__accounts.append(BetAccount(
                    username=account_data.get("username"),
                    password=account_data.get("password"),
                    active=account_data.get("active", True),
                    max_concurrent_bets=account_data.get("max_concurrent_bets", 3),
                    min_balance=account_data.get("min_balance", 100),
                    proxy=account_data.get("proxy")
                ))
                logger.info(f"Added account: {account_data.get('username')}")
                
        # Ensure we have at least one account
        if not self.__accounts:
            raise ValueError("No betting accounts configured. Please set NAIRABET_USERNAME and NAIRABET_PASSWORD environment variables or configure accounts in config.json")
            
        logger.info(f"Set up {len(self.__accounts)} betting accounts")
        
        # Try to login to accounts for initial setup, but don't fail if login fails
        if self.__accounts and not self.__skip_initial_login:
            logger.info("Attempting initial login for all accounts...")
            try:
                for account in self.__accounts:
                    try:
                        self.__do_login_for_account(account)
                        logger.info(f"Successfully logged in account: {account.username}")
                    except Exception as e:
                        logger.error(f"Failed to login account {account.username} during setup: {e}")
                        logger.warning("Account will be available for retry later")
                        # Continue with other accounts instead of crashing
                        continue
            finally:
                # Close browser after all login attempts are complete
                if self.__browser_initialized:
                    logger.info("Closing browser after account setup...")
                    self.cleanup()
        elif self.__skip_initial_login:
            logger.info("Skipping initial login as requested")
        else:
            logger.warning("No accounts configured for initial login")

            
    def __start_bet_worker(self):
        """Start a worker thread to process bet queue"""
        self.__worker_thread = threading.Thread(target=self.__process_bet_queue, daemon=True)
        self.__worker_thread.start()
        
    def __process_bet_queue(self):
        """Process bets from the queue"""
        while True:
            try:
                # Get bet data from queue
                bet_data = self.__bet_queue.get()
                
                # Place bet with available accounts
                self.__place_bet_with_available_account(bet_data)
                
                # Mark task as done
                self.__bet_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in bet worker thread: {e}")
                
            # Small sleep to prevent CPU hogging
            time.sleep(0.1)

    def __do_login(self):
        """Log in to Nairabet website with the first account (for search functionality)"""
        if self.__accounts:
            self.__do_login_for_account(self.__accounts[0])
        else:
            raise ValueError("No betting accounts configured")
            
    def __check_ip_address(self, using_proxy=False, proxy_url=None, account=None ):
        """Check and log the current IP address being used"""
        try:
            # Use a service that returns the client's IP address
            ip_check_url = "https://api.ipify.org?format=json"
            response = requests.get(ip_check_url, proxies=proxy_url)
            if response.status_code == 200:
                ip_data = response.json()
                if "ip" in ip_data:
                    ip_address = ip_data["ip"]
                    if using_proxy:
                        logger.info(f"✅ Using proxy - Current IP address: {ip_address} {account.username} {account.proxy}")
                    else:
                        logger.info(f"Current IP address (no proxy): {ip_address}")
                    return ip_address
            logger.warning("Failed to get IP address")
            return None
        except Exception as e:
            logger.error(f"Error checking IP address: {e}")
            return None
            
    def __fetch_account_balance(self, account):
        """
        Fetch account balance from Nairabet API after login
        
        Parameters:
        - account: BetAccount instance with valid cookies
        
        Returns:
        - Balance amount as float, or 0 if failed
        """
        try:
            if not account.cookie_jar:
                logger.warning(f"No cookies available for account {account.username}, cannot fetch balance")
                return 0
                
            balance_url = "https://users-api.nairabet.com/v2/users/me/balance?country=NG&group=g3&platform=desktop&locale=en"
            
            # Convert cookie jar to requests format
            cookies = {}
            if isinstance(account.cookie_jar, dict):
                cookies = account.cookie_jar
            elif isinstance(account.cookie_jar, list):
                cookies = {cookie["name"]: cookie["value"] for cookie in account.cookie_jar}
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nairabet.com/",
                "x-sah-device": "5f40d3154db72f213ffd1fe7f7ad1cb8"
            }
            
            response = requests.get(balance_url, headers=headers, cookies=cookies, proxies=account.get_proxies())
            
            if response.status_code == 200:
                balance_data = response.json()
                
                # Support both top-level and nested under 'data'
                payload = balance_data.get("data", balance_data) if isinstance(balance_data, dict) else {}
                
                if isinstance(payload, dict) and ("withdrawable" in payload or "total" in payload):
                    withdrawable = float(payload.get("withdrawable", 0.0))
                    total = float(payload.get("total", 0.0))
                    logger.info(f"Account {account.username} balance: withdrawable={withdrawable:.2f}, total={total:.2f}")
                    return total
                else:
                    logger.warning(f"Invalid balance response for account {account.username}: {balance_data}")
                    return 0
            else:
                logger.error(f"Failed to fetch balance for account {account.username}: HTTP {response.status_code}")
                return 0
                
        except Exception as e:
            logger.error(f"Error fetching balance for account {account.username}: {e}")
            return 0

    def __do_login_for_account(self, account, _retry=False):
        """Log in to Nairabet website with a specific account using selenium with retry mechanism"""
        max_retries = 2
        current_attempt = 2 if _retry else 1
        
        logger.info(f"🔄 Login attempt {current_attempt}/{max_retries} for account: {account.username}")
        
        if not account.username or not account.password:
            raise ValueError("Nairabet username or password not found for account")
        
        try:
            # Initialize browser with account-specific proxy
            self._initialize_browser_if_needed(account)
            
            # Initialize CAPTCHA solver
            # captcha_config = self.__config.get("captcha", {})
            # if captcha_config.get("enabled", True):
            #     captcha_solver = CaptchaSolver(api_key=captcha_config.get("api_key"))
            #     captcha_solver.max_retries = captcha_config.get("max_retries", 3)
            # else:
            #     print("⚠️  CAPTCHA solving is disabled in configuration")
            #     captcha_solver = None

            # Check if already logged in first by presence of header 'Account' button
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(@class,'header-button') and contains(@class,'header-button--none')][.//span[contains(@class,'header-button__label') and normalize-space()='Account']]"))
                )
                logger.info(f"Already logged in for account: {account.username}")
                # Get cookies from selenium
                selenium_cookies = self.driver.get_cookies()
                account.set_cookie_jar(selenium_cookies)
                
                # Fetch account balance after successful login
                balance = self.__fetch_account_balance(account)
                account.balance = balance
                logger.info(f"Updated account balance: {balance:.2f}")
            
                # If this is the first account, also store cookies in the class for search functionality
                if self.__accounts and account == self.__accounts[0]:
                    self.__cookie_jar = account.cookie_jar
                
                return True
            except TimeoutException:
                logger.info(f"Not logged in, proceeding with login process for account: {account.username}")
            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
                # Continue with login process
            
            # Navigate to Nairabet login page
            login_url = f"{self.__bet_host}"
            try:
                self.driver.get(login_url)
                logger.info(f"Navigated to login page: {login_url}")
            except Exception as get_err:
                msg = str(get_err).lower()
                if ("invalid session id" in msg or "disconnected" in msg):
                    logger.error("Invalid Selenium session detected. Restarting browser and retrying login navigation...")
                    self.__restart_browser(account)
                    self.driver.get(login_url)
                    logger.info(f"Navigated to login page after restart: {login_url}")
                else:
                    raise
            
            # Open login modal from header
            try:
                header_login_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'header-button')][.//span[contains(@class,'header-button__label') and normalize-space()='Login']]"))
                )
                header_login_btn.click()
                logger.info("Opened login modal")
                
                # Handle notification popup that may appear after clicking login
                # try:
                #     # Wait for notification popup and click "Maybe Later"
                #     maybe_later_btn = WebDriverWait(self.driver, 5).until(
                #         EC.element_to_be_clickable((By.CSS_SELECTOR, "button.kumulos-action-button.kumulos-action-button-cancel"))
                #     )
                #     maybe_later_btn.click()
                #     logger.info("Clicked 'Maybe Later' on notification popup")
                #     time.sleep(1)  # Brief wait for popup to close
                # except TimeoutException:
                #     logger.info("No notification popup found, continuing with login")
                # except Exception as e:
                #     logger.warning(f"Could not handle notification popup: {e}")
                    
            except Exception as e:
                logger.error(f"Could not open login modal: {e}")
            
            # Find username/phone/email input
            phone_input = WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.skeleton-container.overlay-skeleton input[name='login']"))
            )
            phone_input.clear()
            phone_input.send_keys(account.username)
            logger.info(f"📱 Entered username/phone/email: {account.username}")
            
            # Find password input
            password_input = WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.skeleton-container.overlay-skeleton input[name='password']"))
            )
            password_input.clear()
            password_input.send_keys(account.password)
            logger.info(f"🔑 Entered password")
            
            # Find and click login button inside the modal
            login_button = WebDriverWait(self.driver, 60).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'skeleton-container') and contains(@class,'overlay-skeleton')]//button[contains(@class,'form-button') and contains(@class,'form-button--primary')]"))
            )
            login_button.click()
            logger.info(f"🚀 Clicked login button")
            
            # Take screenshot for debugging
            # try:
            #     timestamp = time.strftime("%Y%m%d-%H%M%S")
            #     screenshot_path = f"login_status_{timestamp}.png"
            #     self.driver.save_screenshot(screenshot_path)
            #     # print(f"📸 Login status screenshot saved to {screenshot_path}")
            # except Exception as screenshot_error:
            #     logger.error(f"Failed to take screenshot: {screenshot_error}")
            
            # Verify login success by presence of header 'Account' button
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(@class,'header-button') and contains(@class,'header-button--none')][.//span[contains(@class,'header-button__label') and normalize-space()='Account']]"))
                )
                logger.info(f"Login successful for account: {account.username}")
                
                # Get cookies from selenium
                selenium_cookies = self.driver.get_cookies()
                account.set_cookie_jar(selenium_cookies)
                
                # Fetch account balance after successful login
                balance = self.__fetch_account_balance(account)
                account.balance = balance
                logger.info(f"Updated account balance: {balance:.2f}")
            
                # If this is the first account, also store cookies in the class for search functionality
                if self.__accounts and account == self.__accounts[0]:
                    self.__cookie_jar = account.cookie_jar
                
                return True
                        
            except TimeoutException:
                logger.warning(f"Login may have failed for account: {account.username}")
                raise Exception("Login verification timeout")
                
        except Exception as e:
            # Take screenshot of error state
            try:
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                screenshot_path = f"login_error_{timestamp}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Login error screenshot saved to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to take error screenshot: {screenshot_error}")
            
            logger.error(f"❌ Login attempt {current_attempt} failed for account: {account.username}: {e}")
            
            # Retry logic for any login failure
            if current_attempt < max_retries:
                logger.info(f"🔄 Retrying login for account: {account.username} (attempt {current_attempt + 1}/{max_retries})")
                time.sleep(2)  # Brief wait before retry
                return self.__do_login_for_account(account, _retry=True)
            
            # If we've exhausted all retries, handle final failure
            logger.error(f"❌ All login attempts failed for account: {account.username}")
            
            # Minimal recovery for Selenium tab crashes (only on first attempt)
            msg = str(e).lower()
            if ("tab crashed" in msg or "chrome not reachable" in msg or "disconnected" in msg or "invalid session id" in msg) and not _retry:
                logger.error("Detected browser/tab crash during login. Restarting browser and retrying once...")
                self.__restart_browser(account)
                return self.__do_login_for_account(account, _retry=True)
            
            # Final failure - don't sleep for 1000 seconds, just raise the exception
            raise

    def __search_event(self, home_team, away_team, pinnacle_start_time=None):
        """
        Search for an event on Nairabet using team names and match start time
        
        Parameters:
        - home_team: Home team name
        - away_team: Away team name
        - pinnacle_start_time: Start time from Pinnacle in milliseconds (unix timestamp)
        
        Returns:
        - event ID if found, None otherwise
        """
        logger.info(f"Searching for match: {home_team} vs {away_team}")
        if pinnacle_start_time:
            pinnacle_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(pinnacle_start_time)/1000))
            logger.info(f"Pinnacle start time: {pinnacle_datetime} (GMT)")
        
        # Try different search strategies
        search_strategies = [
            f"{home_team.lower()} {away_team.lower()}",  # Full match name
            home_team.lower(),                   # Home team only
            away_team.lower(),                   # Away team only
        ]
        
        # Add individual words from team names as search strategies
        for team in [home_team, away_team]:
            words = team.split()
            for word in words:
                if len(word) > 3 and word not in search_strategies:  # Only use words longer than 3 chars
                    search_strategies.append(word)
        
        # Store potential matches with scores for later evaluation
        potential_matches = []
        
        # List of terms that indicate the wrong team variant
        variant_indicators = ["ladies", "women", "u21", "u-21", "u23", "u-23", "youth", "junior", "reserve", "b team"]
        
        for search_term in search_strategies:
            # logger.info(f"Trying search term: {search_term}")
            
            try:
                # Nairabet sports API search endpoint
                search_url = "https://sports-api.nairabet.com/v2/events/search"
                params = {
                    'country': 'NG',
                    'group': 'g3',
                    'platform': 'desktop',
                    'locale': 'en',
                    'text': search_term
                }
            
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.nairabet.com/",
                    "x-sah-device": "5f40d3154db72f213ffd1fe7f7ad1cb8"
                }
                
                # Get proxy if available
                proxies = None
                if self.__config.get("use_proxies", False) and self.__accounts:
                    # Use the first available account's proxy
                    for acc in self.__accounts:
                        if acc.proxy:
                            proxies = acc.get_proxies()
                            logger.info(f"Using proxy for search: {acc.proxy}")
                            break
                
                # logger.info(f"Searching with URL: {search_url} and params: {params}")
                response = requests.get(search_url, params=params, headers=headers, proxies=proxies)
                
                # logger.info(f"Response status: {response.status_code}")
                # print(f"Response content: {response.text[:500]}...")
                if response.status_code == 200:
                    try:
                        search_results = response.json()
                        # print(f"Search response: {search_results}")
                    except ValueError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
                        logger.info(f"Response content: {response.text[:500]}...")
                        continue
                
                    # Updated to handle the new API response structure
                    if "data" in search_results and search_results["data"]:
                        events = search_results["data"]
                        for event in events:
                            # Extract team names from new response format
                            event_names = event.get("eventNames", [])
                            
                            # Handle both array format and single string format
                            if isinstance(event_names, list) and len(event_names) >= 2:
                                # Array format: ["Team A", "Team B"]
                                home_team_name = event_names[0].lower()
                                away_team_name = event_names[1].lower()
                            elif isinstance(event_names, list) and len(event_names) == 1:
                                # Single string format: ["Team A v Team B"]
                                team_string = event_names[0]
                                if " v " in team_string:
                                    parts = team_string.split(" v ")
                                    if len(parts) == 2:
                                        home_team_name = parts[0].strip().lower()
                                        away_team_name = parts[1].strip().lower()
                                    else:
                                        continue
                                else:
                                    continue
                            else:
                                continue
                            
                            event_id = event.get("id")
                            
                            if not event_id:
                                continue
                                
                            # Skip events with variant indicators that don't exist in the original team names
                            event_name = f"{home_team_name} vs {away_team_name}"
                            should_skip = False
                            for indicator in variant_indicators:
                                if (indicator in event_name and 
                                    indicator not in home_team.lower() and 
                                    indicator not in away_team.lower()):
                                    should_skip = True
                                    break
                                
                            if should_skip:
                                logger.info(f"Skipping variant team: {event_name}")
                                continue
                                
                            # Calculate match score based on word matching
                            match_score = 0
                            home_words = set(word.lower() for word in home_team.lower().split() if len(word) > 1)
                            away_words = set(word.lower() for word in away_team.lower().split() if len(word) > 1)
                            event_home_words = set(word.lower() for word in home_team_name.split() if len(word) > 1)
                            event_away_words = set(word.lower() for word in away_team_name.split() if len(word) > 1)
                            
                            home_match_count = len(home_words.intersection(event_home_words))
                            away_match_count = len(away_words.intersection(event_away_words))
                            
                            # Perfect match check
                            if (home_team.lower() in home_team_name and away_team.lower() in away_team_name):
                                match_score += 10
                                    
                            # At least one word from each team must match
                            if home_match_count > 0 and away_match_count > 0:
                                match_score += home_match_count + away_match_count
                            else:
                                continue
                            
                                
                            # Check start time if available
                            time_match_score = 0
                            if pinnacle_start_time and "startTime" in event:
                                logger.info(f"Pinnacle start time: {pinnacle_start_time}")
                                logger.info(f"Nairabet start time: {event['startTime']}")
                                nairabet_start_time = event["startTime"]
                                try:
                                    # Both Pinnacle and Nairabet times are in milliseconds (Unix timestamp)
                                    # No need for timezone conversion, just compare the raw millisecond values
                                    time_diff_hours = abs(int(pinnacle_start_time) - int(nairabet_start_time)) / (1000 * 60 * 60)
                                    
                                    if time_diff_hours <= 1.0833:  # Within 1 hour and 5 minutes
                                        time_match_score = 10
                                        match_score += time_match_score
                                        # logger.info(f"Time match found: Pinnacle={pinnacle_start_time}, Nairabet={nairabet_start_time}, diff={time_diff_hours:.2f}h")
                                    else:
                                        logger.info(f"Time difference: {time_diff_hours:.2f} hours, skipping event - not the right game")
                                        continue  # Skip this event entirely
                                            
                                except Exception as e:
                                    logger.error(f"Error parsing time: {e}")
                                    continue  # Skip this event if time parsing fails
                                
                            # Add to potential matches if score is positive
                            if match_score > 0:
                                potential_matches.append({
                                "event_name": f"{home_team_name} vs {away_team_name}",
                                "event_id": event_id,
                                "score": match_score,
                                "strategy": search_term,
                                "home_team": home_team_name,
                                "away_team": away_team_name
                            })
                            # logger.info(f"Potential match: {event_name} (Score: {match_score})")
                    else:
                        logger.info(f"No data found in search response for term: {search_term}")
                else:
                    logger.warning(f"Search request failed with status: {response.status_code}")
                    # print(f"Response content: {response.text[:500]}...")
            
            except Exception as e:
                logger.error(f"Error searching for event with term '{search_term}': {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # If we have potential matches, return the one with the highest score
        if potential_matches:
            best_match = max(potential_matches, key=lambda x: x["score"])
            logger.info(f"Best match: {best_match['event_name']} (ID: {best_match['event_id']}, Score: {best_match['score']})")
            return best_match["event_id"]
        
        logger.warning("No matching event found on Nairabet")
        return None

    def __get_event_details(self, event_id):
        """Get detailed information about an event from Nairabet"""
        logger.info(f"Getting details for event ID: {event_id}")
        
        try:
            # Nairabet sports API event details endpoint
            details_url = f"https://sports-api.nairabet.com/v2/events/{event_id}"
            params = {
                'country': 'NG',
                'group': 'g3',
                'platform': 'desktop',
                'locale': 'en'
            }
        
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nairabet.com/",
                "x-sah-device": "5f40d3154db72f213ffd1fe7f7ad1cb8"
            }
            
            # Get proxy if available
            proxies = None
            if self.__config.get("use_proxies", False) and self.__accounts:
                # Use the first available account's proxy
                for acc in self.__accounts:
                    if acc.proxy:
                        proxies = acc.get_proxies()
                        logger.info(f"Using proxy for event details: {acc.proxy}")
                        break
            
            response = requests.get(details_url, params=params, headers=headers, proxies=proxies, timeout=10)
            response.raise_for_status()
            
            event_details = response.json()
            
            # Extract team names from the new response format
            event_names = event_details.get("eventNames", [])
            if len(event_names) >= 2:
                home_team = event_names[0]
                away_team = event_names[1]
                
                # Add team names to event details for compatibility
                event_details["homeTeam"] = home_team
                event_details["awayTeam"] = away_team
                event_details["eventId"] = event_id
                
                logger.info(f"Event details retrieved: {home_team} vs {away_team}")
                logger.info(f"Event ID: {event_id}")
                logger.info(f"Start time: {event_details.get('startTime')}")
                logger.info(f"Competition: {event_details.get('competitionName')}")
                
                return event_details
            else:
                logger.error(f"Invalid event names format: {event_names}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting event details: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_event_details: {e}")
            return None

    def __generate_nairabet_bet_url(self, event_details):
        """
        Generate Nairabet betting URL based on event details
        Format: https://www.nairabet.com/event/{eventId}
        """
        try:
            # Get event ID from event details
            event_id = event_details.get("eventId") or event_details.get("event_id") or event_details.get("id")
            
            if not event_id:
                logger.error(f"Missing event_id for URL generation: {event_details}")
                return None
            
            bet_url = f"{self.__bet_host}/event/{event_id}"
            logger.info(f"Generated Nairabet bet URL: {bet_url}")
            
            return bet_url
            
        except Exception as e:
            logger.error(f"Error generating bet URL: {e}")
            return None

    def __take_screenshot(self, reason: str) -> None:
        """
        Take a screenshot with timestamp and reason
        """
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            screenshot_path = f"{reason}_{timestamp}.png"
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as screenshot_error:
            logger.error(f"Failed to take screenshot: {screenshot_error}")

    def __wait_for_market_content(self, timeout_seconds: int = 15) -> None:
        """
        Explicitly wait for Nairabet market content to render.
        Waits until at least one of the known market containers is present.
        """
        try:
            # Ensure document is at least interactive/complete first
            WebDriverWait(self.driver, timeout_seconds).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )
        except Exception:
            # Continue to element-based checks even if readyState wait fails
            pass
        
        # Wait for the active market group to be present
        WebDriverWait(self.driver, timeout_seconds, poll_frequency=0.5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".event-details__market-groups"))
        )

    def __place_bet_with_selenium(self, account, bet_url, market_type, outcome, odds, stake, points=None, is_first_half=False, home_team=None, away_team=None):
        """
        Place a bet on Nairabet using Selenium
        
        Parameters:
        - account: BetAccount instance
        - bet_url: Nairabet betting URL for the event
        - market_type: Type of bet (moneyline, total, spread)
        - outcome: Outcome to bet on
        - odds: Expected odds
        - stake: Amount to stake
        - points: Points value for total/spread bets
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (from shaped_data)
        - away_team: Name of the away team (from shaped_data)
        
        Returns:
        - True if bet was placed successfully, False otherwise
        """
        try:
            # Always login before placing bet (this will also initialize browser if needed)
            logger.info("Logging in before placing bet...")
            login_success = self.__do_login_for_account(account)
            if not login_success:
                logger.error("Login failed, cannot place bet")
                return False
            
            logger.info(f"Navigating to betting page: {bet_url}")
            self.open_url(bet_url)
            # Wait for the market content to render instead of using sleep
            try:
                self.__wait_for_market_content(timeout_seconds=15)
                logger.info("found market content")
            except Exception as e:
                logger.warning(f"Market content not detected within wait window: {e}")
            time.sleep(3)
            
            # Check and handle betslip "Remove all" button
            try:
                remove_all_button = self.driver.find_element(By.CSS_SELECTOR, ".betslip-header__remove-all")
                if "betslip-header__remove-all--disabled" not in remove_all_button.get_attribute("class"):
                    logger.info("Remove all button is enabled, clicking it to clear betslip")
                    remove_all_button.click()
                    time.sleep(1)  # Wait for betslip to clear
                else:
                    logger.info("Remove all button is disabled, betslip is already empty")
            except Exception as e:
                logger.warning(f"Could not find or interact with Remove all button: {e}")
            
            # Find and click the market/outcome
            market_element = self.__get_market_selector(market_type, outcome, points, is_first_half, home_team, away_team)
            # logger.info(f"Market element: {market_element}")
            if not market_element:
                logger.error("Could not find market element")
                # time.sleep(100)
                return False
            
            try:
                logger.info(f"Found market element for: {market_type} - {outcome} - {points}")
                
                # # Verify odds before placing bet
                # try:
                #     # Use more specific selector to find odds within the correct div structure
                #     odds_element = market_element.find_element(By.CSS_SELECTOR, ".has-desc.m-outcome.multiple .odds")
                #     odds_text = odds_element.text.strip()
                #     import re
                #     odds_match = re.search(r'(\d+\.?\d*)', odds_text)
                #     if odds_match:
                #         actual_odds = float(odds_match.group(1))
                #         odds_diff = abs(actual_odds - odds)
                        
                #         if odds_diff > 0.1:  # Allow 0.1 difference
                #             bet_logger.error(f"⚠️ Odds mismatch! Expected: {odds}, Actual: {actual_odds}")
                #             bet_logger.error("Bet cancelled due to odds change")
                #             return False
                #         else:
                #             bet_logger.info(f"✅ Odds verified: {actual_odds} (expected: {odds})")
                # except Exception as e:
                #     bet_logger.error(f"Could not verify odds: {e}")
                
                # Simple direct clicking approach - no scrolling
                try:
                    # Wait for element to be clickable
                    WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable(market_element)
                    )
                    
                    # Direct click on the element
                    market_element.click()
                    logger.info(f"Clicked on market: {market_type} - {outcome} - {points}")
                    # time.sleep(2)
                    
                except Exception as click_error:
                    logger.error(f"Direct click failed, trying JavaScript click: {click_error}")
                    
                    # Fallback to JavaScript click
                    try:
                        self.driver.execute_script("arguments[0].click();", market_element)
                        logger.info(f"JavaScript clicked on market: {market_type} - {outcome} - {points}")
                        # time.sleep(2)
                    except Exception as js_error:
                        logger.error(f"JavaScript click also failed: {js_error}")
                        
                        # Last resort: try ActionChains
                        try:
                            actions = ActionChains(self.driver)
                            actions.move_to_element(market_element).click().perform()
                            logger.info(f"ActionChains clicked on market: {market_type} - {outcome} - {points}")
                            # time.sleep(2)
                        except Exception as action_error:
                            logger.error(f"All click methods failed: {action_error}")
                            raise Exception("All click methods failed")
                
            except Exception as e:
                    logger.error(f"Could not click market element: {e}")
                    return False
            
            # Enter stake amount using new Nairabet selectors
            try:
                # Fallback: Use JavaScript to find and set stake input
                logger.info("Trying JavaScript fallback for stake input")
                script = """
                var stakeInput = document.querySelector('.betslip-acca-bet__stake .betslip-stake .form-input__input');
                if (stakeInput) {
                    stakeInput.value = '';
                    stakeInput.value = arguments[0];
                    stakeInput.dispatchEvent(new Event('input', { bubbles: true }));
                    stakeInput.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
                """
                result = self.driver.execute_script(script, str(stake))
                if result:
                    logger.info(f"✅ Successfully entered stake via JavaScript: {stake}")
                else:
                    logger.error("JavaScript fallback failed - stake input not found")
                    return False
            except Exception as e:
                logger.error(f"Error entering stake with selector: {e}")
                try:
                    # Find the stake input using the new selector structure
                    stake_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".betslip-acca-bet__stake .betslip-stake .form-input__input"))
                    )
                    
                    # Clear existing value and enter new stake
                    stake_input.clear()
                    stake_input.send_keys(str(stake))
                    logger.info(f"✅ Successfully entered stake: {stake}")
                except Exception as js_error:
                    logger.error(f"fallback also failed: {js_error}")
                    return False
            
            # Place the bet using new Nairabet selectors
            try:
                # Wait for the bet button to be clickable
                place_bet_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.betslip-bet-button"))
                )
                
                # Check the button text to determine action needed
                button_text = place_bet_button.text.strip()
                logger.info(f"Found bet button with text: {button_text}")
                
                # Click the button
                place_bet_button.click()
                logger.info("Clicked bet button")
                
                # If button says "Accept Odds...", odds have changed - need to recalculate EV
                if "accept odds" in button_text.lower():
                    logger.warning("⚠️ Odds have changed! Recalculating EV with new Nairabet odds...")
                    
                    try:
                        # Get the shaped_data from the current bet context
                        current_shaped_data = getattr(self, '_current_shaped_data', None)
                        if not current_shaped_data:
                            logger.error("No shaped_data available for EV recalculation")
                            self.__take_screenshot("odds_change_no_shaped_data")
                            return False
                        
                        # Get event ID from shaped data and fetch event details
                        event_id = current_shaped_data.get("eventId")
                        if not event_id:
                            logger.error("No eventId found in shaped data")
                            self.__take_screenshot("odds_change_no_event_id")
                            return False
                        
                        # Get event details from Nairabet API to get exact odds
                        event_details = self.__get_event_details(event_id)
                        if not event_details:
                            logger.error("Failed to get event details from Nairabet API")
                            self.__take_screenshot("odds_change_no_event_details")
                            return False
                        
                        # Extract bet parameters from shaped_data
                        line_type = current_shaped_data["category"]["type"].lower()
                        outcome = current_shaped_data["category"]["meta"]["team"]
                        points = current_shaped_data["category"]["meta"].get("value")
                        is_first_half = current_shaped_data.get("periodNumber") == "1"
                        home_team = current_shaped_data["game"]["home"]
                        away_team = current_shaped_data["game"]["away"]
                        
                        # Get the exact market and odds from Nairabet API using the same method as initial bet
                        bet_code, new_odds, _ = self.__find_market_bet_code_with_points(
                            event_details, line_type, outcome, points, is_first_half, home_team, away_team
                        )
                        
                        if not new_odds:
                            logger.error("Could not get new odds from Nairabet API")
                            self.__take_screenshot("odds_change_no_odds_from_api")
                            return False
                        
                        logger.info(f"New odds from Nairabet API: {new_odds}")
                        
                        # Recalculate EV with new odds
                        new_ev = self.__calculate_ev(new_odds, current_shaped_data)
                        logger.info(f"📊 Recalculated EV with new odds {new_odds}: {new_ev:.2f}%")
                        
                        if new_ev > 0:
                            logger.info("✅ EV still positive, accepting odds change...")
                            time.sleep(1)  # Wait a moment for button to update
                            
                            # Click accept odds button
                            updated_button = WebDriverWait(self.driver, 10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.betslip-bet-button"))
                            )
                            updated_button.click()
                            logger.info("Clicked accept odds button")
                        else:
                            logger.warning(f"❌ EV turned negative ({new_ev:.2f}%), aborting bet...")
                            self.__take_screenshot("odds_change_negative_ev")
                            return False  # Abort this bet
                            
                    except Exception as odds_check_error:
                        logger.error(f"Error checking odds change: {odds_check_error}")
                        self.__take_screenshot("odds_change_error")
                        return False  # Any error = abort bet
                
                # Wait for success confirmation
                try:
                    success_element = WebDriverWait(self.driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".betslip-bet-receipt__title"))
                    )
                    
                    success_text = success_element.text.strip()
                    if "Bet Placed Successfully" in success_text:
                        logger.info("✅ Bet placed successfully!")
                        return True
                    else:
                        logger.warning(f"⚠️ Unexpected success message: {success_text}")
                        return False
                        
                except Exception as e:
                    logger.error(f"No success confirmation found: {e}")
                    # Take screenshot of failed bet state
                    try:
                        timestamp = time.strftime("%Y%m%d-%H%M%S")
                        screenshot_path = f"failed_bet_screenshot_{timestamp}.png"
                        self.driver.save_screenshot(screenshot_path)
                        logger.info(f"Failed bet screenshot saved to {screenshot_path}")
                    except Exception as screenshot_error:
                        logger.error(f"Failed to take failed bet screenshot: {screenshot_error}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error clicking place bet button: {e}")
                self.__take_screenshot("error_clicking_place_bet_button")
                return False
                
        except Exception as e:
            # Minimal recovery for Selenium tab crashes
            msg = str(e).lower()
            if ("tab crashed" in msg or "chrome not reachable" in msg or "disconnected" in msg or "invalid session id" in msg):
                logger.error("Detected browser/tab crash during bet placement. Restarting browser and retrying once...")
                self.__restart_browser(account)
                return self.__place_bet_with_selenium(account, bet_url, market_type, outcome, odds, stake, points, is_first_half)
            
            logger.error(f"Error placing bet with Selenium: {e}")
            # Take screenshot of error state
            try:
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                screenshot_path = f"error_screenshot_{timestamp}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Error screenshot saved to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to take error screenshot: {screenshot_error}")
            import traceback
            traceback.print_exc()
            return False

    def __get_market_selector(self, market_type, outcome, points=None, is_first_half=False, home_team=None, away_team=None):
        """
        Get the CSS selector for a specific market and outcome on Nairabet
        
        Parameters:
        - market_type: Type of bet (moneyline, total, spread)
        - outcome: Outcome to bet on
        - points: Points value for total/spread bets
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (from shaped_data)
        - away_team: Name of the away team (from shaped_data)
        
        Returns:
        - Element or None if not found
        """
        market_type_lower = market_type.lower()
        outcome_lower = outcome.lower()
        
        # Handle first half navigation
        if is_first_half:
            # Click halftime button first
            try:
                # Wait for the first half button to be present and clickable (4th li element)
                halftime_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".event-details__market-groups .horizontal-scroll-box__body li:nth-child(4) .horizontal-selector-option"))
                )
                
                # Try regular click first
                try:
                    halftime_button.click()
                    # print("Clicked first half tab")
                except Exception as click_error:
                    logger.error(f"Regular click failed, trying JavaScript click: {click_error}")
                    # Use JavaScript click as fallback
                    self.driver.execute_script("arguments[0].click();", halftime_button)
                    logger.info("JavaScript clicked first half tab")
                
                time.sleep(2)
            except Exception as e:
                logger.error(f"Could not click first half tab: {e}")
                return None
        
        # Get all market rows
        try:
            # Take screenshot before searching for market rows
            try:
                screenshot_path = f"market_search_{int(time.time())}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Market search screenshot saved to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to take market search screenshot: {screenshot_error}")
            market_rows = self.driver.find_elements(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            if not market_rows:
                logger.warning("No market rows found")
                return None
        except Exception as e:
            logger.error(f"Error finding market rows: {e}")
            return None
        
        # 1X2 (Moneyline) - First div from the list
        if market_type_lower == "moneyline" or market_type_lower == "money_line":
            return self.__find_1x2_outcome(market_rows[0] if market_rows else None, outcome_lower)
        
        # Over/Under
        elif market_type_lower == "total":
            if not points:
                return None
            return self.__find_total_outcome(points, outcome_lower)
        
        # Asian Handicap
        elif market_type_lower == "spread":
            if points is None:
                return None
            # Check if handicap is 0 - if so, use DNB (Draw No Bet) market instead
            logger.info(f"DEBUG: points={points}, points_float={points}, abs_points={abs(float(points))}")
            if abs(float(points)) < 0.01:  # Using small threshold for floating point comparison
                logger.info(f"Handicap is 0, looking for DNB (Draw No Bet) market instead of Asian Handicap")
                # For DNB, use team names from shaped_data (passed as parameters)
                return self.__find_dnb_outcome(outcome_lower, is_first_half, home_team, away_team)
            
            return self.__find_handicap_outcome(points, outcome_lower, home_team, away_team)
        
        return None
    
    def __find_1x2_outcome(self, market_row, outcome):
        """
        Find the 1X2 outcome element for Nairabet
        
        Parameters:
        - market_row: The market row element for 1X2 (not used in new implementation)
        - outcome: 'home', 'draw', or 'away'
        
        Returns:
        - Element or None if not found
        """
        try:
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get the first event-market div (1X2 market)
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            if not event_markets:
                logger.warning("No event-market divs found for 1X2")
                return None
            
            logger.info("finding 1x2")
            # First event-market div is for 1X2
            market_div = event_markets[0]
            
            # Get all event-market__cell divs (should be 3: home, draw, away)
            cells = market_div.find_elements(By.CSS_SELECTOR, ".event-market__cell")
            
            if len(cells) < 3:
                logger.warning(f"Expected 3 cells for 1X2, found {len(cells)}")
                return None
            
            # Map outcome to index: first=home, second=draw, third=away
            outcome_index = {"home": 0, "draw": 1, "away": 2}
            
            if outcome not in outcome_index:
                logger.error(f"Invalid 1X2 outcome: {outcome}")
                return None
            
            target_cell = cells[outcome_index[outcome]]
            
            # Get the button inside this cell
            button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
            
            # Verify odds
            try:
                odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                odds_text = odds_element.text.strip()
                logger.info(f"Found 1X2 {outcome} with odds: {odds_text}")
                return button
            except Exception as e:
                logger.error(f"Could not find odds in 1X2 outcome: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error finding 1X2 outcome: {e}")
            return None
    
    def __find_total_outcome(self, target_points, outcome):
        """
        Find the over/under outcome element for Nairabet
        
        Parameters:
        - target_points: Points value to look for
        - outcome: 'over' or 'under'
        
        Returns:
        - Element or None if not found
        """
        try:
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get all event-market divs and find the one with totals
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            
            totals_market_div = None
            for market_div in event_markets:
                try:
                    # Check if this market has totals by looking for totals-related text in header
                    header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                    header_text = header.text.strip()
                    
                    # Check for main totals or first half totals
                    if "Total Goals (O/U)" in header_text or "First Half Over/Under Goals" in header_text:
                        totals_market_div = market_div
                        logger.info(f"Found totals market: {header_text}")
                        break
                        
                except Exception as e:
                    # This market doesn't have the expected structure, continue to next
                    continue
            
            if not totals_market_div:
                logger.warning("No totals market found")
                return None
            
            # Get all event-market__row divs within this totals market
            rows = totals_market_div.find_elements(By.CSS_SELECTOR, ".event-market__row")
            
            for row in rows:
                try:
                    # Each row has 2 cells: first for under, second for over
                    cells = row.find_elements(By.CSS_SELECTOR, ".event-market__cell")
                    
                    if len(cells) < 2:
                        logger.warning(f"Expected 2 cells for totals row, found {len(cells)}")
                        continue
                    
                    # Check if this row has the target points by looking at cell titles
                    # Look for the cell that contains the target points
                    target_cell = None
                    found_points = False
                    
                    for cell in cells:
                        try:
                            # Check if cell has a title with points
                            title_element = cell.find_element(By.CSS_SELECTOR, ".event-market__cell-title")
                            title_text = title_element.text.strip()
                            
                            # Extract points value from title (e.g., "Over 7.5", "Under 2.5")
                            import re
                            match = re.search(r'(\d+\.?\d*)', title_text)
                            if match:
                                cell_points = float(match.group(1))
                        
                                # Check if this matches our target points
                                if abs(cell_points - float(target_points)) < 0.01:
                                    # Check if this cell matches our outcome
                                    if (outcome == "over" and "over" in title_text.lower()) or \
                                       (outcome == "under" and "under" in title_text.lower()):
                                        target_cell = cell
                                        found_points = True
                                        break
                        except Exception as e:
                            # Cell doesn't have expected structure, continue to next
                            continue
                    
                    if not found_points or not target_cell:
                                continue
                            
                    # Get the button inside this cell
                    button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                            
                    # Verify odds
                    try:
                        odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                        odds_text = odds_element.text.strip()
                        logger.info(f"Found total {outcome} {target_points} with odds: {odds_text}")
                        return button
                    except Exception as e:
                        logger.error(f"Could not find odds in total outcome: {e}")
                        continue
                                
                except Exception as e:
                    # Row doesn't match, continue to next
                    continue
                    
            logger.warning(f"Could not find total market for {target_points} {outcome}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding total outcome: {e}")
            return None
    
    def __find_handicap_outcome(self, target_points, outcome, home_team, away_team):
        """
        Find the Asian handicap outcome element for Nairabet
        
        Parameters:
        - target_points: Points value to look for
        - outcome: 'home' or 'away'
        
        Returns:
        - Element or None if not found
        """
        try:
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get all event-market divs and find the one with handicap
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            
            for market_div in event_markets:
                try:
                    # Check if this market has handicap by looking for handicap-related text
                    header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                    header_text = header.text.strip().lower()
                    
                    if "handicap" in header_text:
                        # Found handicap market, now look for the specific points
                        rows = market_div.find_elements(By.CSS_SELECTOR, ".event-market__row")
                        
                        for row in rows:
                            try:
                                cells = row.find_elements(By.CSS_SELECTOR, ".event-market__cell")
                                
                                if len(cells) < 2:
                                    continue
                    
                                # Check if this row has the target points
                                # The points might be in the row structure or we need to find the right row
                                # Check each cell to find the one with the correct team and points
                                target_cell = None
                                
                                for i, cell in enumerate(cells):
                                    try:
                                        # Get the cell text to check team name and points
                                        cell_text = cell.text.strip()
                                        # logger.info(f"Checking cell {i}: '{cell_text}'")
                                        
                                        # Check if this cell contains the target team name and points
                                        if outcome == "home" and home_team in cell_text and "Draw" not in cell_text:
                                            # Look for points after the team name (e.g., "NAC Breda -2")
                                            target_points_str = str(target_points)
                                            if target_points > 0 and not target_points_str.startswith('+'):
                                                # For positive points, ensure we look for the "+" sign
                                                target_points_str = f"+{target_points}"
                                            
                                            if target_points_str in cell_text:
                                                target_cell = cell
                                                logger.info(f"Found home team cell with correct points: {target_points_str} - {cell_text}")
                                                break
                                        elif outcome == "away" and away_team in cell_text and "Draw" not in cell_text:
                                            # Look for points after the team name (e.g., "AZ Alkmaar +2")
                                            target_points_str = str(target_points)
                                            if target_points > 0 and not target_points_str.startswith('+'):
                                                # For positive points, ensure we look for the "+" sign
                                                target_points_str = f"+{target_points}"
                                            
                                            if target_points_str in cell_text:
                                                target_cell = cell
                                                logger.info(f"Found away team cell with correct points: {target_points_str} - {cell_text}")
                                                break
                                    except Exception as e:
                                        logger.debug(f"Error checking cell {i}: {e}")
                                        continue
                                
                                if target_cell:
                                    # Get the button inside this cell
                                    button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                                    
                                    # Verify odds
                                    try:
                                        odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                                        odds_text = odds_element.text.strip()
                                        logger.info(f"Found handicap {outcome} {target_points} with odds: {odds_text}")
                                        return button
                                    except Exception as e:
                                        logger.error(f"Could not find odds in handicap outcome: {e}")
                                        continue
                                else:
                                    logger.debug(f"No cell found for {outcome} team with points {target_points}")
                                    continue
                                    
                            except Exception as e:
                                # Row doesn't match, continue to next
                                continue
                        
                        # If we found the handicap market but no matching row, break
                        break
                        
                except Exception as e:
                    # This market doesn't have the expected structure, continue to next
                    continue
            
            logger.info(f"Could not find handicap market for {target_points} {outcome}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding handicap outcome: {e}")
            return None

    def __find_dnb_outcome(self, outcome, is_first_half=False, home_team=None, away_team=None):
        """
        Find the DNB (Draw No Bet) outcome element for Nairabet
        
        Parameters:
        - outcome: 'home' or 'away'
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (optional)
        - away_team: Name of the away team (optional)
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info(f"Finding DNB outcome for {outcome}, {is_first_half}, {home_team}, {away_team}")
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get all event-market divs and find the one with "Draw No Bet"
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            
            dnb_market_div = None
            for market_div in event_markets:
                try:
                    # Check if this market has "Draw No Bet" in the header
                    header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                    header_text = header.text.strip()
                    
                    if "Draw No Bet" in header_text:
                        dnb_market_div = market_div
                        logger.info(f"Found DNB market: {header_text}")
                        break
                        
                except Exception as e:
                    # This market doesn't have the expected structure, continue to next
                    continue
            
            if not dnb_market_div:
                logger.warning("No DNB market found")
                return None
            
            # Get all event-market__row divs within this DNB market
            rows = dnb_market_div.find_elements(By.CSS_SELECTOR, ".event-market__row")
            
            if not rows:
                logger.warning("No rows found in DNB market")
                return None
            
            # Use the first row (there's usually only one for DNB)
            row = rows[0]
            cells = row.find_elements(By.CSS_SELECTOR, ".event-market__cell")
            
            if len(cells) < 1:
                logger.warning(f"Expected at least 1 cell for DNB, found {len(cells)}")
                return None
            
            # Check each cell for team name to determine which one matches our outcome
            target_cell = None
            
            for cell in cells:
                try:
                    # Get the team name from the cell title
                    title_element = cell.find_element(By.CSS_SELECTOR, ".event-market__cell-title")
                    team_name = title_element.text.strip()
                    
                    # Check if this cell has a button (not empty)
                    try:
                        button = cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                        # Cell has a button, so it's not empty
                    except Exception:
                        # Cell is empty, skip it
                        continue
                    
                    # Determine if this cell is for home or away based on team name
                    if home_team and away_team:
                        # Use provided team names for exact matching
                        if outcome == "home" and team_name.lower() == home_team.lower():
                            target_cell = cell
                            logger.info(f"Found DNB home team: {team_name}")
                            break
                        elif outcome == "away" and team_name.lower() == away_team.lower():
                            target_cell = cell
                            logger.info(f"Found DNB away team: {team_name}")
                            break
                    else:
                        # Fallback: use first non-empty cell for home, second for away
                        if outcome == "home" and target_cell is None:
                            target_cell = cell
                            logger.info(f"Found DNB home team: {team_name}")
                        elif outcome == "away" and target_cell is None:
                            target_cell = cell
                            logger.info(f"Found DNB away team: {team_name}")
                        
                        # If we found both outcomes or the specific one we need, break
                        if target_cell is not None:
                            break
                
                except Exception as e:
                    # Cell doesn't have expected structure, continue to next
                    continue
                    
            if not target_cell:
                logger.warning(f"Could not find target cell for DNB {outcome}")
                return None
            
            # Get the button inside this cell
            try:
                button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                
                # Verify odds
                try:
                    odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                    odds_text = odds_element.text.strip()
                    logger.info(f"Found DNB {outcome} with odds: {odds_text}")
                    return button
                except Exception as e:
                    logger.error(f"Could not find odds in DNB outcome: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error finding DNB outcome: {e}")
                return None
            
        except Exception as e:
            logger.error(f"Error finding DNB outcome: {e}")
            return None

        

    def __place_bet_with_available_account(self, bet_data):
        """
        Place a bet using all available accounts
        
        Parameters:
        - bet_data: Dictionary with bet information
        
        Returns:
        - True if at least one bet was placed successfully, False otherwise
        """
        try:
            # Get max concurrent bets from config
            max_total_bets = self.__config.get("max_total_concurrent_bets", 5)
            
            # Count total current bets across all accounts
            total_current_bets = sum(account.current_bets for account in self.__accounts)
            
            # Check if we've reached the global limit
            # if total_current_bets >= max_total_bets:
            #     logger.warning(f"Reached global limit of {max_total_bets} concurrent bets. Queuing bet.")
            #     # Re-add to queue with a delay
            #     threading.Timer(30.0, lambda: self.__bet_queue.put(bet_data)).start()
            #     return False
            
            # Track if at least one bet was placed successfully
            any_bet_placed = False
            
            # Find all available accounts and place bets with each
            logger.info(f"Checking {len(self.__accounts)} accounts")
            logger.info(f"account names: {[account.username for account in self.__accounts]}")

            for account in self.__accounts:
                logger.info(f"just checking account {account.username}")
            for account in self.__accounts:
                logger.info(f"Checking account {account.username}")
                if account.can_place_bet():
                    logger.info(f"Account {account.username} can place bet")
                    # Check if login is needed
                    # if account.needs_login():
                    #     try:
                    #         self.__do_login_for_account(account)
                    #     except Exception as e:
                    #         print(f"Failed to login to account {account.username}: {e}")
                    #         continue  # Try next account
                    
                    # Try to place bet with this account
                    account.increment_bets()
                    
                    # Store shaped_data for EV recalculation if odds change
                    self._current_shaped_data = bet_data["shaped_data"]
                    
                    success = self.__place_bet_with_selenium(
                        account,
                        self.__generate_nairabet_bet_url(bet_data["event_details"]),
                        bet_data["market_type"],
                        bet_data["outcome"],
                        bet_data["odds"],
                        bet_data["stake"],  # Use pre-calculated stake
                        bet_data["shaped_data"]["category"]["meta"].get("value"),
                        bet_data.get("is_first_half", False),
                        bet_data["shaped_data"]["game"]["home"],  # home_team from shaped_data
                        bet_data["shaped_data"]["game"]["away"]   # away_team from shaped_data
                    )
                    
                    if success:
                        account.decrement_bets()
                        logger.info(f"Bet placed successfully with account {account.username}")
                        any_bet_placed = True
                    else:
                        # If bet failed, decrement the bet counter
                        account.decrement_bets()
                else:
                    logger.info(f"Account {account.username} cannot place bet")
            
            if not any_bet_placed:
                # logger.warning("No available accounts to place bet.")
                # Re-add to queue with a delay
                # threading.Timer(60.0, lambda: self.__bet_queue.put(bet_data)).start()
                return False
            
            return any_bet_placed
        except Exception as e:
            logger.error(f"Error in place_bet_with_available_account: {e}")
            # Close browser on error
            self.cleanup()
            raise

    def __calculate_ev(self, bet_odds, shaped_data):
        """
        Calculate the Expected Value (EV) for a bet
        
        Parameters:
        - bet_odds: The decimal odds offered by MSport
        - shaped_data: The data from Pinnacle with prices
        
        Returns:
        - EV percentage
        """
        logger.info(f"Shaped data used for calculating ev {shaped_data}")
        line_type = shaped_data["category"]["type"].lower()
        outcome = shaped_data["category"]["meta"]["team"]
        points = shaped_data["category"]["meta"].get("value")
        
        # Determine if this is for first half or full match
        is_first_half = False
        period_key = "num_0"  # Default to full match
        if "periodNumber" in shaped_data and shaped_data["periodNumber"] == "1":
            is_first_half = True
            period_key = "num_1"
            
        # Get the event ID to fetch latest odds from Pinnacle
        event_id = shaped_data.get("eventId")
        
        # For Asian handicaps (spread), invert points for away team when fetching Pinnacle odds
        pinnacle_points = points
        if line_type == "spread" and outcome == "away" and points is not None:
            pinnacle_points = -points
            logger.info(f"Asian handicap away team: inverting points from {points} to {pinnacle_points} for Pinnacle odds")
        
        # Fetch latest odds from Pinnacle API if event ID is available
        latest_prices = self.__fetch_latest_pinnacle_odds(event_id, line_type, pinnacle_points, outcome, period_key)
        
        # If we couldn't get latest odds, return -100 EV instead of using fallback
        if not latest_prices:
            logger.info("No latest Pinnacle odds available, returning -100 EV")
            return -100  # Return negative EV instead of fallback
        
        # Use the latest prices we fetched
        decimal_prices = latest_prices
        logger.info(f"Using latest Pinnacle odds: {decimal_prices}")
        
        # Store the prices for later use in stake calculation
        shaped_data["_decimal_prices"] = decimal_prices
        
        # Calculate no-vig prices
        if not decimal_prices:
            logger.info("No prices found for calculation")
            return -100  # Negative EV as fallback
            
        no_vig_prices = calculate_no_vig_prices(decimal_prices)
        
        # Map outcome to the corresponding key in no_vig_prices
        if line_type == "total":
            # Map over/under to home/away
            outcome_map = {"over": "home", "under": "away"}
            outcome_key = outcome_map.get(outcome.lower(), outcome.lower())
        else:
            outcome_key = outcome.lower()
        
        # Store the outcome key for later use in stake calculation
        shaped_data["_outcome_key"] = outcome_key
        
        # Get the true price using the power method (or choose another method if preferred)
        true_price = no_vig_prices["power"].get(outcome_key)
        
        if not true_price:
            logger.info(f"No no-vig price found for outcome {outcome_key}")
            return -100  # Negative EV as fallback
            
        # Calculate EV
        ev = calculate_ev(bet_odds, true_price)
        # logger.info(f"Bet odds: {bet_odds}, outcome: {outcome_key}, True price: {true_price}, EV: {ev:.2f}%")
        
        # Format EV with emoji and market info
        emoji = "✅" if ev > 0 else "❌"
        line_type = line_type
        outcome = outcome_key
        points = points
        is_first_half = is_first_half
        
        if line_type == "spread":
            if abs(points) < 0.01:  # DNB
                market_info = f"DNB {outcome}"
            else:
                market_info = f"handicap {points:+g} {outcome}"
        elif line_type == "total":
            market_info = f"{outcome} {points}"
        elif line_type == "money_line":
            market_info = f"1x2 {outcome}"
        else:
            market_info = f"{line_type} {outcome}"
        
        first_half_info = ", firsthalf: true" if is_first_half else ""
        
        formatted_ev = f"({emoji}{market_info}{first_half_info})"
        logger.info(f"Bet odds: {bet_odds}, outcome: {outcome_key}, True price: {true_price}, EV: {ev:.2f}%")
        logger.info(f"{formatted_ev}")
        
        return ev
        
    def __fetch_latest_pinnacle_odds(self, event_id, line_type, points, outcome, period_key):
        """
        Fetch the latest odds from Pinnacle API for a specific event
        
        Parameters:
        - event_id: The Pinnacle event ID
        - line_type: The type of bet (spread, moneyline, total)
        - points: The points value for the bet
        - outcome: The outcome (home, away, draw, over, under)
        - period_key: The period key (num_0 for full match, num_1 for first half)
        
        Returns:
        - Dictionary with the latest decimal prices or None if not found
        """
        if not event_id:
            logger.info("No event ID provided, cannot fetch latest odds")
            return None
            
        pinnacle_api_host = os.getenv("PINNACLE_HOST")
        if not pinnacle_api_host:
            logger.info("Pinnacle Events API host not configured")
            return None
            
        # Get proxy from first account if available
        proxies = None
        if self.__accounts and hasattr(self.__accounts[0], 'get_proxies'):
            proxies = self.__accounts[0].get_proxies()
            # if proxies:
            #     # logger.info(f"Using proxy for Pinnacle odds: {self.__accounts[0].proxy}")
            
        try:
            url = f"{pinnacle_api_host}/events/{event_id}"
            logger.info(f"Fetching latest odds from: {url}")
            
            response = requests.get(url)
            if response.status_code != 200:
                logger.info(f"Failed to fetch latest odds: HTTP {response.status_code}")
                return None
                
            event_data = response.json()
            if not event_data or "data" not in event_data or not event_data["data"]:
                logger.info("No data returned from Pinnacle API")
                return None
                
            if event_data["data"] == None or event_data["data"] == "null":
                return None
            
            # Extract the period data
            periods = event_data["data"].get("periods", {})
            if not periods:  # Check if periods is None or empty
                logger.info("No periods data found in Pinnacle API response")
                return None
                
            period = periods.get(period_key, {})
            if not period:  # Check if period is None or empty
                logger.info(f"No period data found for period key: {period_key}")
                return None
            
            # Extract the appropriate odds based on line type
            decimal_prices = {}
            
            if line_type == "money_line":
                money_line = period.get("money_line", {})
                if money_line:  # Check if money_line data exists
                    if "home" in money_line:
                        decimal_prices["home"] = float(money_line["home"])
                    if "away" in money_line:
                        decimal_prices["away"] = float(money_line["away"])
                    if "draw" in money_line:
                        decimal_prices["draw"] = float(money_line["draw"])
                else:
                    logger.info("No money_line data found in period")
                    
            elif line_type == "spread":
                spreads = period.get("spreads", {})
                if spreads:  # Check if spreads data exists
                    # Look for exact spread points match
                    exact_spread = None
                    
                    for spread_key, spread_data in spreads.items():
                        try:
                            spread_points = float(spread_data.get("hdp", 0))
                            # Only check for exact match, no closest approximation
                            if abs(spread_points - float(points)) < 0.01:  # Exact match with small tolerance
                                exact_spread = spread_data
                                break
                        except (ValueError, TypeError):
                            continue
                    
                    if exact_spread:
                        if "home" in exact_spread:
                            decimal_prices["home"] = float(exact_spread["home"])
                        if "away" in exact_spread:
                            decimal_prices["away"] = float(exact_spread["away"])
                    else:
                        logger.info(f"No exact spread match found for points: {points}")
                else:
                    logger.info("No spreads data found in period")
                    
            elif line_type == "total":
                totals = period.get("totals", {})
                if totals:  # Check if totals data exists
                    # Look for exact total points match
                    exact_total = None
                    
                    for total_key, total_data in totals.items():
                        try:
                            total_points = float(total_data.get("points", 0))
                            # Only check for exact match, no closest approximation
                            if abs(total_points - float(points)) < 0.01:  # Exact match with small tolerance
                                exact_total = total_data
                                break
                        except (ValueError, TypeError):
                            continue
                    
                    if exact_total:
                        if "over" in exact_total:
                            decimal_prices["home"] = float(exact_total["over"])  # Over as home
                        if "under" in exact_total:
                            decimal_prices["away"] = float(exact_total["under"])  # Under as away
                    else:
                        logger.info(f"No exact total match found for points: {points}")
                else:
                    logger.info("No totals data found in period")
            
            return decimal_prices if decimal_prices else None
            
        except Exception as e:
            logger.error(f"Error fetching latest odds: {e}")
            return None

    def __power_method_devig(self, odds_list, max_iter=100, tol=1e-10):
        """
        Devigs a list of decimal odds using the power method.
        Returns the fair probabilities (without the bookmaker's margin).
        
        Parameters:
        - odds_list: List of decimal odds values
        - max_iter: Maximum number of iterations for optimization
        - tol: Tolerance for convergence
        
        Returns:
        - List of fair probabilities
        """
        def implied_probs(power):
            return [o**-power for o in odds_list]

        def objective(power):
            return abs(sum(implied_probs(power)) - 1)

        res = minimize_scalar(objective, bounds=(0.001, 10), method='bounded')
        power = res.x
        probs = implied_probs(power)
        total = sum(probs)
        return [p / total for p in probs]  # normalized
        
    def __kelly_stake(self, prob, odds, bankroll):
        """
        Calculate the optimal stake using the Kelly Criterion
        
        Parameters:
        - prob: Probability of winning
        - odds: Decimal odds
        - bankroll: Available bankroll
        
        Returns:
        - Recommended stake amount (0 if no bet recommended)
        """
        b = odds - 1
        q = 1 - prob
        numerator = (b * prob - q)
        if numerator <= 0:
            return 0  # no bet
        return bankroll * numerator / b
        
    def __round_stake_humanlike(self, stake):
        """
        Round stake to more human-like amounts to avoid detection
        
        Parameters:
        - stake: The calculated stake amount
        
        Returns:
        - Rounded stake that looks more natural
        """
        if stake < 50:
            # For small amounts, round to nearest 5 or 10
            if stake < 20:
                return round(stake / 5) * 5  # Round to nearest 5
            else:
                return round(stake / 10) * 10  # Round to nearest 10
        
        elif stake < 200:
            # For medium amounts (50-200), round to nearest 10 or 25
            if stake < 100:
                return round(stake / 10) * 10  # Round to nearest 10
            else:
                return round(stake / 25) * 25  # Round to nearest 25
        
        elif stake < 1000:
            # For larger amounts (200-1000), round to nearest 50
            return round(stake / 50) * 50
        
        elif stake < 5000:
            # For large amounts (1000-5000), round to nearest 100
            # Examples: 1506 -> 1500, 2453 -> 2500
            return round(stake / 100) * 100
        
        elif stake < 10000:
            # For very large amounts (5000-10000), round to nearest 250
            return round(stake / 250) * 250
        
        else:
            # For extremely large amounts (10000+), round to nearest 500
            return round(stake / 500) * 500

    def __get_stake_limits_for_odds(self, odds):
        """
        Get the appropriate min and max stake limits based on odds
        
        Parameters:
        - odds: The decimal odds for the bet
        
        Returns:
        - Tuple of (min_stake, max_stake)
        """
        # Check if odds fall into any defined range
        for range_name, range_config in self.__odds_based_stakes.items():
            min_odds = range_config.get("min_odds", 0)
            max_odds = range_config.get("max_odds", float('inf'))
            
            # Check if odds fall within this range
            if min_odds <= odds <= max_odds:
                min_stake = range_config.get("min_stake", self.__min_stake)
                max_stake = range_config.get("max_stake", self.__max_stake)
                logger.info(f"Using {range_name} stake limits for odds {odds:.2f}: min={min_stake}, max={max_stake}")
                return min_stake, max_stake
        
        # If no range matches, use default limits
        logger.info(f"Using default stake limits for odds {odds:.2f}: min={self.__min_stake}, max={self.__max_stake}")
        return self.__min_stake, self.__max_stake

    def __calculate_stake(self, bet_odds, shaped_data, bankroll):
        """
        Calculate the stake amount based on Kelly criterion
        
        Parameters:
        - bet_odds: The decimal odds offered by Nairabet
        - shaped_data: The data with prices and outcome information
        
        Returns:
        - Recommended stake amount (rounded to human-like values)
        """
        # Get the stored decimal prices and outcome key
        decimal_prices = shaped_data.get("_decimal_prices", {})
        outcome_key = shaped_data.get("_outcome_key", "")
        
        if not decimal_prices or not outcome_key:
            logger.info("Missing required data for stake calculation")
            return self.__round_stake_humanlike(10)  # Default stake if calculation not possible
        
        # Extract values into a list for power method
        odds_values = list(decimal_prices.values())
        if not odds_values:
            return self.__round_stake_humanlike(10)  # Default stake
        
        # Calculate fair probabilities using power method
        fair_probs = self.__power_method_devig(odds_values)
        
        # Map the probabilities back to their outcomes
        outcome_probs = {}
        for i, (outcome, _) in enumerate(decimal_prices.items()):
            if i < len(fair_probs):
                outcome_probs[outcome] = fair_probs[i]
        
        # Get the probability for our specific outcome
        if outcome_key not in outcome_probs:
            logger.info(f"Outcome {outcome_key} not found in probabilities")
            return self.__round_stake_humanlike(10)  # Default stake
            
        outcome_prob = outcome_probs[outcome_key]
        
        
        # Calculate Kelly stake
        full_kelly = self.__kelly_stake(outcome_prob, bet_odds, bankroll)
        
        # Use 30% of Kelly as a more conservative approach
        fractional_kelly = full_kelly * 0.3
        
        # Get odds-based stake limits
        min_stake, max_stake = self.__get_stake_limits_for_odds(bet_odds)
        
        stake = max(min_stake, min(fractional_kelly, max_stake))
        
        # Round to human-like amounts
        rounded_stake = self.__round_stake_humanlike(stake)
        
        logger.info(f"Probability: {outcome_prob:.4f}, Full Kelly: {full_kelly:.2f}, "
              f"Fractional Kelly (30%): {fractional_kelly:.2f}, Calculated Stake: {stake:.2f}, "
              f"Rounded Stake: {rounded_stake:.2f}")
        
        return rounded_stake

    def __generate_game_id(self, home_team, away_team, pinnacle_start_time=None):
        """
        Generate a unique identifier for a game to track if it has been processed
        """
        if pinnacle_start_time:
            return f"{home_team}_{away_team}_{pinnacle_start_time}"
        return f"{home_team}_{away_team}"
    
    def __generate_bet_signature(self, event_id, market_id, outcome_id, odds, handicap=None, is_first_half=False):
        """
        Generate a unique signature for a bet to avoid duplicates
        
        Parameters:
        - event_id: The event ID
        - market_id: The market ID (e.g., "HC", "TGOU", "1x2")
        - outcome_id: The outcome ID (e.g., "HOME", "AWAY", "OVER", "UNDER")
        - odds: The odds value
        - handicap: The handicap value (for spread bets)
        - is_first_half: Whether it's a first half bet
        
        Returns:
        - String signature for the bet
        """
        signature_parts = [str(event_id), str(market_id), str(outcome_id)]
        if handicap is not None:
            signature_parts.append(str(handicap))
        if is_first_half:
            signature_parts.append("FH")
        return "_".join(signature_parts)
    
    def __is_bet_already_placed(self, bet_signature):
        """
        Check if a bet with the same signature has already been placed
        
        Parameters:
        - bet_signature: The bet signature to check
        
        Returns:
        - True if bet already placed, False otherwise
        """
        return bet_signature in self.__placed_bets
    
    def __store_placed_bet(self, bet_signature, bet_details):
        """
        Store details of a placed bet
        
        Parameters:
        - bet_signature: The bet signature
        - bet_details: Dictionary with bet details
        """
        # Limit to max 1000 bets
        if len(self.__placed_bets) >= 1000:
            # Remove oldest bet (first item in dict)
            oldest_key = next(iter(self.__placed_bets))
            del self.__placed_bets[oldest_key]
        
        self.__placed_bets[bet_signature] = bet_details
        logger.info(f"Stored bet: {bet_signature}")
    
    def __add_found_outcome(self, game_id, line_type, outcome):
        """
        Add a found outcome to the game tracking to avoid checking opposite outcomes
        
        Parameters:
        - game_id: The game identifier
        - line_type: The line type (spread, money_line, total)
        - outcome: The outcome that was found (home, away, over, under, etc.)
        """
        if game_id not in self.__game_found_outcomes:
            self.__game_found_outcomes[game_id] = set()
        
        outcome_key = f"{line_type}_{outcome}"
        self.__game_found_outcomes[game_id].add(outcome_key)
        logger.info(f"Added found outcome for {game_id}: {outcome_key}")
    
    def __should_skip_outcome(self, game_id, line_type, outcome):
        """
        Check if we should skip checking this outcome based on found outcomes
        
        For spread and money_line: If we found "home" for either line type, only check "home" for both.
        If we found "away" for either line type, only check "away" for both.
        
        For total: Check if we have the opposite outcome (over/under)
        
        Parameters:
        - game_id: The game identifier
        - line_type: The line type (spread, money_line, total)
        - outcome: The outcome to check
        
        Returns:
        - True if we should skip this outcome, False otherwise
        """
        if game_id not in self.__game_found_outcomes:
            return False
        
        found_outcomes = self.__game_found_outcomes[game_id]
        
        # For spread and money_line, check if we have found home or away for either line type
        if line_type in ["spread", "money_line"]:
            # Check if we have found "home" for either spread or money_line
            has_home_spread = "spread_home" in found_outcomes
            has_home_moneyline = "money_line_home" in found_outcomes
            has_away_spread = "spread_away" in found_outcomes
            has_away_moneyline = "money_line_away" in found_outcomes
            
            # If we found "home" for either line type, only allow "home" outcomes
            if has_home_spread or has_home_moneyline:
                if outcome.lower() != "home":
                    logger.info(f"Skipping {line_type} {outcome} for {game_id} - already found home outcome for spread/moneyline")
                    return True
            
            # If we found "away" for either line type, only allow "away" outcomes
            elif has_away_spread or has_away_moneyline:
                if outcome.lower() != "away":
                    logger.info(f"Skipping {line_type} {outcome} for {game_id} - already found away outcome for spread/moneyline")
                    return True
        
        # For total, check if we have the opposite outcome
        elif line_type == "total":
            if outcome.lower() == "over":
                opposite_key = f"{line_type}_under"
            elif outcome.lower() == "under":
                opposite_key = f"{line_type}_over"
            else:
                return False
            
            if opposite_key in found_outcomes:
                logger.info(f"Skipping {line_type} {outcome} for {game_id} - already found opposite outcome")
                return True
        
        return False
    
    def __map_asian_handicap_to_nairabet(self, points):
        """
        Map Pinnacle Asian Handicap values to Nairabet regular handicap format
        
        Asian handicaps with .5 are mapped to whole numbers by removing the decimal:
        -2.5 → -2, -1.5 → -1, -0.5 → 0, +0.5 → +1, +1.5 → +2, etc.
        
        Parameters:
        - points: Asian handicap value from Pinnacle
        
        Returns:
        - Mapped handicap value for Nairabet
        """
        if points % 1 == 0.5:  # Has .5 decimal
            if points > 0:
                return int(points + 0.5)  # +0.5 → +1, +1.5 → +2, etc.
            else:
                return int(points + 0.5)  # -0.5 → 0, -1.5 → -1, -2.5 → -2, etc.
        else:
            return int(points)  # Whole numbers stay the same
    
    def __check_all_markets_for_game(self, event_details, shaped_data):
        """
        Check all available markets for a game and return those that meet EV threshold
        
        Returns:
        - List of tuples: (market_type, outcome, odds, points, ev, is_first_half, stake)
        """
        available_markets = []
        
        # Get basic game info
        home_team = event_details.get("homeTeam", "")
        away_team = event_details.get("awayTeam", "")
        sport_id = event_details.get("sportId", "1")
        
        # Generate game ID for outcome tracking
        game_id = self.__generate_game_id(home_team, away_team)
        
        # Check both normal and first half markets
        for is_first_half in [False, True]:
            period_suffix = " (1st Half)" if is_first_half else ""
            
            # Check Moneyline markets
            logger.info(f"\033[1m\033[1;36mChecking moneyline markets{period_suffix} for {home_team} vs {away_team}\033[0m")
            # logger.info(f"Checking moneyline markets{period_suffix} for {home_team} vs {away_team}")
            for outcome in ["home", "away", "draw"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "money_line", outcome):
                    continue
                bet_code, odds, _ = self.__find_market_bet_code_with_points(
                    event_details, "money_line", None, outcome, is_first_half, sport_id, home_team, away_team
                )
                if bet_code and odds:
                    # Create modified shaped data for this specific market
                    modified_shaped_data = shaped_data.copy()
                    modified_shaped_data["category"]["type"] = "money_line"
                    modified_shaped_data["category"]["meta"]["team"] = outcome
                    modified_shaped_data["category"]["meta"]["value"] = None
                    if is_first_half:
                        modified_shaped_data["periodNumber"] = "1"
                    
                    ev = self.__calculate_ev(odds, modified_shaped_data)
                    if ev > self.__min_ev:
                        # Check if Nairabet odds exceed maximum allowed
                        if odds > self.__max_pinnacle_odds:
                            logger.info(f"Nairabet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                            continue
                        
                        # Calculate stake for this specific market
                        stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                        available_markets.append(("money_line", outcome, odds, None, ev, is_first_half, stake))
                        
                        # Track this found outcome to avoid checking opposite outcomes
                        self.__add_found_outcome(game_id, "money_line", outcome)
                        # logger.info(f"Moneyline{period_suffix} {outcome}: EV {ev:.2f}% (odds: {odds}, stake: {stake:.2f})")
        
        # Check Total markets (Over/Under)
        for is_first_half in [False, True]:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"\033[1m\033[1;36mChecking total markets{period_suffix} for {home_team} vs {away_team}\033[0m")
            # logger.info(f"Checking total markets{period_suffix} for {home_team} vs {away_team}")
            
            for outcome in ["over", "under"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "total", outcome):
                    continue
                    
                # Try common total points: 0.5, 1.5, 2.5, 3.5, 4.5, 5.5
                for points in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]:
                    bet_code, odds, actual_points = self.__find_market_bet_code_with_points(
                        event_details, "total", points, outcome, is_first_half, sport_id, home_team, away_team
                    )
                    if bet_code and odds:
                        # Create modified shaped data for this specific market
                        modified_shaped_data = shaped_data.copy()
                        modified_shaped_data["category"]["type"] = "total"
                        modified_shaped_data["category"]["meta"]["team"] = outcome
                        modified_shaped_data["category"]["meta"]["value"] = actual_points
                        if is_first_half:
                            modified_shaped_data["periodNumber"] = "1"
                        
                        ev = self.__calculate_ev(odds, modified_shaped_data)
                        if ev > self.__min_ev:
                            # Check if Nairabet odds exceed maximum allowed
                            if odds > self.__max_pinnacle_odds:
                                logger.info(f"Nairabet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                                continue
                            
                            # Calculate stake for this specific market
                            stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                            available_markets.append(("total", outcome, odds, actual_points, ev, is_first_half, stake))
                            
                            # Track this found outcome to avoid checking opposite outcomes
                            self.__add_found_outcome(game_id, "total", outcome)
                            # logger.info(f"Total{period_suffix} {outcome} {actual_points}: EV {ev:.2f}% (odds: {odds}, stake: {stake:.2f})")
        
        # Check Asian Handicap markets (with mapping to Nairabet regular handicap)
        for is_first_half in [False, True]:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"\033[1m\033[1;36mChecking handicap markets{period_suffix} for {home_team} vs {away_team}\033[0m")
            # logger.info(f"Checking handicap markets{period_suffix} for {home_team} vs {away_team}")
            
            for outcome in ["home", "away"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "spread", outcome):
                    continue
                    
                # Try common handicap points: -2.5, -2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0, 2.5
                for points in [-4.5, -3.5, -2.5, -1.5, 0.5, 1.5, 2.5, 3.5, 4.5]:
                    # Map Pinnacle Asian Handicap to Nairabet regular handicap
                    nairabet_points = self.__map_asian_handicap_to_nairabet(points)
                    logger.info(f"Nairabet points: {nairabet_points}")
                    bet_code, odds, actual_points = self.__find_market_bet_code_with_points(
                        event_details, "spread", nairabet_points, outcome, is_first_half, sport_id, home_team, away_team
                    )
                    if bet_code and odds:
                        # Create modified shaped data for this specific market
                        # Use the original Pinnacle points for EV calculation
                        modified_shaped_data = shaped_data.copy()
                        modified_shaped_data["category"]["type"] = "spread"
                        modified_shaped_data["category"]["meta"]["team"] = outcome
                        modified_shaped_data["category"]["meta"]["value"] = points  # Use original Pinnacle points for EV
                        if is_first_half:
                            modified_shaped_data["periodNumber"] = "1"
                        
                        ev = self.__calculate_ev(odds, modified_shaped_data)
                        if ev > self.__min_ev:
                            # Check if Nairabet odds exceed maximum allowed
                            if odds > self.__max_pinnacle_odds:
                                logger.info(f"Nairabet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                                continue
                            
                            # Calculate stake for this specific market
                            stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                            # Store the Nairabet points for actual betting, but use Pinnacle points for EV display
                            available_markets.append(("spread", outcome, odds, nairabet_points, ev, is_first_half, stake))
                            
                            # Track this found outcome to avoid checking opposite outcomes
                            self.__add_found_outcome(game_id, "spread", outcome)
                            # logger.info(f"Handicap{period_suffix} {outcome} - Pinnacle {points} → Nairabet {nairabet_points}: EV {ev:.2f}% (odds: {odds}, stake: {stake:.2f})")
        
        # Check DNB markets (when handicap is 0)
        for is_first_half in [False, True]:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"\033[1m\033[1;36mChecking DNB markets{period_suffix} for {home_team} vs {away_team}\033[0m")
            # logger.info(f"Checking DNB markets{period_suffix} for {home_team} vs {away_team}")
            
            for outcome in ["home", "away"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "spread", outcome):
                    continue
                    
                bet_code, odds, _ = self.__find_market_bet_code_with_points(
                    event_details, "spread", 0.0, outcome, is_first_half, sport_id, home_team, away_team
                )
                if bet_code and odds:
                    # Create modified shaped data for this specific market
                    modified_shaped_data = shaped_data.copy()
                    modified_shaped_data["category"]["type"] = "spread"
                    modified_shaped_data["category"]["meta"]["team"] = outcome
                    modified_shaped_data["category"]["meta"]["value"] = 0.0
                    if is_first_half:
                        modified_shaped_data["periodNumber"] = "1"
                    
                    ev = self.__calculate_ev(odds, modified_shaped_data)
                    if ev > self.__min_ev:
                        # Check if Nairabet odds exceed maximum allowed
                        if odds > self.__max_pinnacle_odds:
                            logger.info(f"Nairabet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                            continue
                        
                        # Calculate stake for this specific market
                        stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                        available_markets.append(("DNB", outcome, odds, 0.0, ev, is_first_half, stake))
                        
                        # Track this found outcome to avoid checking opposite outcomes
                        self.__add_found_outcome(game_id, "spread", outcome)
                        # logger.info(f"DNB{period_suffix} {outcome}: EV {ev:.2f}% (odds: {odds}, stake: {stake:.2f})")
        
        logger.info(f"Found {len(available_markets)} markets with positive EV for {home_team} vs {away_team}")
        logger.info(f"{available_markets}")
        return available_markets

    def notify(self, shaped_data):
        """
        Main notification method for processing betting opportunities
        
        NEW: Now checks all available markets for each game instead of just the alerted market
        """
        try:
            logger.info(f"Processing alert: {shaped_data}")
            
            # Validate shaped data
            required_fields = ['game', 'category', 'match_type']
            if not all(field in shaped_data for field in required_fields):
                logger.info("Invalid shaped data format")
                return
            
            # Extract basic information
            home_team = shaped_data['game']['home']
            away_team = shaped_data['game']['away']
            pinnacle_start_time = shaped_data.get("starts")
            # line_type = shaped_data["category"]["type"]
            # outcome = shaped_data["category"]["meta"]["team"]
            # original_points = shaped_data["category"]["meta"].get("value")
            
            # Generate unique game identifier
            game_id = self.__generate_game_id(home_team, away_team, pinnacle_start_time)
            
            # Check if this game has already been processed
            if game_id in self.__processed_games:
                logger.info(f"Game {game_id} already processed, skipping")
                return
            
            logger.info(f"Processing new game: {home_team} vs {away_team}")
            
            # Step 1: Search for the event on Nairabet
            logger.info(f"Searching for event: {home_team} vs {away_team}")
            event_id = self.__search_event(home_team, away_team, pinnacle_start_time)
            if not event_id:
                logger.info("Event not found, cannot place bet")
                return
            
            # Step 2: Get event details
            logger.info(f"Getting event details for event: {event_id}")
            event_details = self.__get_event_details(event_id)
            if not event_details:
                logger.info("Could not get event details, cannot place bet")
                return
            
            # Step 3: Check all available markets for this game
            available_markets = self.__check_all_markets_for_game(event_details, shaped_data)
            
            if not available_markets:
                logger.info(f"No markets with positive EV found for {home_team} vs {away_team}")
                # Mark as processed even if no bets placed
                self.__processed_games.add(game_id)
                return
            
            # Step 4: Place bets for all markets that meet EV threshold
            bets_placed = 0
            for market_type, outcome, odds, points, ev, is_first_half, stake in available_markets:
                try:
                    period_suffix = " (1st Half)" if is_first_half else ""
                    logger.info(f"Placing bet: {market_type}{period_suffix} - {outcome} with odds {odds} (EV: {ev:.2f}%)")
                    
                    # Create modified shaped data for this specific market
                    modified_shaped_data = shaped_data.copy()
                    modified_shaped_data["category"]["type"] = market_type
                    modified_shaped_data["category"]["meta"]["team"] = outcome
                    if points is not None:
                        modified_shaped_data["category"]["meta"]["value"] = points
                    if is_first_half:
                        modified_shaped_data["periodNumber"] = "1"
                    
                    # Check for duplicate bet before placing
                    event_id = event_details.get("id", "unknown")
                    market_id = market_type
                    outcome_id = outcome.upper()
                    bet_signature = self.__generate_bet_signature(
                        event_id, market_id, outcome_id, odds, points, is_first_half
                    )
                    
                    if self.__is_bet_already_placed(bet_signature):
                        logger.info(f"Bet already placed, skipping: {bet_signature}")
                        continue
                    
                    # Place the bet
                    success = self.__place_bet(event_details, market_type, outcome, odds, modified_shaped_data, is_first_half, stake)
                    if success:
                        bets_placed += 1
                        logger.info(f"Successfully placed bet on {market_type}{period_suffix} - {outcome}")
                        
                        # Store bet details
                        bet_details = {
                            "event_id": event_id,
                            "market_id": market_id,
                            "outcome_id": outcome_id,
                            "odds": odds,
                            "handicap": points,
                            "line_type": market_type,
                            "outcome": outcome,
                            "is_first_half": is_first_half,
                            "stake": stake,
                            "timestamp": time.time(),
                            "home_team": home_team,
                            "away_team": away_team,
                            "ev": ev
                        }
                        self.__store_placed_bet(bet_signature, bet_details)
                    else:
                        logger.error(f"Failed to place bet on {market_type}{period_suffix} - {outcome}")
                        
                except Exception as e:
                    logger.error(f"Error placing bet on {market_type} - {outcome}: {e}")
                    continue
            
            # Mark game as processed
            self.__processed_games.add(game_id)
            logger.info(f"Game {game_id} processed. Placed {bets_placed} out of {len(available_markets)} available bets")
            
        except Exception as e:
            logger.error(f"Error in notify method: {e}")
            # Close browser on error
            self.cleanup()

    def __find_market_bet_code_with_points(self, event_details, line_type, points, outcome, is_first_half=False, sport_id=1, home_team=None, away_team=None):
        """
        Find the appropriate bet code in the Nairabet event details and return the adjusted points value
        
        Parameters:
        - event_details: The event details from Nairabet
        - line_type: The type of bet (spread, moneyline, total)
        - points: The points value for the bet
        - outcome: The outcome (home, away, draw, over, under)
        - is_first_half: Whether the bet is for the first half
        - sport_id: The sport ID (1 for soccer, 3 for basketball)
        
        Returns:
        - Tuple of (bet_code, odds, adjusted_points)
        """
        # logger.info(f"sport id {sport_id}")
        logger.info(f"Finding market for Game: {home_team} vs {away_team}: {line_type} - {outcome} - {points} - First Half: {is_first_half} - Sport: {'Basketball' if sport_id == 3 or sport_id == "3" else 'Soccer'}")
        
        # Handle new Nairabet API structure
        if "marketGroups" in event_details:
            # New API structure - extract markets from marketGroups
            all_markets = []
            first_half_markets = []
            
            for group in event_details.get("marketGroups", []):
                group_name = group.get("name", "").lower()
                group_markets = group.get("markets", [])
                
                # Check if this is a first half group
                if "1st half" in group_name or "first half" in group_name:
                    first_half_markets.extend(group_markets)
                else:
                    all_markets.extend(group_markets)
            
            # Use appropriate markets based on is_first_half parameter
            if is_first_half:
                markets = first_half_markets
                # logger.info(f"Using first half markets: {len(first_half_markets)} markets found")
            else:
                markets = all_markets
                # logger.info(f"Using full match markets: {len(all_markets)} markets found")
                
        elif "markets" in event_details:
            # Old API structure
            markets = event_details["markets"]
        else:
            logger.info("No markets found in event details")
            return None, None, None

        # Use different market names based on sport
        is_basketball = (sport_id == "3" or sport_id == 3)
        # logger.info(f"is basketball: {is_basketball}")
        
        # Determine the correct market descriptions based on is_first_half
        if is_first_half:
            # First half market descriptions - use actual market IDs from new API
            moneyline_market = "FH1X2"  # First Half 1X2
            total_market = "HTGOU_LS"   # Half time Goals - Under/Over
            spread_market = "HC"        # Handicap (if available for first half)
            dnb_market = "DNB"         # Draw No Bet (if available for first half)
        else:
            # Full match market descriptions - use actual market IDs from new API
            moneyline_market = "1x2"
            total_market = "TGOU"
            spread_market = "HC"
            dnb_market = "DNB"
        
        # logger.info(f"Looking for markets: moneyline='{moneyline_market}', total='{total_market}', spread='{spread_market}', dnb='{dnb_market}'")

        # Handle MONEYLINE bets (1X2 in Nairabet)
        if line_type.lower() == "money_line":
            # Find 1x2 market by ID
            for market in markets:
                market_id = market.get("id", "")
                
                # Check by market ID (new API)
                if market_id == moneyline_market:
                    # Map outcome to Nairabet format
                    outcome_map = {"home": "HOME", "away": "AWAY", "draw": "DRAW"}
                    if outcome.lower() not in outcome_map:
                        logger.info(f"Invalid outcome for moneyline: {outcome}")
                        continue
                        
                    target_outcome_id = outcome_map[outcome.lower()]
                    
                    # Find matching outcome
                    for market_outcome in market.get("outcomes", []):
                        if market_outcome.get("id") == target_outcome_id:
                            odds = market_outcome.get("value", market_outcome.get("odds", 0))
                            logger.info(f"Found moneyline market: {market.get('name', market.get('description', ''))} outcome {target_outcome_id} with odds {odds}")
                            return market_outcome["id"], float(odds), None
            
            logger.info(f"No matching moneyline market found for {outcome}")
            return None, None, None
            
        # Handle TOTAL bets (Over/Under in Nairabet)
        elif line_type.lower() == "total":
            # Map outcome to Nairabet format
            outcome_map = {"over": "OVER", "under": "UNDER"}
            if outcome.lower() not in outcome_map:
                logger.info(f"Invalid outcome for total: {outcome}")
                return None, None, None
                
            target_outcome_id = outcome_map[outcome.lower()]
            original_points = float(points)
            
            # Round to nearest 0.5 increment first (e.g., 1.25 -> 1.5, 1.3 -> 1.5, 1.7 -> 1.5)
            rounded_points = round(original_points * 2) / 2
            # logger.info(f"Original points: {original_points}, Rounded to nearest 0.5: {rounded_points}")
            
            # Generate alternate lines to search for (4 steps up and down with 0.5 increments)
            alternate_points = []
            
            # Add rounded target first
            alternate_points.append(rounded_points)
            
            # Add 4 steps upward (0.5, 1.0, 1.5, 2.0 higher)
            # FOR NOW REM OVE THIS SINCE WE ARE MANUALLY PASSING IT
            # for i in range(1, 5):
            #     alternate_points.append(rounded_points + (i * 0.5))
            
            # Add 4 steps downward (0.5, 1.0, 1.5, 2.0 lower), but not below 0
            # for i in range(1, 5):
            #     lower_point = rounded_points - (i * 0.5)
            #     if lower_point >= 0:  # Don't go below 0
            #         alternate_points.append(lower_point)
            
            # logger.info(f"Searching for total points in order: {alternate_points}")
            
            # Find Over/Under markets and look for the closest points from our alternate list
            best_match = None
            best_diff = float('inf')
            
            for market in markets:
                market_id = market.get("id", "")
                market_name = market.get("name", "")
                
                # Check by market ID first (new API)
                if market_id == total_market:
                    for market_outcome in market.get("outcomes", []):
                        outcome_desc = market_outcome.get("name", market_outcome.get("description", ""))
                        outcome_id = market_outcome.get("id")
                        
                        # Check if this outcome matches our target (over/under)
                        if outcome_id == target_outcome_id:
                            # Extract points from description (e.g., "Over 2.5" -> 2.5)
                            try:
                                if "over" in outcome_desc.lower():
                                    market_points = float(outcome_desc.lower().replace("over", "").strip())
                                elif "under" in outcome_desc.lower():
                                    market_points = float(outcome_desc.lower().replace("under", "").strip())
                                else:
                                    continue
                                
                                # Check if this market point is in our alternate points list
                                for alt_point in alternate_points:
                                    diff = abs(market_points - alt_point)
                                    if diff < 0.01:  # Match found (allowing for floating point precision)
                                        # Calculate priority based on distance from original target
                                        priority_diff = abs(market_points - original_points)
                                        
                                        if priority_diff < best_diff:
                                            best_diff = priority_diff
                                            odds = market_outcome.get("value", market_outcome.get("odds", 0))
                                            best_match = {
                                                "id": outcome_id,
                                                "odds": float(odds),
                                                "points": market_points,
                                                "description": outcome_desc
                                            }
                                        break  # Found match in alternate points, move to next outcome
                                    
                            except (ValueError, AttributeError):
                                continue
            
            if best_match:
                if best_match["points"] != original_points:
                    logger.info(f"Exact total {original_points} not found, using closest: {best_match['points']}")
                logger.info(f"Found total market: {best_match['description']} with odds {best_match['odds']}")
                return best_match["id"], best_match["odds"], best_match["points"]
            
            logger.info(f"No matching total market found for {points} {outcome} or alternate lines")
            return None, None, None
            
        # Handle SPREAD bets (Asian Handicap in Nairabet)
        elif line_type.lower() == "spread":
            original_points = float(points)
            
            # Check if handicap is 0 - if so, use DNB (Draw No Bet) market instead
            if abs(original_points) < 0.01:  # Using small threshold for floating point comparison
                logger.info(f"Handicap is 0, looking for DNB (Draw No Bet) market instead of Asian Handicap")
                
                # Map outcome to Nairabet format for DNB (based on actual API structure)
                outcome_map = {"home": "HOME", "away": "AWAY"}
                if outcome.lower() not in outcome_map:
                    logger.info(f"Invalid outcome for DNB: {outcome}")
                    return None, None, None
                    
                target_outcome_id = outcome_map[outcome.lower()]
                
                # Look for DNB market by ID
                for market in markets:
                    market_id = market.get("id", "")
                    market_name = market.get("name", "")
                    
                    # Check by market ID first (new API)
                    if market_id == dnb_market:
                        # Find matching outcome
                        for market_outcome in market.get("outcomes", []):
                            if market_outcome.get("id") == target_outcome_id:
                                odds = market_outcome.get("value", market_outcome.get("odds", 0))
                                logger.info(f"Found DNB market: {market.get('name', market.get('description', ''))} outcome {target_outcome_id} with odds {odds}")
                                return market_outcome["id"], float(odds), 0.0  # Return 0.0 as adjusted points
                
                logger.info(f"No matching DNB market found for {outcome}")
                return None, None, None
            
            # Original Asian Handicap logic for non-zero handicaps
            # Map outcome to Nairabet format for Asian Handicap
            outcome_map = {"home": "HOME", "away": "AWAY"}
            if outcome.lower() not in outcome_map:
                logger.info(f"Invalid outcome for handicap: {outcome}")
                return None, None, None
                
            target_outcome_id = outcome_map[outcome.lower()]
            
            # Round to nearest 0.5 increment first (e.g., -0.25 -> -0.5, +1.3 -> +1.5, -1.7 -> -1.5)
            rounded_points = round(original_points * 2) / 2
            # logger.info(f"Original handicap: {original_points}, Rounded to nearest 0.5: {rounded_points}")
            
            # Generate alternate handicap lines to search for (4 steps in each direction with 0.5 increments)
            alternate_points = []
            
            # Add rounded target first
            alternate_points.append(rounded_points)
            
            # Add 4 steps in positive direction (towards 0 if negative, away from 0 if positive)
            # if rounded_points < 0:
            #     # For negative handicaps, go towards 0 (less negative)
            #     for i in range(1, 5):
            #         new_point = rounded_points + (i * 0.5)
            #         if new_point <= 0:  # Don't cross zero for negative handicaps
            #             alternate_points.append(new_point)
            # else:
            #     # For positive handicaps, go away from 0 (more positive)
            #     for i in range(1, 5):
            #         alternate_points.append(rounded_points + (i * 0.5))
            
            # # Add 4 steps in negative direction (away from 0 if negative, towards 0 if positive)
            # if rounded_points < 0:
            #     # For negative handicaps, go away from 0 (more negative)
            #     for i in range(1, 5):
            #         alternate_points.append(rounded_points - (i * 0.5))
            # else:
            #     # For positive handicaps, go towards 0 (less positive)
            #     for i in range(1, 5):
            #         new_point = rounded_points - (i * 0.5)
            #         if new_point >= 0:  # Don't cross zero for positive handicaps
            #             alternate_points.append(new_point)
            
            # logger.info(f"Searching for handicap points in order: {alternate_points}")
            
            # Find Asian Handicap markets and look for the closest points from our alternate list
            best_match = None
            best_diff = float('inf')
            
            for market in markets:
                market_id = market.get("id", "")
                market_name = market.get("name", "")
                
                # Check by market ID first (new API)
                if market_id == spread_market:
                    # logger.info(f"Found spread market: {market.get('name', market.get('description', ''))}")
                    for market_outcome in market.get("outcomes", []):
                        outcome_desc = market_outcome.get("name", market_outcome.get("description", ""))
                        outcome_id = market_outcome.get("id")
                        
                        # Check if this outcome matches our target (home/away)
                        if outcome_id == target_outcome_id:
                            # logger.info(f"Found spread market outcome: {outcome_id}")
                            # Use handicap field directly from API response
                            try:
                                handicap_value = market_outcome.get("handicap")
                                if handicap_value is not None:
                                    market_points = float(handicap_value)
                                    # logger.info(f"Found handicap from API field: {market_points}")
                                else:
                                    # Fallback to parsing description if handicap field not available
                                    import re
                                    match = re.search(r'[(\[]([+-]?\d+\.?\d*)[)\]]', outcome_desc)
                                    if match:
                                        market_points = float(match.group(1))
                                        # logger.info(f"Found handicap from description: {market_points}")
                                    else:
                                        continue
                                
                                display_points = market_points
                                
                                # Check if this market point is in our alternate points list
                                for alt_point in alternate_points:
                                    diff = abs(display_points - alt_point)
                                    if diff < 0.01:  # Match found (allowing for floating point precision)
                                        # Calculate priority based on distance from original target
                                        priority_diff = abs(display_points - original_points)
                                        
                                        if priority_diff < best_diff:
                                            best_diff = priority_diff
                                            odds = market_outcome.get("value", market_outcome.get("odds", 0))
                                            best_match = {
                                                "id": outcome_id,
                                                "odds": float(odds),
                                                "points": display_points,
                                                "description": outcome_desc
                                            }
                                        break  # Found match in alternate points, move to next outcome
                                        
                            except (ValueError, AttributeError):
                                continue
            
            if best_match:
                if best_match["points"] != original_points:
                    logger.info(f"Exact handicap {original_points} not found, using closest: {best_match['points']}")
                logger.info(f"Found handicap market: {best_match['description']} with odds {best_match['odds']}")
                return best_match["id"], best_match["odds"], best_match["points"]
            
            logger.info(f"No matching handicap market found for {points} {outcome} or alternate lines")
            return None, None, None
        
        else:
            logger.info(f"Unsupported line type: {line_type}")
            return None, None, None
            
    def __extract_points_from_key(self, key):
        """Extract points value from a bet key"""
        try:
            # For totals: S_OU@2.5_O or S_OU1T@2.5_O
            # For spreads: S_1X2HND@2_1H or S_1X2HND1T@2_1H
            parts = key.split('@')
            if len(parts) < 2:
                return None
                
            # The points should be between '@' and '_'
            points_part = parts[1].split('_')[0]
            return float(points_part)
        except (ValueError, IndexError):
            return None

    def cleanup(self):
        """Close browser and clean up resources"""
        # Stop background popup handler
        self.__stop_popup_handler()
        
        if self.__browser_open and self.__browser_initialized:
            try:
                logger.info("Closing browser...")
                self.close_browser()
                self.__browser_open = False
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
        
        # Reset browser state so it can be reinitialized when needed
        self.__browser_initialized = False
        self.__browser_open = False
                
    def __del__(self):
        """Destructor to ensure browser is closed when object is garbage collected"""
        self.cleanup()

    def __place_bet(self, event_details, line_type, outcome, odds, modified_shaped_data, is_first_half=False, stake=None):
        """
        Place a bet on Nairabet
        
        Parameters:
        - event_details: Event details from Nairabet
        - line_type: Type of bet (money_line, total, spread)
        - outcome: Outcome to bet on
        - odds: The decimal odds for the bet
        - modified_shaped_data: The modified shaped data for the bet
        - is_first_half: Whether this is a first half bet
        
        Returns:
        - True if bet was placed/queued successfully
        """
        # Check if immediate bet placement is enabled
        immediate_placement = self.__config.get("immediate_bet_placement", True)
        
        if immediate_placement:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"Placing Nairabet bet immediately: {line_type}{period_suffix} - {outcome} with odds {odds}")
            
            # Create bet data
            bet_data = {
                "event_details": event_details,
                "market_type": line_type,
                "outcome": outcome,
                "odds": odds,
                "shaped_data": modified_shaped_data,
                "is_first_half": is_first_half,
                "stake": stake,  # Include pre-calculated stake
                "timestamp": time.time()
            }
            
            # Place bet immediately
            try:
                result = self.__place_bet_with_available_account(bet_data)
                if result:
                    logger.info("Bet placed successfully")
                else:
                    logger.warning("Bet placement failed")
                return result
            except Exception as e:
                logger.error(f"Error placing bet immediately: {e}")
                return False
        else:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"Queueing Nairabet bet: {line_type}{period_suffix} - {outcome} with odds {odds}")
            
            # Add bet to queue
            bet_data = {
                "event_details": event_details,
                "market_type": line_type,
                "outcome": outcome,
                "odds": odds,
                "shaped_data": modified_shaped_data,
                "is_first_half": is_first_half,
                "stake": stake,  # Include pre-calculated stake
                "timestamp": time.time()
            }
            
            self.__bet_queue.put(bet_data)
            return True  # Return True as the bet was queued successfully

    def __find_market_bet_code(self, event_details, line_type, points, outcome, is_first_half=False, sport_id=1, home_team=None, away_team=None):
        """
        DEPRECATED: Use __find_market_bet_code_with_points instead
        This method is kept for backward compatibility.
        
        Find the appropriate bet code in the Nairabet event details
        
        Parameters:
        - event_details: The event details from Nairabet
        - line_type: The type of bet (spread, moneyline, total)
        - points: The points value for the bet
        - outcome: The outcome (home, away, draw, over, under)
        - is_first_half: Whether the bet is for the first half
        - sport_id: The sport ID (1 for soccer, 3 for basketball)
        - home_team: Home team name (for logging)
        - away_team: Away team name (for logging)
        
        Returns:
        - Tuple of (bet_code, odds)
        """
        logger.warning("Using deprecated __find_market_bet_code method. Use __find_market_bet_code_with_points instead.")
        
        result = self.__find_market_bet_code_with_points(event_details, line_type, points, outcome, is_first_half, sport_id, home_team, away_team)
        if result:
            return result[0]  # Return only the bet_code
        return None

    def refresh_account_balances(self):
        """
        Refresh account balances for all accounts that have valid cookies
        
        Returns:
        - Dictionary with account usernames and their updated balances
        """
        balance_updates = {}
        
        for account in self.__accounts:
            if account.cookie_jar:
                try:
                    old_balance = account.balance
                    new_balance = self.__fetch_account_balance(account)
                    account.balance = new_balance
                    balance_updates[account.username] = {
                        "old_balance": old_balance,
                        "new_balance": new_balance,
                        "change": new_balance - old_balance
                    }
                    logger.info(f"Balance updated for {account.username}: {old_balance:.2f} -> {new_balance:.2f} (change: {new_balance - old_balance:+.2f})")
                except Exception as e:
                    logger.error(f"Failed to refresh balance for {account.username}: {e}")
                    balance_updates[account.username] = {
                        "error": str(e)
                    }
            else:
                logger.info(f"No valid cookies for {account.username}, skipping balance refresh")
                
        return balance_updates

    def search_event(self, home_team, away_team, pinnacle_start_time=None):
        """
        Public method to search for an event on Nairabet
        
        Parameters:
        - home_team: Home team name
        - away_team: Away team name
        - pinnacle_start_time: Start time from Pinnacle in milliseconds (unix timestamp)
        
        Returns:
        - event ID if found, None otherwise
        """
        return self.__search_event(home_team, away_team, pinnacle_start_time)
    
    def get_event_details(self, event_id):
        """
        Public method to get detailed information about an event from Nairabet
        
        Parameters:
        - event_id: The event ID to get details for
        
        Returns:
        - Event details dictionary or None if not found
        """
        return self.__get_event_details(event_id)
    
    def generate_nairabet_bet_url(self, event_details):
        """
        Public method to generate Nairabet betting URL based on event details
        
        Parameters:
        - event_details: Event details dictionary
        
        Returns:
        - Betting URL string or None if generation fails
        """
        return self.__generate_nairabet_bet_url(event_details)
    
    def find_market_bet_code_with_points(self, event_details, line_type, points, outcome, is_first_half=False, sport_id=1, home_team=None, away_team=None):
        """
        Public method to find the appropriate bet code in the Nairabet event details
        
        Parameters:
        - event_details: The event details from Nairabet
        - line_type: The type of bet (spread, moneyline, total)
        - points: The points value for the bet
        - outcome: The outcome (home, away, draw, over, under)
        - is_first_half: Whether the bet is for the first half
        - sport_id: The sport ID (1 for soccer, 3 for basketball)
        - home_team: Home team name (for logging)
        - away_team: Away team name (for logging)
        
        Returns:
        - Tuple of (bet_code, odds, adjusted_points)
        """
        return self.__find_market_bet_code_with_points(event_details, line_type, points, outcome, is_first_half, sport_id, home_team, away_team)

    def test_direct_bet_placement(self):
        """
        Test function to directly test bet placement with real event data
        This bypasses the normal alert flow and tests the CSS selector system
        
        NEW: Now supports DNB (Draw No Bet) market when handicap is 0
        """
        logger.info("=== Testing Direct Bet Placement ===")
        
        # Example test data - modify these values as needed
        test_data = {
            "game": {
                "home": "Chelsea",  # Changed to more common teams
                "away": "Arsenal"
            },
            "category": {
            "type": "spread",  # Changed from "moneyline" to "spread" for handicap
            "meta": {
                    "team": "home",  # for handicap: "home" or "away"
                    "value": "-0.5"  # handicap value (e.g., "-0.5", "+1.5", "-1.0")
                }
            },
            "match_type": "test",
            "sportId": 1,  # 1 for soccer, 3 for basketball
            "starts": None  # can add start time in milliseconds if needed
        }
        
        logger.info(f"Testing DNB market with handicap 0: {test_data['category']['meta']['value']}")
        
        try:
            # Step 1: Search for the event
            logger.info(f"\n1. Searching for event: {test_data['game']['home']} vs {test_data['game']['away']}")
            event_id = self.search_event(
                test_data["game"]["home"], 
                test_data["game"]["away"], 
                test_data.get("starts")
            )
            
            if not event_id:
                logger.info("❌ Event not found")
                return False
            
            logger.info(f"✅ Found event ID: {event_id}")
            
            # Step 2: Get event details
            logger.info(f"\n2. Getting event details...")
            event_details = self.get_event_details(event_id)
            
            if not event_details:
                print("❌ Could not get event details")
                return False
                
            print(f"✅ Got event details for: {event_details.get('homeTeam')} vs {event_details.get('awayTeam')}")
            
            # Step 3: Generate betting URL
            print(f"\n3. Generating betting URL...")
            bet_url = self.generate_nairabet_bet_url(event_details)
            
            if not bet_url:
                print("❌ Could not generate betting URL")
                return False
                
            print(f"✅ Generated URL: {bet_url}")
            
            # Step 4: Find market (this tests the new CSS selector system)
            print(f"\n4. Testing market finder...")
            line_type = test_data["category"]["type"]
            outcome = test_data["category"]["meta"]["team"]
            points = test_data["category"]["meta"].get("value")
            sport_id = test_data.get("sportId", 1)
            
            bet_code, odds, adjusted_points = self.find_market_bet_code_with_points(
                event_details,
                line_type,
                points,
                outcome,
                is_first_half=False,
                sport_id=sport_id,
                home_team=test_data["game"]["home"],
                away_team=test_data["game"]["away"]
            )
            
            if not bet_code or not odds:
                print("❌ Could not find market")
                return False
                
            print(f"✅ Found market: {bet_code} with odds {odds}")
            if adjusted_points is not None:
                print(f"   Adjusted points: {adjusted_points}")
            
            # Step 5: Test CSS selector system (without actually placing bet)
            print(f"\n5. Testing CSS selector system...")
            
            # Navigate to the betting page first
            self._initialize_browser_if_needed(test_data["accounts"][0])
            print(f"Navigating to: {bet_url}")
            self.open_url(bet_url)
            time.sleep(5)
            
            # Test the new selector system
            market_element = self.__get_market_selector(line_type, outcome, points, is_first_half=False)
            
            if market_element:
                print("✅ CSS selector system found market element!")
                
                # Try to get odds from the element to verify it's working
                try:
                    odds_element = market_element.find_element(By.CSS_SELECTOR, ".odds")
                    odds_text = odds_element.text.strip()
                    print(f"   Element odds: {odds_text}")
                    
                    # Test scrolling and element positioning (but don't click)
                    print("   Testing element positioning...")
                    
                    # Use the same improved scrolling logic
                    self.driver.execute_script("""
                        var element = arguments[0];
                        var elementRect = element.getBoundingClientRect();
                        var absoluteElementTop = elementRect.top + window.pageYOffset;
                        var middle = absoluteElementTop - (window.innerHeight / 2) + 100;
                        window.scrollTo(0, middle);
                    """, market_element)
                    # time.sleep(2)
                    
                    # Check if element is now in viewport and clickable
                    element_rect = self.driver.execute_script("""
                        var element = arguments[0];
                        var rect = element.getBoundingClientRect();
                        return {
                            top: rect.top,
                            bottom: rect.bottom,
                            left: rect.left,
                            right: rect.right,
                            visible: rect.top >= 0 && rect.bottom <= window.innerHeight
                        };
                    """, market_element)
                    
                    print(f"   Element position: top={element_rect['top']:.1f}, visible={element_rect['visible']}")
                    
                    if element_rect['visible'] and element_rect['top'] > 50:  # Ensure it's not covered by header
                        print("✅ Element is properly positioned and clickable!")
                    else:
                        print("⚠️  Element positioning may have issues")
                    
                    print("✅ Successfully tested CSS selector system!")
                    print("⚠️  Test completed without placing actual bet (safety measure)")
                    
                except Exception as e:
                    print(f"⚠️  Found element but couldn't extract odds: {e}")
                    
            else:
                print("❌ CSS selector system could not find market element")
                return False
            
            print(f"\n=== Test Summary ===")
            print(f"Event: {test_data['game']['home']} vs {test_data['game']['away']}")
            print(f"Market: {line_type} - {outcome}")
            if points:
                print(f"Points: {points}")
            print(f"Status: CSS selectors working ✅")
            
            return True
            
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Clean up
            self.cleanup()

    def get_bet_placement_mode(self):
        """
        Get the current bet placement mode
        
        Returns:
        - 'immediate' if bets are placed immediately
        - 'queued' if bets are queued for later placement
        """
        immediate_placement = self.__config.get("immediate_bet_placement", True)
        return "immediate" if immediate_placement else "queued"
    
    def set_bet_placement_mode(self, immediate=True):
        """
        Set the bet placement mode
        
        Parameters:
        - immediate: True for immediate placement, False for queued placement
        """
        self.__config["immediate_bet_placement"] = immediate
        mode = "immediate" if immediate else "queued"
        logger.info(f"Bet placement mode changed to: {mode}")
        
        # Save config to file if it exists
        try:
            with open("config.json", "w") as f:
                json.dump(self.__config, f, indent=4)
            logger.info("Configuration saved to config.json")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
    
    def get_queue_size(self):
        """
        Get the current size of the bet queue
        
        Returns:
        - Number of bets in the queue
        """
        return self.__bet_queue.qsize()
    
    def clear_bet_queue(self):
        """
        Clear all bets from the queue
        
        Returns:
        - Number of bets that were cleared
        """
        cleared_count = 0
        while not self.__bet_queue.empty():
            try:
                self.__bet_queue.get_nowait()
                self.__bet_queue.task_done()
                cleared_count += 1
            except queue.Empty:
                break
        
        logger.info(f"Cleared {cleared_count} bets from queue")
        return cleared_count

    def clear_processed_games(self):
        """
        Clear the set of processed games (useful for testing or resetting state)
        """
        self.__processed_games.clear()
        logger.info("Cleared processed games tracking")
    
    def get_processed_games_count(self):
        """
        Get the number of processed games
        """
        return len(self.__processed_games)

    def __restart_browser(self, account):
        """
        Restart browser by cleaning up and reinitializing
        """
        try:
            logger.info("Restarting browser...")
            self._cleanup_browser_for_proxy_switch()
            self._initialize_browser_if_needed(account)
            logger.info("Browser restarted successfully")
        except Exception as e:
            logger.error(f"Error restarting browser: {e}")
            raise

    def __calculate_stake(self, bet_odds, shaped_data, bankroll):
        """
        Calculate the stake amount based on Kelly criterion
        
        Parameters:
        - bet_odds: The decimal odds offered by Nairabet
        - shaped_data: The data with prices and outcome information
        
        Returns:
        - Recommended stake amount (rounded to human-like values)
        """
        # Get the stored decimal prices and outcome key
        decimal_prices = shaped_data.get("_decimal_prices", {})
        outcome_key = shaped_data.get("_outcome_key", "")
        
        if not decimal_prices or not outcome_key:
            logger.info("Missing required data for stake calculation")
            return self.__round_stake_humanlike(10)  # Default stake if calculation not possible
        
        # Extract values into a list for power method
        odds_values = list(decimal_prices.values())
        if not odds_values:
            return self.__round_stake_humanlike(10)  # Default stake
        
        # Calculate fair probabilities using power method
        fair_probs = self.__power_method_devig(odds_values)
        
        # Map the probabilities back to their outcomes
        outcome_probs = {}
        for i, (outcome, _) in enumerate(decimal_prices.items()):
            if i < len(fair_probs):
                outcome_probs[outcome] = fair_probs[i]
        
        # Get the probability for our specific outcome
        if outcome_key not in outcome_probs:
            logger.info(f"Outcome {outcome_key} not found in probabilities")
            return self.__round_stake_humanlike(10)  # Default stake
            
        outcome_prob = outcome_probs[outcome_key]
        
        
        # Calculate Kelly stake
        full_kelly = self.__kelly_stake(outcome_prob, bet_odds, bankroll)
        
        # Use 30% of Kelly as a more conservative approach
        fractional_kelly = full_kelly * 0.3
        
        # Get odds-based stake limits
        min_stake, max_stake = self.__get_stake_limits_for_odds(bet_odds)
        
        stake = max(min_stake, min(fractional_kelly, max_stake))
        
        # Round to human-like amounts
        rounded_stake = self.__round_stake_humanlike(stake)
        
        logger.info(f"Probability: {outcome_prob:.4f}, Full Kelly: {full_kelly:.2f}, "
              f"Fractional Kelly (30%): {fractional_kelly:.2f}, Calculated Stake: {stake:.2f}, "
              f"Rounded Stake: {rounded_stake:.2f}")
        
        return rounded_stake
    
    def __calculate_stake_for_market(self, bet_odds, shaped_data, bankroll):
        """
        Calculate the stake amount for a specific market based on pre-calculated EV data
        
        Parameters:
        - bet_odds: The decimal odds offered by Nairabet
        - shaped_data: The data with pre-calculated prices and outcome information
        
        Returns:
        - Recommended stake amount (rounded to human-like values)
        """
        # Get the stored decimal prices and outcome key from EV calculation
        decimal_prices = shaped_data.get("_decimal_prices", {})
        outcome_key = shaped_data.get("_outcome_key", "")
        
        if not decimal_prices or not outcome_key:
            logger.info("Missing required data for stake calculation")
            return self.__round_stake_humanlike(10)  # Default stake if calculation not possible
        
        # Extract values into a list for power method
        odds_values = list(decimal_prices.values())
        if not odds_values:
            return self.__round_stake_humanlike(10)  # Default stake
        
        # Calculate fair probabilities using power method
        fair_probs = self.__power_method_devig(odds_values)
        
        # Map the probabilities back to their outcomes
        outcome_probs = {}
        for i, (outcome, _) in enumerate(decimal_prices.items()):
            if i < len(fair_probs):
                outcome_probs[outcome] = fair_probs[i]
        
        # Get the probability for our specific outcome
        if outcome_key not in outcome_probs:
            logger.info(f"Outcome {outcome_key} not found in probabilities")
            return self.__round_stake_humanlike(10)  # Default stake
            
        outcome_prob = outcome_probs[outcome_key]
        
        # Calculate Kelly stake
        full_kelly = self.__kelly_stake(outcome_prob, bet_odds, bankroll)  # Use default bankroll of 1000
        
        # Use 30% of Kelly as a more conservative approach
        fractional_kelly = full_kelly * 0.3
        
        # Get odds-based stake limits
        min_stake, max_stake = self.__get_stake_limits_for_odds(bet_odds)
        
        stake = max(min_stake, min(fractional_kelly, max_stake))
        
        # Round to human-like amounts
        rounded_stake = self.__round_stake_humanlike(stake)
        
        logger.info(f"Probability: {outcome_prob:.4f}, Full Kelly: {full_kelly:.2f}, "
              f"Fractional Kelly (30%): {fractional_kelly:.2f}, Calculated Stake: {stake:.2f}, "
              f"Rounded Stake: {rounded_stake:.2f}")
        
        return rounded_stake

    def __calculate_stake(self, bet_odds, shaped_data, bankroll):
        """
        Calculate the stake amount based on Kelly criterion
        
        Parameters:
        - bet_odds: The decimal odds offered by Nairabet
        - shaped_data: The data with prices and outcome information
        
        Returns:
        - Recommended stake amount (rounded to human-like values)
        """
        # Get the stored decimal prices and outcome key
        decimal_prices = shaped_data.get("_decimal_prices", {})
        outcome_key = shaped_data.get("_outcome_key", "")
        
        if not decimal_prices or not outcome_key:
            logger.info("Missing required data for stake calculation")
            return self.__round_stake_humanlike(10)  # Default stake if calculation not possible
        
        # Extract values into a list for power method
        odds_values = list(decimal_prices.values())
        if not odds_values:
            return self.__round_stake_humanlike(10)  # Default stake
        
        # Calculate fair probabilities using power method
        fair_probs = self.__power_method_devig(odds_values)
        
        # Map the probabilities back to their outcomes
        outcome_probs = {}
        for i, (outcome, _) in enumerate(decimal_prices.items()):
            if i < len(fair_probs):
                outcome_probs[outcome] = fair_probs[i]
        
        # Get the probability for our specific outcome
        if outcome_key not in outcome_probs:
            logger.info(f"Outcome {outcome_key} not found in probabilities")
            return self.__round_stake_humanlike(10)  # Default stake
            
        outcome_prob = outcome_probs[outcome_key]
        
        
        # Calculate Kelly stake
        full_kelly = self.__kelly_stake(outcome_prob, bet_odds, bankroll)
        
        # Use 30% of Kelly as a more conservative approach
        fractional_kelly = full_kelly * 0.3
        
        # Get odds-based stake limits
        min_stake, max_stake = self.__get_stake_limits_for_odds(bet_odds)
        
        stake = max(min_stake, min(fractional_kelly, max_stake))
        
        # Round to human-like amounts
        rounded_stake = self.__round_stake_humanlike(stake)
        
        logger.info(f"Probability: {outcome_prob:.4f}, Full Kelly: {full_kelly:.2f}, "
              f"Fractional Kelly (30%): {fractional_kelly:.2f}, Calculated Stake: {stake:.2f}, "
              f"Rounded Stake: {rounded_stake:.2f}")
        
        return rounded_stake

if __name__ == "__main__":
    """Main Application
    
    NEW FEATURE: Now supports DNB (Draw No Bet) market when handicap is 0
    - When handicap points is 0, the system will look for DNB market instead of Asian Handicap
    - DNB market has only 2 outcomes: Home and Away (no Draw)
    - This provides better odds for matches where a draw is unlikely
    """
    bet_engine = BetEngine(
        headless=os.getenv("ENVIRONMENT") == "production",
        config_file="config.json"
    )
    
    # Run the test function instead of the old test
    bet_engine.test_direct_bet_placement()