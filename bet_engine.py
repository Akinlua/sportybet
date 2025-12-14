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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode, quote
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
logger = logging.getLogger('sporty_betting')
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

class BetAccount:
    """
    Represents a single Sportybet account with its own login credentials and cookie jar
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
    Handles the bet placement process on sportybet, including:
    - Searching for matches
    - Finding the right market
    - Calculating EV
    - Placing bets with positive EV using selenium
    """
    
    def __init__(self, headless=os.getenv("ENVIRONMENT")=="production", 
                 bet_host=os.getenv("SPORTY_HOST", "https://www.sportybet.com"), 
                 bet_api_host=os.getenv("SPORTY_API_HOST", "https://www.sportybet.com/api/ng"),
                 min_ev=float(os.getenv("MIN_EV", "0")),
                 config_file="config.json",
                 skip_initial_login=False):
        """
        Initialize BetEngine
        
        Parameters:
        - headless: Whether to run browser in headless mode
        - bet_host: sportybet betting website host
        - bet_api_host: sportybet API host for searching events
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
        
        # Thread-local drivers per worker
        self.__thread_drivers = {}
        
        # Track processed games to avoid reprocessing
        self.__processed_games = set()
        
        # Track placed bets to avoid duplicates (max 1000)
        self.__placed_bets = {}  # Key: bet_signature, Value: bet_details
        self.__used_virtual_event_ids = set()
        
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
    
    # Thread-local driver property to avoid cross-thread overrides
    @property
    def driver(self):
        tid = threading.get_ident()
        return self.__thread_drivers.get(tid)
    
    @driver.setter
    def driver(self, value):
        try:
            self.__thread_drivers[threading.get_ident()] = value
        except Exception:
            pass
    
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
            
            profile_base = os.path.join(os.getcwd(), "profiles")
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
            profile_path = os.path.join(profile_base, safe_name)
            super().__init__(self.__headless, proxy, profile_path=profile_path)
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
                    try:
                        ap_yes = self.driver.find_element(By.CSS_SELECTOR, "[data-op='account-protection-yes-its-me'], [data-cms-key='yes_it_is_me'][data-cms-page='account_protection']")
                        ap_yes.click()
                        logger.info("🖱️ Clicked Account Protection 'Yes, it's me'")
                        await asyncio.sleep(0.5)
                    except:
                        pass
                    # Handle Accept/Cookie popups
                    # try:
                    #     accept_button = self.driver.find_element(By.XPATH, "//button[contains(text(),'Accept')]")
                    #     accept_button.click()
                    #     logger.info("🖱️ Clicked Accept button on popup")
                    #     await asyncio.sleep(0.5)
                    # except:
                    #     pass
                    
                    # Handle Kumulos confirmation popups
                    # try:
                    #     confirm_button = self.driver.find_element(By.CSS_SELECTOR, "button.kumulos-action-button.kumulos-action-button-cancel")
                    #     confirm_button.click()
                    #     logger.info("🖱️ Clicked Kumulos confirm button")
                    #     await asyncio.sleep(0.5)
                    # except:
                    #     try:
                    #         cancel_button = self.driver.find_element(By.CSS_SELECTOR, ".kumulos-action-button-cancel")
                    #         cancel_button.click()
                    #         logger.info("🖱️ Clicked Kumulos cancel button")
                    #         await asyncio.sleep(0.5)
                    #     except:
                    #         pass
                    
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
        env_username = os.getenv("SPORTY_USERNAME")
        env_password = os.getenv("SPORTY_PASSWORD")
        
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
            raise ValueError("No betting accounts configured. Please set sportybet_USERNAME and sportybet_PASSWORD environment variables or configure accounts in config.json")
            
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
        workers = int(self.__config.get("max_total_concurrent_bets", 20))
        self.__worker_threads = []
        for _ in range(max(1, workers)):
            t = threading.Thread(target=self.__process_bet_queue, daemon=True)
            t.start()
            self.__worker_threads.append(t)
        
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
        """Log in to sportybet website with the first account (for search functionality)"""
        if self.__accounts:
            self.__do_login_for_account(self.__accounts[0])
        else:
            raise ValueError("No betting accounts configured")
            
    def __check_ip_address(self, using_proxy=False, proxy_url=None, account=None ):
        """Check and log the current IP address being used"""
        try:
            # Use a service that returns the client's IP address
            ip_check_url = "https://ip.decodo.com/json"
            response = requests.get(ip_check_url, proxies=proxy_url)
            if response.status_code == 200:
                ip_data = response.json()
                if "ip" in ip_data["proxy"]:
                    ip_address = ip_data["proxy"]["ip"]
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
        Fetch account balance from sportybet API after login
        
        Parameters:
        - account: BetAccount instance with valid cookies
        
        Returns:
        - Balance amount as float, or 0 if failed
        """
        try:
            if not account.cookie_jar:
                logger.warning(f"No cookies available for account {account.username}, cannot fetch balance")
                return 0
                
            ts = str(int(time.time() * 1000))
            balance_url = f"https://www.sportybet.com/api/ng/pocket/v1/finAccs/finAcc/userBal/NGN?_t={ts}"
            
            # Convert cookie jar to requests format
            cookies = {}
            if isinstance(account.cookie_jar, dict):
                cookies = account.cookie_jar
            elif isinstance(account.cookie_jar, list):
                cookies = {cookie["name"]: cookie["value"] for cookie in account.cookie_jar}
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.sportybet.com/ng/",
                "Origin": "https://www.sportybet.com"
            }
            
            response = requests.get(balance_url, headers=headers, cookies=cookies)
            
            if response.status_code == 200:
                balance_data = response.json()
                payload = balance_data.get("data", balance_data) if isinstance(balance_data, dict) else {}
                if isinstance(payload, dict):
                    biz_code = None
                    try:
                        biz_code = float(balance_data.get("bizCode")) if isinstance(balance_data, dict) else None
                    except Exception:
                        biz_code = None
                    if "avlBal" in payload and biz_code and biz_code > 0:
                        try:
                            amt = float(payload.get("avlBal")) / biz_code
                            logger.info(f"Account {account.username} balance (avlBal/bizCode): {amt:.2f}")
                            return amt
                        except Exception:
                            pass
                    for key in ("balance", "userBal", "availableBalance", "withdrawable", "total"):
                        if key in payload and isinstance(payload.get(key), (int, float, str)):
                            try:
                                amt = float(payload.get(key))
                                logger.info(f"Account {account.username} balance ({key}): {amt:.2f}")
                                return amt
                            except Exception:
                                continue
                logger.warning(f"Invalid balance response for account {account.username}: {balance_data}")
                return 0
            else:
                logger.error(f"Failed to fetch balance for account {account.username}: HTTP {response.status_code}")
                return 0
                
        except Exception as e:
            logger.error(f"Error fetching balance for account {account.username}: {e}")
            return 0

    def __do_login_for_account(self, account, _retry=False):
        """Log in to sportybet website with a specific account using selenium with retry mechanism"""
        max_retries = 2
        current_attempt = 2 if _retry else 1
        
        logger.info(f"🔄 Login attempt {current_attempt}/{max_retries} for account: {account.username}")
        
        if not account.username or not account.password:
            raise ValueError("sportybet username or password not found for account")
        
        try:
            if not hasattr(self, 'driver') or not self.driver:
                profile_base = os.path.join(os.getcwd(), "profiles")
                safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                profile_path = os.path.join(profile_base, safe_name)
                opener = WebsiteOpener(headless=self.__headless, proxy=account.proxy, config_file="config.json", profile_path=profile_path)
                self.driver = opener.driver
            
            # Fast-path: try persisted cookies to verify session via balance before hitting login page
            try:
                return True
                # profile_base = os.path.join(os.getcwd(), "profiles")
                # safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                # cookie_file = os.path.join(profile_base, safe_name, "cookies.json")
                # if os.path.exists(cookie_file):
                #     with open(cookie_file, "r") as f:
                #         stored = json.load(f)
                #     if stored:
                #         account.set_cookie_jar(stored)
                #         bal = self.__fetch_account_balance(account)
                #         if bal and bal > 0:
                #             logger.info(f"Session valid via persisted cookies for {account.username}; skipping login")
                #             return True
            except Exception:
                pass
            
            # Initialize CAPTCHA solver
            # captcha_config = self.__config.get("captcha", {})
            # if captcha_config.get("enabled", True):
            #     captcha_solver = CaptchaSolver(api_key=captcha_config.get("api_key"))
            #     captcha_solver.max_retries = captcha_config.get("max_retries", 3)
            # else:
            #     print("⚠️  CAPTCHA solving is disabled in configuration")
            #     captcha_solver = None

            # # Navigate to sportybet login page
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

            # Check if already logged in first by presence of header 'Account' button
            try:
                WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".m-user-center.m-list"))
                )
                logger.info(f"Already logged in for account: {account.username}")
                # Get cookies from selenium
                selenium_cookies = self.driver.get_cookies()
                account.set_cookie_jar(selenium_cookies)
                
                try:
                    profile_base = os.path.join(os.getcwd(), "profiles")
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                    os.makedirs(os.path.join(profile_base, safe_name), exist_ok=True)
                    cookie_file = os.path.join(profile_base, safe_name, "cookies.json")
                    to_save = {c["name"]: c["value"] for c in selenium_cookies if isinstance(c, dict) and "name" in c and "value" in c}
                    with open(cookie_file, "w") as f:
                        json.dump(to_save, f)
                    logger.info(f"Persisted cookies for {account.username} to {cookie_file}")
                except Exception:
                    pass
                
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
            
            # Navigate to sportybet login page
            # login_url = f"{self.__bet_host}"
            # try:
            #     self.driver.get(login_url)
            #     logger.info(f"Navigated to login page: {login_url}")
            # except Exception as get_err:
            #     msg = str(get_err).lower()
            #     if ("invalid session id" in msg or "disconnected" in msg):
            #         logger.error("Invalid Selenium session detected. Restarting browser and retrying login navigation...")
            #         self.__restart_browser(account)
            #         self.driver.get(login_url)
            #         logger.info(f"Navigated to login page after restart: {login_url}")
            #     else:
            #         raise
            
            # Open login modal from header
            # try:
            #     header_login_btn = WebDriverWait(self.driver, 10).until(
            #         EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'header-button')][.//span[contains(@class,'header-button__label') and normalize-space()='Login']]"))
            #     )
            #     header_login_btn.click()
            #     logger.info("Opened login modal")
                
            #     # Handle notification popup that may appear after clicking login
            #     # try:
            #     #     # Wait for notification popup and click "Maybe Later"
            #     #     maybe_later_btn = WebDriverWait(self.driver, 5).until(
            #     #         EC.element_to_be_clickable((By.CSS_SELECTOR, "button.kumulos-action-button.kumulos-action-button-cancel"))
            #     #     )
            #     #     maybe_later_btn.click()
            #     #     logger.info("Clicked 'Maybe Later' on notification popup")
            #     #     time.sleep(1)  # Brief wait for popup to close
            #     # except TimeoutException:
            #     #     logger.info("No notification popup found, continuing with login")
            #     # except Exception as e:
            #     #     logger.warning(f"Could not handle notification popup: {e}")
                    
            # except Exception as e:
            #     logger.error(f"Could not open login modal: {e}")
            
            # Find phone input
            try:
                self.driver.execute_script("document.querySelectorAll('.af-toast,.m-dialog,.m-modal,.m-balance-wrapper,.m-bablance-wrapper').forEach(el=>{try{el.style.pointerEvents='none'}catch(e){}});")
            except Exception:
                pass
            phone_input = WebDriverWait(self.driver, 60).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='phone']"))
            )
            try:
                phone_input.clear()
                phone_input.send_keys(account.username)
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input')); arguments[0].dispatchEvent(new Event('change'));", phone_input, account.username)
                except Exception:
                    pass
            logger.info(f"📱 Entered username/phone/email: {account.username}")
            
            # Find password input
            password_input = WebDriverWait(self.driver, 60).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='psd']"))
            )
            try:
                password_input.clear()
                password_input.send_keys(account.password)
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input')); arguments[0].dispatchEvent(new Event('change'));", password_input, account.password)
                except Exception:
                    pass
            logger.info(f"🔑 Entered password")
            
            # Find and click login button
            login_button = WebDriverWait(self.driver, 60).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[name='logIn'].m-btn.m-btn-login"))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", login_button)
                login_button.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", login_button)
                except Exception:
                    pass
            logger.info(f"🚀 Clicked login button")
            # time.sleep(10)
            
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
                WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".m-user-center.m-list"))
                )
                logger.info(f"Login successful for account: {account.username}")
                
                # Get cookies from selenium
                selenium_cookies = self.driver.get_cookies()
                account.set_cookie_jar(selenium_cookies)
                
                try:
                    profile_base = os.path.join(os.getcwd(), "profiles")
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                    os.makedirs(os.path.join(profile_base, safe_name), exist_ok=True)
                    cookie_file = os.path.join(profile_base, safe_name, "cookies.json")
                    to_save = {c["name"]: c["value"] for c in selenium_cookies if isinstance(c, dict) and "name" in c and "value" in c}
                    with open(cookie_file, "w") as f:
                        json.dump(to_save, f)
                    logger.info(f"Persisted cookies for {account.username} to {cookie_file}")
                except Exception:
                    pass
                
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
                logger.info(f"Login error screenshot saved to username-{account.username} {screenshot_path}")
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

    def __normalize_team(self, name):
        s = str(name or "").lower()
        s = re.sub(r"\(.*?\)", "", s)
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"\b(fc|bc|cf|ac)\b\s*$", "", s).strip()
        tokens = [t for t in s.split() if t not in {"club","team","sport","sports","fc","cf","sc","ac","bc","fk","united","city","town","rovers","athletic","sporting","real","atletico","inter","milan","juventus","football","soccer","basketball"}]
        return " ".join(tokens)

    def __extract_longest_tokens(self, name):
        s = self.__normalize_team(name)
        arr = [w for w in s.split() if len(w) >= 3]
        arr.sort(key=lambda x: len(x), reverse=True)
        seen = []
        for w in arr:
            if w not in seen:
                seen.append(w)
            if len(seen) >= 3:
                break
        return seen

    def __lev_similarity(self, a, b):
        a = self.__normalize_team(a)
        b = self.__normalize_team(b)
        if not a or not b:
            return 0.0
        la, lb = len(a), len(b)
        dp = list(range(lb + 1))
        for i in range(1, la + 1):
            prev = dp[0]
            dp[0] = i
            ai = a[i - 1]
            for j in range(1, lb + 1):
                tmp = dp[j]
                cost = 0 if ai == b[j - 1] else 1
                dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
                prev = tmp
        dist = dp[lb]
        sim = (1 - dist / max(la, lb)) * 100
        return sim

    def __word_match(self, token, text):
        token = str(token or "").lower().strip()
        text = self.__normalize_team(text)
        if not token or not text:
            return False
        if len(token) <= 3:
            return re.search(r"\b" + re.escape(token) + r"\b", text) is not None
        return token in text

    def __similar(self, a, b):
        ta = set(self.__normalize_team(a).split())
        tb = set(self.__normalize_team(b).split())
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union

    def __search_event(self, home_team, away_team, pinnacle_start_time=None):
        """
        Search for an event on sportybet using team names and match start time
        
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
        
        q_home = self.__normalize_team(home_team)
        q_away = self.__normalize_team(away_team)
        l_home = self.__extract_longest_tokens(home_team)
        l_away = self.__extract_longest_tokens(away_team)
        search_strategies = []
        for i in range(min(3, len(l_home))):
            for j in range(min(3, len(l_away))):
                search_strategies.append(f"{l_home[i]} {l_away[j]}")
        for t in l_home[:3] + l_away[:3]:
            if t not in search_strategies:
                search_strategies.append(t)
        
        # Store potential matches with scores for later evaluation
        potential_matches = []

        try:
            from urllib3.util.retry import Retry
            from requests.adapters import HTTPAdapter
            session = requests.Session()
            retry = Retry(total=3, connect=3, read=3, backoff_factor=0.5, status_forcelist=[502, 503, 504], allowed_methods=["GET"]) 
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        except Exception:
            session = requests
        
        # List of terms that indicate the wrong team variant
        # variant_indicators = ["ladies", "women", "u21", "u-21", "u23", "u-23", "youth", "junior", "b team"]
        variant_indicators = []

        
        for search_term in search_strategies:
            # logger.info(f"Trying search term: {search_term}")
            
            try:
                search_url = f"{self.__bet_api_host}/factsCenter/event/firstSearch"
                params = {
                    'keyword': search_term,
                    'offset': '0',
                    'pageSize': '20',
                    'withOneUpMarket': 'true',
                    'withTwoUpMarket': 'true',
                    '_t': str(int(time.time()*1000))
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Referer": self.__bet_host,
                    "Connection": "close",
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
                prox = proxies
                if isinstance(prox, dict) and "https" not in prox and "http" in prox:
                    prox = dict(prox)
                    prox["https"] = prox.get("http")
                try:
                    response = session.get(search_url, params=params, headers=headers, proxies=prox, timeout=15)
                except requests.exceptions.SSLError:
                    try:
                        response = session.get(search_url, params=params, headers=headers, proxies=None, timeout=15)
                    except Exception as e:
                        logger.error(f"Search request error: {e}")
                        continue
                
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
                        payload = search_results["data"]
                        candidates = []
                        if isinstance(payload, dict):
                            for key in ["preMatch"]:
                                v = payload.get(key)
                                if isinstance(v, list):
                                    candidates.extend(v)
                        elif isinstance(payload, list):
                            candidates.extend(payload)
                        for event in candidates:
                            home_team_name = event.get("homeTeamName") or event.get("home") or ""
                            away_team_name = event.get("awayTeamName") or event.get("away") or ""
                            event_id = event.get("eventId") or event.get("id")
                            
                            if not event_id:
                                continue
                                
                            hn = self.__normalize_team(home_team_name)
                            an = self.__normalize_team(away_team_name)
                            est = event.get("estimateStartTime") or event.get("startTime")
                            if pinnacle_start_time and est:
                                try:
                                    diff_h = abs(int(pinnacle_start_time) - int(est)) / (1000 * 60 * 60)
                                    if diff_h > 2:
                                        continue
                                except Exception:
                                    continue
                            lh = self.__extract_longest_tokens(home_team)
                            la = self.__extract_longest_tokens(away_team)
                            ok_l1b = False
                            for x in lh[:1] + la[:1]:
                                if self.__word_match(x, hn) or self.__word_match(x, an):
                                    ok_l1b = True
                                    break
                            sim_hh = self.__lev_similarity(q_home, hn)
                            sim_aa = self.__lev_similarity(q_away, an)
                            sim_ha = self.__lev_similarity(q_home, an)
                            sim_ah = self.__lev_similarity(q_away, hn)
                            best_pair = max(((sim_hh, sim_aa),(sim_ha, sim_ah)), key=lambda t: t[0]+t[1])
                            s1, s2 = best_pair
                            rule_scores = []
                            if s1 >= 25 and s2 >= 25 and (s1 + s2) >= 100:
                                rule_scores.append(400)
                            if ok_l1b and s1 >= 70 or ok_l1b and s2 >= 70:
                                rule_scores.append(350)
                            if q_home == hn and s2 >= 50 or q_home == an and s2 >= 50 or q_away == hn and s1 >= 50 or q_away == an and s1 >= 50:
                                rule_scores.append(300)
                            bs1 = (len(q_home) >= 3 and (q_home in hn or hn in q_home)) or (len(q_home) <= 3 and self.__word_match(q_home, hn))
                            bs2 = (len(q_away) >= 3 and (q_away in an or an in q_away)) or (len(q_away) <= 3 and self.__word_match(q_away, an))
                            if ok_l1b and (s1 >= 50 or s2 >= 50 or (bs1 and bs2)):
                                rule_scores.append(250)
                            if s1 >= 40 and s2 >= 40 and (s1 + s2) >= 100:
                                rule_scores.append(200)
                            if rule_scores:
                                potential_matches.append({
                                    "event_name": f"{home_team_name} vs {away_team_name}",
                                    "event_id": event_id,
                                    "score": max(rule_scores),
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
        
        logger.warning("No matching event found on Sporty")
        return None

    def __get_event_details(self, event_id):
        """Get detailed information about an event from Sporty"""
        logger.info(f"Getting details for event ID: {event_id}")
        
        try:
            details_url = f"{self.__bet_api_host}/factsCenter/event"
            params = {
                'eventId': event_id,
                'productId': '3',
                '_t': str(int(time.time()*1000))
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": self.__bet_host,
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
            
            response = requests.get(details_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            payload = response.json() or {}
            data = payload.get("data") or {}
            home_team = data.get("homeTeamName") or data.get("home") or ""
            away_team = data.get("awayTeamName") or data.get("away") or ""
            sport = data.get("sport") or {}
            sport_id = (data.get("sport") or {}).get("id") or ""
            sport_num = 1
            if "sr:sport:2" in str(sport_id).lower():
                sport_num = 2
            event_details = {
                "homeTeam": home_team,
                "awayTeam": away_team,
                "eventId": data.get("eventId") or event_id,
                "sportId": sport_num,
                "sport": sport,
                "markets": data.get("markets") or []
            }
            logger.info(f"Event details retrieved: {home_team} vs {away_team}")
            return event_details
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting event details: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_event_details: {e}")
            return None

    def __generate_sportybet_bet_url(self, event_details):
        """
        Generate Sporty betting URL based on event details
        """
        try:
            # Get event ID from event details
            event_id = event_details.get("eventId") or event_details.get("event_id") or event_details.get("id")
            
            if not event_id:
                logger.error(f"Missing event_id for URL generation: {event_details}")
                return None
            
            sport = event_details.get("sport") or {}
            logger.info(f"sport: {sport}")
            sname = (sport.get("name") or "").strip()
            category = sport.get("category") or {}
            cname = (category.get("name") or "").strip()
            tournament = category.get("tournament") or {}
            tname = (tournament.get("name") or "").strip()
            home = (event_details.get("homeTeam") or event_details.get("homeTeamName") or "").strip()
            away = (event_details.get("awayTeam") or event_details.get("awayTeamName") or "").strip()

            def _seg(x, lower=False):
                x = re.sub(r"\s+", "_", str(x))
                return x.lower() if lower else x

            sport_seg = _seg(sname, lower=True if sname.lower() in ("football", "basketball") else False)
            category_seg = _seg(cname)
            tournament_seg = _seg(tname)
            match_seg = _seg(f"{home}_vs_{away}")
            id_seg = quote(str(event_id), safe=":")
            logger.info(f"spor_seg: {sport_seg}, category_seg: {category_seg}, tournament_seg: {tournament_seg}, match_seg: {match_seg}, id_seg: {id_seg}")
            if sport_seg and category_seg and tournament_seg and match_seg:
                bet_url = f"{self.__bet_host}/ng/sport/{sport_seg}/{category_seg}/{tournament_seg}/{match_seg}/{id_seg}"
            else:
                bet_url = f"{self.__bet_host}/ng/event?eventId={quote(str(event_id))}&productId=3"
            logger.info(f"Generated Sporty bet URL: {bet_url}")
            
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

    def __wait_for_market_content(self, timeout_seconds: int = 60) -> None:
        """
        Explicitly wait for sportybet market content to render.
        Waits until at least one of the known market containers is present.
        """
        # try:
        #     # Ensure document is at least interactive/complete first
        #     WebDriverWait(self.driver, timeout_seconds).until(
        #         lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
        #     )
        # except Exception:
        #     # Continue to element-based checks even if readyState wait fails
        #     pass
        
        WebDriverWait(self.driver, timeout_seconds, poll_frequency=0.5).until(
            lambda d: d.execute_script("return !!document.querySelector('.m-against');")
        )
        # .m-eventDetail
        # "document.querySelector('.m-table-cell--responsive'));"
        # "document.querySelector('.m-detail-wrapper') || "
        # "document.querySelector('.m-table__wrapper') || "

    def __ensure_session_after_nav(self, account, recent_url):
        try:
            logged = False
            # try:
            #     WebDriverWait(self.driver, 10).until(
            #         EC.presence_of_element_located((By.CSS_SELECTOR, ".m-user-center.m-list"))
            #     )
            #     logger.info(f"ensured")
            #     logged = True
            #     logger.info(f"logged {logged}")
            # except Exception:
            #     logged = False
            # if not logged:
            #     try:
            #         bal = self.__fetch_account_balance(account)
            #         if bal and bal > 0:
            #             logged = True
            #     except Exception:
            #         logged = False
            if not logged:
                try:
                    logged = bool(self.__quick_inline_login(account))
                    logger.info(f"quick inline login {logged}")
                except Exception:
                    logged = False
            return logged
        except Exception:
            return False

    def __quick_inline_login(self, account):
        try:
            try:
                self.driver.execute_script("document.querySelectorAll('.af-toast,.m-dialog,.m-modal,.m-balance-wrapper,.m-bablance-wrapper').forEach(el=>{try{el.style.pointerEvents='none'}catch(e){}});")
                logger.info(f"starting loggin")
            except Exception:
                pass
            try:
                WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".m-user-center.m.list, .m-user-center.m-list"))
                )
                selenium_cookies = self.driver.get_cookies()
                account.set_cookie_jar(selenium_cookies)
                logger.info("actually logged in already")
                return True
            except Exception:
                pass
            logger.info("actually not logged in already")

            phone_input = WebDriverWait(self.driver, 60).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='phone']"))
            )
            try:
                phone_input.clear()
                phone_input.send_keys(account.username)
                logger.info(f"phone input keys {account.username}")
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input', { bubbles: true })); arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", phone_input, account.username)
                except Exception:
                    pass
            password_input = WebDriverWait(self.driver, 30).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='psd']"))
            )
            try:
                password_input.clear()
                password_input.send_keys(account.password)
                logger.info(f"password input keys {account.password}")
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input', { bubbles: true })); arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", password_input, account.password)
                except Exception:
                    pass
            login_button = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[name='logIn'].m-btn.m-btn-login"))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", login_button)
                login_button.click()
                logger.info(f"login button click")
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", login_button)
                except Exception:
                    pass
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".m-user-center.m.list, .m-user-center.m-list"))
            )
            selenium_cookies = self.driver.get_cookies()
            account.set_cookie_jar(selenium_cookies)
            logger.info(f"cookies saved")

            try:
                profile_base = os.path.join(os.getcwd(), "profiles")
                safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                os.makedirs(os.path.join(profile_base, safe_name), exist_ok=True)
                cookie_file = os.path.join(profile_base, safe_name, "cookies.json")
                to_save = {c["name"]: c["value"] for c in selenium_cookies if isinstance(c, dict) and "name" in c and "value" in c}
                with open(cookie_file, "w") as f:
                    json.dump(to_save, f)
            except Exception:
                pass
            logger.info(f"profile saved")
            return True
        except Exception:
            return False

    def __place_bet_with_selenium(self, account, bet_url, market_type, outcome, odds, stake, points=None, is_first_half=False, home_team=None, away_team=None, sport_id=1):
        start_bet_ts = time.time()
        logger.info(f"Starting bet placement: {market_type} - {outcome} - {points} @ {odds}")
        """
        Place a bet on sportybet using Selenium
        
        Parameters:
        - account: BetAccount instance
        - bet_url: sportybet betting URL for the event
        - market_type: Type of bet (moneyline, total, spread)
        - outcome: Outcome to bet on
        - odds: Expected odds
        - stake: Amount to stake
        - points: Points value for total/spread bets
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (from shaped_data)
        - away_team: Name of the away team (from shaped_data)
        - sport_id: Sport ID (1 for soccer, 3 for basketball)
        
        Returns:
        - True if bet was placed successfully, False otherwise
        """
        try:
            # Always login before placing bet (this will also initialize browser if needed)
            logger.info(f"Logging in before placing bet... username-{account.username}")
            login_success = self.__do_login_for_account(account)
            if not login_success:
                logger.error(f"Login failed, cannot place bet username-{account.username}")
                return False
            
            logger.info(f"Navigating to betting page: {bet_url} username-{account.username}")
            self.open_url(bet_url)
            # Full-page screenshot after navigation to confirm navigated_ state
            # try:
            #     self.driver.execute_cdp_cmd("Page.enable", {})
            #     metrics = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
            #     cs = metrics.get("contentSize", {})
            #     width = int(cs.get("width", 1920))
            #     height = int(cs.get("height", 1080))
            #     self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            #         "mobile": False,
            #         "width": width,
            #         "height": height,
            #         "deviceScaleFactor": 1,
            #         "screenOrientation": {"type": "landscapePrimary", "angle": 0}
            #     })
            #     shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {
            #         "format": "png",
            #         "captureBeyondViewport": True
            #     })
            #     import base64
            #     timestamp = time.strftime("%Y%m%d-%H%M%S")
            #     fname = f"navigated_{account.username}_{timestamp}.png"
            #     with open(fname, "wb") as f:
            #         f.write(base64.b64decode(shot.get("data", "")))
            #     logger.info(f"Saved full-page logged-in screenshot: {fname}")
            # except Exception:
            #     timestamp = time.strftime("%Y%m%d-%H%M%S")
            #     fname = f"navigated_{account.username}_{timestamp}.png"
            #     self.driver.save_screenshot(fname)
            #     logger.info(f"Saved fallback logged-in screenshot: {fname}")
            # try:
            #     self.__ensure_session_after_nav(account, bet_url)
            # except Exception:
            #     pass
            # Wait for the market content to render instead of using sleep
            logger.info(f"about to check market content username-{account.username}")
            try:
                self.__wait_for_market_content(timeout_seconds=60)
                logger.info("found market content")
            except Exception as e:
                logger.warning(f"Market content not detected within wait window username-{account.username}: {e}")
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                fname = f"market_content_not_detected_{timestamp}.png"
                try:
                    self.driver.execute_cdp_cmd("Page.enable", {})
                    metrics = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                    cs = metrics.get("contentSize", {})
                    width = int(cs.get("width", 1920))
                    height = int(cs.get("height", 1080))
                    self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                        "mobile": False,
                        "width": width,
                        "height": height,
                        "deviceScaleFactor": 1,
                        "screenOrientation": {"type": "landscapePrimary", "angle": 0}
                    })
                    shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {
                        "format": "png",
                        "captureBeyondViewport": True
                    })
                    import base64
                    with open(fname, "wb") as f:
                        f.write(base64.b64decode(shot.get("data", "")))
                except Exception:
                    self.driver.save_screenshot(fname)
                logger.info(f"Saved full-page screenshot: {fname}")
                current_shaped_data = getattr(self, '_current_shaped_data', None)
                try:
                    ev = self.__calculate_ev(odds, current_shaped_data) if current_shaped_data else -999
                    logger.info(f"ev: {ev} username-{account.username}")
                except Exception:
                    ev = -999
                if ev > self.__min_ev and not getattr(self, '_retry_once', False):
                    logger.info(f"EV {ev} higher than min EV {self.__min_ev}, retrying once username-{account.username}")
                    setattr(self, '_retry_once', True)
                    try:
                        return self.__place_bet_with_selenium(account, bet_url, market_type, outcome, odds, stake, points, is_first_half, home_team, away_team, sport_id)
                    finally:
                        setattr(self, '_retry_once', False)
                return False
            
            # time.sleep(3)
            
            # try:
            #     remove_all = WebDriverWait(self.driver, 5).until(
            #         EC.element_to_be_clickable((By.CSS_SELECTOR, "span.m-text-min[data-cms-key='remove_all'][data-cms-page='component_betslip']"))
            #     )
            #     try:
            #         self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", remove_all)
            #     except Exception:
            #         pass
            #     try:
            #         remove_all.click()
            #         logger.info(f"remove all button clicked")
            #     except Exception:
            #         try:
            #             self.driver.execute_script("arguments[0].click();", remove_all)
            #         except Exception:
            #             pass
            #     try:
            #         ok_btn = WebDriverWait(self.driver, 5).until(
            #             EC.element_to_be_clickable((By.CSS_SELECTOR, ".m-dialog-footer.es-dialog-footer a.es-dialog-btn[data-ret='1']"))
            #         )
            #         ok_btn.click()
            #         logger.info(f"ok button clicked")
            #     except Exception:
            #         pass
            # except Exception:
            #     pass
            
            # Find and click the market/outcome
            market_element, odds_from_api = self.__get_market_selector(market_type, outcome, points, is_first_half, home_team, away_team, sport_id)
            logger.info(f"Market element: {market_element}")
            if not market_element:
                logger.error(f"Could not find market element username-{account.username}")
                # Capture full-page screenshot
                try:
                    self.driver.execute_cdp_cmd("Page.enable", {})
                    metrics = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                    cs = metrics.get("contentSize", {})
                    width = int(cs.get("width", 1920))
                    height = int(cs.get("height", 1080))
                    self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                        "mobile": False,
                        "width": width,
                        "height": height,
                        "deviceScaleFactor": 1,
                        "screenOrientation": {"type": "landscapePrimary", "angle": 0}
                    })
                    shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {
                        "format": "png",
                        "captureBeyondViewport": True
                    })
                    import base64
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    with open(f"market_not_found_{timestamp}.png", "wb") as f:
                        f.write(base64.b64decode(shot.get("data", "")))
                except Exception:
                    # Fallback to regular screenshot
                    self.driver.save_screenshot("market_not_found.png")
                current_shaped_data = getattr(self, '_current_shaped_data', None)
                try:
                    ev_odds = odds
                    ev = self.__calculate_ev(ev_odds, current_shaped_data) if current_shaped_data else -999
                    logger.info(f"ev: {ev} username-{account.username}")
                except Exception:
                    ev = -999
                if ev > self.__min_ev and not getattr(self, '_retry_once', False):
                    logger.info(f"EV is high enough: {ev} > {self.__min_ev} username-{account.username}")
                    setattr(self, '_retry_once', True)
                    try:
                        return self.__place_bet_with_selenium(account, bet_url, market_type, outcome, odds, stake, points, is_first_half, home_team, away_team, sport_id)
                    finally:
                        setattr(self, '_retry_once', False)
                return False
            
            try:
                logger.info(f"Found market element for: {market_type} - {outcome} - {points}")
                
                # # Verify odds before placing bet
                try:
                    if odds_from_api:
                        actual_odds = float(odds_from_api)
                        odds_diff = abs(actual_odds - odds)
                        
                        if odds_diff > 0.1:  # Allow 0.1 difference
                            logger.error(f"⚠️ Odds mismatch! Expected: {odds}, Actual: {actual_odds} username-{account.username}")
                            logger.error("Bet cancelled due to odds change")
                            return False
                        else:
                            logger.info(f"✅ Odds verified: {actual_odds} (expected: {odds})  username-{account.username}")
                    else:
                        logger.error("No odds from API")    
                        return False
                except Exception as e:
                    logger.error(f"Could not verify odds: {e}")
                
                # Simple direct clicking approach - no scrolling
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable(market_element)
                    )
                    market_element.click()
                    logger.info(f"Clicked on market: {market_type} - {outcome} - {points}")
                except Exception as click_error:
                    logger.error(f"Direct click failed, trying JavaScript click: {click_error}")
                    try:
                        self.driver.execute_script("arguments[0].click();", market_element)
                        logger.info(f"JavaScript clicked on market: {market_type} - {outcome} - {points}")
                    except Exception as js_error:
                        logger.error(f"JavaScript click also failed: {js_error}")
                        try:
                            actions = ActionChains(self.driver)
                            actions.move_to_element(market_element).click().perform()
                            logger.info(f"ActionChains clicked on market: {market_type} - {outcome} - {points}")
                        except Exception as action_error:
                            logger.error(f"All click methods failed: {action_error}")
                            raise Exception("All click methods failed")
                
            except Exception as e:
                    logger.error(f"Could not click market element: {e}")
                    return False
            
            # Navigate to a low-odds virtual event URL before entering stake
            try:
                logger.info(f"working on dummy veirtuals now2")
                low_candidates = self.__get_low_odds_virtual_candidates(account, max_odds=1.2, limit=5)
                logger.info(f"Candidates: {low_candidates}")
                if low_candidates:
                    logger.info(f"Found {len(low_candidates)} low-odds virtual candidates")
                    pick_count = getattr(self, "_virtual_pick_toggle", 1)
                    sel = low_candidates[:min(len(low_candidates), pick_count)]
                    for target in sel:
                        try:
                            if target.get("event_id"):
                                self.__used_virtual_event_ids.add(target["event_id"])
                        except Exception:
                            pass
                        self.open_url(target["url"])
                        try:
                            self.__ensure_session_after_nav(account, target["url"])
                        except Exception:
                            pass

                        try:
                            self.__wait_for_market_content(timeout_seconds=60)
                            logger.info("found market content")
                            # WebDriverWait(self.driver, 10).until(
                            #     lambda d: d.execute_script("return document.querySelectorAll('.m-table__wrapper').length > 0;")
                            # )
                        except Exception:
                            pass
                        me2, _o2 = self.__get_market_selector(target["market_type"], target["outcome"], target.get("points"), False, target.get("home"), target.get("away"))
                        if me2:
                            try:
                                WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable(me2))
                                me2.click()
                                logger.info(f"Clicked backup low-odds market: {target['market_type']} - {target['outcome']} - {target.get('points')}")
                            except Exception:
                                try:
                                    self.driver.execute_script("arguments[0].click();", me2)
                                    logger.info("JavaScript clicked backup market")
                                except Exception:
                                    actions = ActionChains(self.driver)
                                    actions.move_to_element(me2).click().perform()
                                    logger.info("ActionChains clicked backup market")
                    try:
                        self._virtual_pick_toggle = 1 if pick_count == 1 else 1
                    except Exception:
                        pass
            except Exception:
                pass

            # Enter stake amount using new sportybet selectors
            try:
                # Fallback: Use JavaScript to find and set stake input
                logger.info("Trying JavaScript fallback for stake input")
                script = """
                var stakeInput = document.querySelector('.m-input-wrapper input.m-input.fs-exclude');
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
                    # time.sleep(5)
                    return False
            except Exception as e:
                logger.error(f"Error entering stake with selector: {e}")
                try:
                    # Find the stake input using the new selector structure
                    stake_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input.m-input.fs-exclude"))
                    )
                    
                    # Clear existing value and enter new stake
                    stake_input.clear()
                    stake_input.send_keys(str(stake))
                    logger.info(f"✅ Successfully entered stake: {stake}")
                except Exception as js_error:
                    logger.error(f"fallback also failed: {js_error}")
                    return False
                    
            # try:
            #     game_name = f"{home_team}_vs_{away_team}" if home_team and away_team else "bet_confirmation"
            #     timestamp = time.strftime("%Y%m%d-%H%M%S")
            #     fname = re.sub(r"[^A-Za-z0-9_.-]", "_", game_name) + f"_{timestamp}.png"
            #     try:
            #         self.driver.execute_cdp_cmd("Page.enable", {})
            #         metrics = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
            #         cs = metrics.get("contentSize", {})
            #         width = int(cs.get("width", 1920))
            #         height = int(cs.get("height", 1080))
            #         self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"mobile": False, "width": width, "height": height, "deviceScaleFactor": 1, "screenOrientation": {"type": "landscapePrimary", "angle": 0}})
            #         shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
            #         import base64
            #         with open(fname, "wb") as f:
            #             f.write(base64.b64decode(shot.get("data", "")))
            #     except Exception:
            #         self.driver.save_screenshot(fname)
            #     logger.info(f"Saved pre-confirm screenshot: {fname}")
            # except Exception:
            #     pass
            # Place the bet using new sportybet selectors
            try:
                # Wait for the bet button to be clickable
                place_bet_button = WebDriverWait(self.driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div.m-btn-wrapper button.af-button.af-button--primary"))
                )
                
                button_text = place_bet_button.text.strip()
                logger.info(f"Found bet button with text: {button_text}")
                
                try:
                    active_key = self.driver.execute_script("var el=document.querySelector('.m-list-nav .m-table-row .m-table-cell.m-table-cell--active span[data-cms-key]'); return el ? (el.getAttribute('data-cms-key') || el.textContent.trim().toLowerCase()) : null;")
                except Exception:
                    active_key = None
                if (active_key or '').lower() != 'multiple':
                    logger.warning(f"Betslip tab not 'Multiple' (got: {active_key}) username-{account.username}. Aborting placement.")
                    try:
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"wrong_betslip_mode_{account.username}_{ts}.png"
                        self.driver.execute_cdp_cmd("Page.enable", {})
                        m = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                        cs = m.get("contentSize", {})
                        w = int(cs.get("width", 1920))
                        h = int(cs.get("height", 1080))
                        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"mobile": False, "width": w, "height": h, "deviceScaleFactor": 1, "screenOrientation": {"type": "landscapePrimary", "angle": 0}})
                        shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
                        import base64
                        with open(fname, "wb") as f:
                            f.write(base64.b64decode(shot.get("data", "")))
                        logger.info(f"Saved full-page wrong-mode screenshot: {fname}")
                    except Exception:
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"wrong_betslip_mode_{account.username}_{ts}.png"
                        self.driver.save_screenshot(fname)
                    return False

                try:
                    self.driver.execute_script("document.querySelectorAll('.m-bablance-wrapper,.m-balance-wrapper,.af-toast').forEach(el=>{try{el.style.pointerEvents='none'}catch(e){}});")
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", place_bet_button)
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.execute_script("const el=arguments[0]; const r=el.getBoundingClientRect(); const x=r.left+r.width/2; const y=r.top+r.height/2; const topEl=document.elementFromPoint(x,y); return topEl===el || el && el.contains(topEl);", place_bet_button)
                    )
                    if "accept changes" in (button_text or "").lower():
                        place_bet_button.click()
                        time.sleep(0.5)
                        try:
                            place_bet_button = WebDriverWait(self.driver, 10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.m-btn-wrapper button.af-button.af-button--primary"))
                            )
                        except Exception:
                            pass
                        place_bet_button.click()
                        logger.info("Accepted changes and clicked bet button")
                    else:
                        place_bet_button.click()
                        logger.info("Clicked bet button")
                except Exception as click_error:
                    logger.error(f"Place bet click intercepted, trying fallbacks: {click_error}")
                    try:
                        self.driver.execute_script("arguments[0].click();", place_bet_button)
                        logger.info("Clicked bet button via JavaScript")
                    except Exception as js_error:
                        logger.error(f"JavaScript click failed: {js_error}")
                        try:
                            actions = ActionChains(self.driver)
                            actions.move_to_element(place_bet_button).click().perform()
                            logger.info("Clicked bet button via ActionChains")
                        except Exception as action_error:
                            logger.error(f"All place bet click methods failed username-{account.username}: {action_error}")
                            try:
                                ts = time.strftime("%Y%m%d-%H%M%S")
                                self.driver.save_screenshot(f"place_bet_click_error_{ts}.png")
                            except Exception:
                                pass
                            return False
                try:
                    active_key = self.driver.execute_script("var el=document.querySelector('.m-list-nav .m-table-row .m-table-cell.m-table-cell--active span[data-cms-key]'); return el ? (el.getAttribute('data-cms-key') || el.textContent.trim().toLowerCase()) : null;")
                except Exception:
                    active_key = None
                if (active_key or '').lower() != 'multiple':
                    logger.warning(f"Betslip tab not 'Multiple' (got: {active_key}) username-{account.username}. Aborting placement.")
                    try:
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"wrong_betslip_mode_2{account.username}_{ts}.png"
                        self.driver.execute_cdp_cmd("Page.enable", {})
                        m = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                        cs = m.get("contentSize", {})
                        w = int(cs.get("width", 1920))
                        h = int(cs.get("height", 1080))
                        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"mobile": False, "width": w, "height": h, "deviceScaleFactor": 1, "screenOrientation": {"type": "landscapePrimary", "angle": 0}})
                        shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
                        import base64
                        with open(fname, "wb") as f:
                            f.write(base64.b64decode(shot.get("data", "")))
                        logger.info(f"Saved full-page wrong-mode screenshot: {fname}")
                    except Exception:
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"wrong_betslip_mode_2{account.username}_{ts}.png"
                        self.driver.save_screenshot(fname)
                    return False
                    
                try:
                    confirm_span = WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button.af-button.af-button--primary span span[data-cms-key='confirm']"))
                    )
                    try:
                        self.driver.execute_script("arguments[0].closest('button').click();", confirm_span)
                        logger.info("Clicked confirm button")
                    except Exception:
                        try:
                            btn = confirm_span.find_element(By.XPATH, "ancestor::button[1]")
                            WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable(btn))
                            btn.click()
                            logger.info("Clicked confirm button (fallback)")
                        except Exception:
                            pass
                except Exception:
                    pass
                
                # If button says "Accept Odds...", odds have changed - need to recalculate EV
                # if "accept odds" in button_text.lower():
                #     logger.warning("⚠️ Odds have changed! discarding bet...")
                #     return False
                    # try:
                    #     # Get the shaped_data from the current bet context
                    #     current_shaped_data = getattr(self, '_current_shaped_data', None)
                    #     if not current_shaped_data:
                    #         logger.error("No shaped_data available for EV recalculation")
                    #         self.__take_screenshot("odds_change_no_shaped_data")
                    #         return False
                        
                    #     # Get event ID from shaped data and fetch event details
                    #     event_id = current_shaped_data.get("eventId")
                    #     if not event_id:
                    #         logger.error("No eventId found in shaped data")
                    #         self.__take_screenshot("odds_change_no_event_id")
                    #         return False
                        
                    #     # Get event details from sportybet API to get exact odds
                    #     event_details = self.__get_event_details(event_id)
                    #     if not event_details:
                    #         logger.error("Failed to get event details from sportybet API")
                    #         self.__take_screenshot("odds_change_no_event_details")
                    #         return False
                        
                    #     # Extract bet parameters from shaped_data
                    #     line_type = current_shaped_data["category"]["type"].lower()
                    #     outcome = current_shaped_data["category"]["meta"]["team"]
                    #     points = current_shaped_data["category"]["meta"].get("value")
                    #     is_first_half = current_shaped_data.get("periodNumber") == "1"
                    #     home_team = current_shaped_data["game"]["home"]
                    #     away_team = current_shaped_data["game"]["away"]
                        
                    #     # Get the exact market and odds from sportybet API using the same method as initial bet
                    #     bet_code, new_odds, _ = self.__find_market_bet_code_with_points(
                    #         event_details, line_type, outcome, points, is_first_half, home_team, away_team
                    #     )
                        
                    #     if not new_odds:
                    #         logger.error("Could not get new odds from sportybet API")
                    #         self.__take_screenshot("odds_change_no_odds_from_api")
                    #         return False
                        
                    #     logger.info(f"New odds from sportybet API: {new_odds}")
                        
                    #     # Recalculate EV with new odds
                    #     new_ev = self.__calculate_ev(new_odds, current_shaped_data)
                    #     logger.info(f"📊 Recalculated EV with new odds {new_odds}: {new_ev:.2f}%")
                        
                    #     if new_ev > 0:
                    #         logger.info("✅ EV still positive, accepting odds change...")
                    #         time.sleep(1)  # Wait a moment for button to update
                            
                    #         # Click accept odds button
                    #         updated_button = WebDriverWait(self.driver, 10).until(
                    #             EC.element_to_be_clickable((By.CSS_SELECTOR, "button.betslip-bet-button"))
                    #         )
                    #         updated_button.click()
                    #         logger.info("Clicked accept odds button")
                    #     else:
                    #         logger.warning(f"❌ EV turned negative ({new_ev:.2f}%), aborting bet...")
                    #         self.__take_screenshot("odds_change_negative_ev")
                    #         return False  # Abort this bet
                            
                    # except Exception as odds_check_error:
                    #     logger.error(f"Error checking odds change: {odds_check_error}")
                    #     self.__take_screenshot("odds_change_error")
                    #     return False  # Any error = abort bet
                
                # Wait for success confirmation
                try:
                    success_element = WebDriverWait(self.driver, 25).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cms-key='submission_successful']"))
                    )
                    success_text = success_element.text.strip()
                    if "Submission Successful" in success_text:
                        logger.info("✅ Bet placed successfully!")
                        elapsed = time.time() - start_bet_ts
                        logger.info(f"Bet placement took {elapsed:.2f}s")

                        try:
                            ok_btn = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, ".m-btn-wrapper.m-ok-wrap button.af-button.af-button--primary[data-action='close'][data-ret='close']"))
                            )
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", ok_btn)
                            except Exception:
                                pass
                            try:
                                ok_btn.click()
                            except Exception:
                                try:
                                    self.driver.execute_script("arguments[0].click();", ok_btn)
                                except Exception:
                                    pass
                            time.sleep(1)
                            # try:
                            #     dn = f"finally_done_{(target.get('home') or '')}_vs_{(target.get('away') or '')}".strip("_") or "finally_done"
                            #     ts = time.strftime("%Y%m%d-%H%M%S")
                            #     fname = re.sub(r"[^A-Za-z0-9_.-]", "_", dn) + f"_{ts}.png"
                            #     try:
                            #         self.driver.execute_cdp_cmd("Page.enable", {})
                            #         m = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                            #         cs = m.get("contentSize", {})
                            #         w = int(cs.get("width", 1920))
                            #         h = int(cs.get("height", 1080))
                            #         self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"mobile": False, "width": w, "height": h, "deviceScaleFactor": 1, "screenOrientation": {"type": "landscapePrimary", "angle": 0}})
                            #         shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
                            #         import base64
                            #         with open(fname, "wb") as f:
                            #             f.write(base64.b64decode(shot.get("data", "")))
                            #     except Exception:
                            #         self.driver.save_screenshot(fname)
                            #     logger.info(f"Saved final screenshot: {fname}")
                            # except Exception:
                            #     pass
                        except Exception:
                            pass

                        
                        return True
                    else:
                        logger.warning(f"⚠️ Unexpected success message: {success_text}")
                        return False
                        
                except Exception as e:
                    logger.error(f"❌ No success confirmation found: {e}")
                    try:
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"failed_bet_screenshot_{ts}.png"
                        try:
                            self.driver.execute_cdp_cmd("Page.enable", {})
                            m = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                            cs = m.get("contentSize", {})
                            w = int(cs.get("width", 1920))
                            h = int(cs.get("height", 1080))
                            self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"mobile": False, "width": w, "height": h, "deviceScaleFactor": 1, "screenOrientation": {"type": "landscapePrimary", "angle": 0}})
                            shot = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
                            import base64
                            with open(fname, "wb") as f:
                                f.write(base64.b64decode(shot.get("data", "")))
                        except Exception:
                            self.driver.save_screenshot(fname)
                        logger.info(f"Failed bet screenshot saved to username-{account.username}: {fname}")
                    except Exception as screenshot_error:
                        logger.error(f"Failed to take failed bet screenshot: {screenshot_error}")
                    try:
                        new_stake = float(stake) / 2.0
                    except Exception:
                        new_stake = stake
                    current_shaped_data = getattr(self, '_current_shaped_data', None)
                    try:
                        ev_odds = float(odds)
                        ev = self.__calculate_ev(ev_odds, current_shaped_data) if current_shaped_data else -999
                    except Exception:
                        ev = -999
                    if ev > self.__min_ev and not getattr(self, '_retry_no_success_once', False):
                        setattr(self, '_retry_no_success_once', True)
                        try:
                            return self.__place_bet_with_selenium(account, bet_url, market_type, outcome, odds, new_stake, points, is_first_half, home_team, away_team, sport_id)
                        finally:
                            setattr(self, '_retry_no_success_once', False)
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
                return self.__place_bet_with_selenium(account, bet_url, market_type, outcome, odds, stake, points, is_first_half, home_team, away_team, sport_id)
            
            logger.error(f"Error placing bet with Selenium: {e}")
            # Take screenshot of error state
            try:
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                screenshot_path = f"error_screenshot_{timestamp}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Error screenshot saved to username-{account.username} {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to take error screenshot: {screenshot_error}")
            import traceback
            traceback.print_exc()
            return False

    def __get_market_selector(self, market_type, outcome, points=None, is_first_half=False, home_team=None, away_team=None, sport_id=1):
        """
        Get the CSS selector for a specific market and outcome on sportybet
        
        Parameters:
        - market_type: Type of bet (moneyline, total, spread)
        - outcome: Outcome to bet on
        - points: Points value for total/spread bets
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (from shaped_data)
        - away_team: Name of the away team (from shaped_data)
        - sport_id: Sport ID (1 for soccer, 3 for basketball)
        
        Returns:
        - Element or None if not found
        """
        market_type_lower = market_type.lower()
        outcome_lower = outcome.lower()

        logger.info(f"market_type_lower: {market_type_lower}, outcome_lower: {outcome_lower}, is_first_half: {is_first_half}, home_team: {home_team}, away_team: {away_team}, points: {points}")
        if is_first_half:
            try:
                nav_items = self.driver.find_elements(By.CSS_SELECTOR, ".m-nav .m-nav-item div")
                for el in nav_items:
                    tx = el.text.strip().lower()
                    if "half" in tx:
                        el.click()
                        time.sleep(1)
                        break
            except Exception:
                pass
        else:
            try:
                # logger.info("clicking main")
                nav_items = self.driver.find_elements(By.CSS_SELECTOR, ".m-nav .m-nav-item div")
                logger.info(f"nav: {nav_items}")
                for idx, nav in enumerate(nav_items):
                    try:
                        html = nav.get_attribute("outerHTML")
                        logger.info(f"nav[{idx}] HTML: {html}")
                    except Exception as ex:
                        logger.warning(f"Could not get HTML for nav[{idx}]: {ex}")
                for el in nav_items:
                    logger.info("1 main")
                    tx = el.text.strip().lower()
                    logger.info(f"=main: {tx}")
                    if "main" in tx:
                        logger.info("clicked main")
                        el.click()
                        time.sleep(1)
                        break
            except Exception:
                pass
        
        try:
            wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".m-table__wrapper")
            if not wrappers:
                logger.info("reutened none")
                return None, None
        except Exception as e:
            logger.error(f"Error finding market containers: {e}")
            return None, None
        
        # Check if this is basketball
        # is_basketball = (sport_id == "3" or sport_id == 3)
        
        # 1X2 (Moneyline) - First div from the list
        if market_type_lower == "moneyline" or market_type_lower == "money_line":
            return self.__sporty_find_1x2(outcome_lower, is_first_half)
        
        # Over/Under
        elif market_type_lower == "total":
            if not points:
                return None, None
            return self.__sporty_find_total(points, outcome_lower)
        
        # Asian Handicap
        elif market_type_lower == "spread":
            if points is None:
                return None, None
            if abs(float(points)) < 0.01:
                return self.__sporty_find_dnb(outcome_lower, home_team, away_team)
            return self.__sporty_find_handicap(points, outcome_lower, home_team, away_team)
        
        return None, None

    def __get_low_odds_virtual_candidates(self, account, max_odds=1.2, limit=5):
        try:
            ts = str(int(time.time() * 1000))
            url = f"{self.__bet_api_host}/factsCenter/pcUpcomingEvents?sportId=sr:sport:202120001&marketId=1,18&pageSize=100&pageNum=1&option=1&timeline=2&_t={ts}"
            cookies = {}
            if hasattr(account, 'cookie_jar') and account.cookie_jar:
                if isinstance(account.cookie_jar, dict):
                    cookies = account.cookie_jar
                elif isinstance(account.cookie_jar, list):
                    cookies = {c.get('name'): c.get('value') for c in account.cookie_jar}
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.sportybet.com/ng/",
                "Origin": "https://www.sportybet.com"
            }
            resp = requests.get(url, headers=headers, cookies=cookies)
            logger.info(f"Response status code: {resp.status_code}")

            if resp.status_code != 200:
                return []
            data = resp.json().get("data", {})
            tournaments = data.get("tournaments", [])
            now_ms = int(time.time() * 1000)
            candidates = []
            for t in tournaments:
                events = t.get("events", [])
                for ev in events:
                    est = ev.get("estimateStartTime")
                    if not isinstance(est, int):
                        continue
                    if est < now_ms + 5 * 60 * 1000:
                        continue
                    home = ev.get("homeTeamName") or ""
                    away = ev.get("awayTeamName") or ""
                    sport = ev.get("sport", {})
                    sname = (sport.get("name") or "").strip()
                    cat = sport.get("category", {})
                    cname = (cat.get("name") or "").strip()
                    tour = cat.get("tournament", {})
                    tname = (tour.get("name") or "").strip()
                    eid = ev.get("eventId") or ""
                    best = None
                    best_info = None
                    for m in ev.get("markets", []):
                        mname = (m.get("name") or m.get("desc") or "").strip().lower()
                        for o in m.get("outcomes", []):
                            ia = o.get("isActive", 1)
                            try:
                                if int(str(ia)) == 0:
                                    continue
                            except Exception:
                                if str(ia).strip().lower() in ("0", "false"):
                                    continue
                            otxt = (o.get("desc") or o.get("name") or "").strip().lower()
                            odds_raw = o.get("odds") or o.get("value") or o.get("price")
                            try:
                                odds_val = float(odds_raw)
                            except Exception:
                                continue
                            if odds_val <= max_odds:
                                if best is None or odds_val < best:
                                    mt = None
                                    pts = None
                                    oc = None
                                    if "1x2" in mname:
                                        mt = "moneyline"
                                        if "home" in otxt:
                                            oc = "home"
                                        elif "away" in otxt:
                                            oc = "away"
                                        elif "draw" in otxt:
                                            oc = "draw"
                                    elif "over/under" in mname or "total" in mname:
                                        mt = "total"
                                        mm = re.search(r"(over|under)\s*(\d+\.?\d*)", otxt)
                                        if mm:
                                            oc = mm.group(1)
                                            try:
                                                pts = float(mm.group(2))
                                            except Exception:
                                                pts = None
                                    elif "handicap" in mname:
                                        mt = "spread"
                                        side = None
                                        if home and home.lower() in otxt:
                                            side = "home"
                                        elif away and away.lower() in otxt:
                                            side = "away"
                                        mm = re.search(r"([+-]?\d+\.?\d*)", otxt)
                                        if side:
                                            oc = side
                                            try:
                                                pts = float(mm.group(1)) if mm else None
                                            except Exception:
                                                pts = None
                                    if mt and oc:
                                        best = odds_val
                                        best_info = {
                                            "market_type": mt,
                                            "outcome": oc,
                                            "points": pts,
                                            "odds": odds_val
                                        }
                    if best_info:
                        seg_s = quote(sname, safe="")
                        seg_c = quote(cname, safe="")
                        seg_t = quote(tname, safe="")
                        seg_match = quote(f"{home}_vs_{away}", safe="")
                        seg_id = quote(eid, safe="")
                        u = f"{self.__bet_host}/ng/sport/{seg_s}/{seg_c}/{seg_t}/{seg_match}/{seg_id}"
                        candidates.append({
                            "url": u,
                            "home": home,
                            "away": away,
                            "market_type": best_info["market_type"],
                            "outcome": best_info["outcome"],
                            "points": best_info["points"],
                            "odds": best_info["odds"],
                            "event_id": eid
                        })
            candidates = [c for c in candidates if c.get("event_id") not in self.__used_virtual_event_ids]
            candidates.sort(key=lambda x: x.get("odds", 9999))
            logger.info(f"Found {len(candidates)} candidates for {home} vs {away}")
            return candidates[:limit]
        except Exception:
            return []
    
    def __sporty_find_1x2(self, outcome, is_first_half=False):
        """
        Find the 1X2 outcome element for sportybet
        
        Parameters:
        - market_row: The market row element for 1X2 (not used in new implementation)
        - outcome: 'home', 'draw', or 'away'
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info(f"moneyline outcome: {outcome}")
            wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".m-table__wrapper")
            for w in wrappers:
                try:
                    header = w.find_element(By.CSS_SELECTOR, ".m-table-header .m-table-header-title")
                    ht = header.text.strip().lower()
                    # logger.info(f"ht {ht}")
                    if (is_first_half and ("1st" in ht and "half" in ht and "1x2" in ht and "up" not in ht)) or (not is_first_half and "up" not in ht and (ht == "1x2" or ("1x2" in ht and "half" not in ht))):
                        # logger.info(f"1X2 header found")
                        table = w.find_element(By.CSS_SELECTOR, ".m-table-row.m-outcome")
                        cells = table.find_elements(By.CSS_SELECTOR, ".m-table-cell.m-table-cell--responsive")
                        mapping = {"home": "home", "draw": "draw", "away": "away"}
                        target = mapping.get(outcome)
                        # Dump the outerHTML of each cell so we can see the actual markup
                        for idx, cell in enumerate(cells):
                            try:
                                html = cell.get_attribute("outerHTML")
                                logger.info(f"cell[{idx}] HTML: {html}")
                            except Exception as ex:
                                logger.warning(f"Could not get HTML for cell[{idx}]: {ex}")
                        # logger.info(f"cells no: {len(cells)}")
                        for cell in cells:
                            labels = cell.find_elements(By.CSS_SELECTOR, ".m-table-cell-item")
                            logger.info(f"labels: {labels}")
                            if len(labels) >= 2:
                                label = labels[0].text.strip().lower()
                                if label == target:
                                    odds_text = labels[1].text.strip()
                                    try:
                                        return cell, float(odds_text)
                                    except Exception:
                                        return cell, None
                except Exception:
                    continue
            return None, None
                
        except Exception as e:
            logger.error(f"Error finding 1X2 outcome: {e}")
            return None, None
    
    def __sporty_find_total(self, target_points, outcome):
        """
        Find the over/under outcome element for sportybet
        
        Parameters:
        - target_points: Points value to look for
        - outcome: 'over' or 'under'
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info("total find selector")
            wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".m-table__wrapper")
            for w in wrappers:
                try:
                    header = w.find_element(By.CSS_SELECTOR, ".m-table-header .m-table-header-title")
                    if "over/under" or "o/u" in header.text.strip().lower():
                        rows = w.find_elements(By.CSS_SELECTOR, ".m-table .m-table-row")
                        for row in rows:
                            cells = row.find_elements(By.CSS_SELECTOR, ".m-table-cell.m-table-cell--responsive")
                            for cell in cells:
                                labels = cell.find_elements(By.CSS_SELECTOR, ".m-table-cell-item")
                                if len(labels) >= 2:
                                    label = labels[0].text.strip().lower()
                                    odds_text = labels[1].text.strip()
                                    m = re.search(r"(over|under)\s*(\d+\.?\d*)", label)
                                    if m:
                                        side = m.group(1)
                                        pts = float(m.group(2))
                                        if side == outcome and abs(pts - float(target_points)) < 0.01:
                                            try:
                                                return cell, float(odds_text)
                                            except Exception:
                                                return cell, None
                except Exception:
                    continue
            return None, None
            
        except Exception as e:
            logger.error(f"Error finding total outcome: {e}")
            return None, None
    
    def __sporty_find_handicap(self, target_points, outcome, home_team, away_team):
        """
        Find the Asian handicap outcome element for sportybet
        
        Parameters:
        - target_points: Points value to look for
        - outcome: 'home' or 'away'
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info(f"spread find selector {outcome}")
            wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".m-table__wrapper")
            for w in wrappers:
                try:
                    header = w.find_element(By.CSS_SELECTOR, ".m-table-header .m-table-header-title")
                    if "asian handicap" in header.text.strip().lower():
                        logger.info("header found")
                        rows = w.find_elements(By.CSS_SELECTOR, ".m-table .m-table-row")
                        for row in rows:
                            cells = row.find_elements(By.CSS_SELECTOR, ".m-table-row.m-outcome .m-table-cell.m-table-cell--responsive")
                            for cell in cells:
                                labels = cell.find_elements(By.CSS_SELECTOR, ".m-table-cell-item")
                                if len(labels) >= 2:
                                    label = labels[0].text.strip().lower()
                                    odds_text = labels[1].text.strip()
                                    logger.info(f"label: {label}")
                                    logger.info(f"odds_text: {odds_text}")
                                    side = None
                                    ms = re.match(r"^\s*(home|away)\b", label)
                                    if ms:
                                        side = ms.group(1)
                                    else:
                                        if home_team and home_team.lower() in label:
                                            side = "home"
                                        elif away_team and away_team.lower() in label:
                                            side = "away"
                                    m = re.search(r"([+-]?\d+\.?\d*)", label)
                                    logger.info(f"gotten point {m}")    
                                    logger.info(f"side: {side}")

                                    if side == outcome and m:
                                        logger.info("im here")
                                        pts = float(m.group(1))
                                        logger.info(f"pts {pts}")
                                        if abs(pts - float(target_points)) < 0.01:
                                            logger.info("done")
                                            try:
                                                return cell, float(odds_text)
                                            except Exception:
                                                return cell, None
                except Exception:
                    continue
            return None, None
            
        except Exception as e:
            logger.error(f"Error finding handicap outcome: {e}")
            return None, None

    def __sporty_find_dnb(self, outcome, home_team=None, away_team=None):
        """
        Find the DNB (Draw No Bet) outcome element for sportybet
        
        Parameters:
        - outcome: 'home' or 'away'
        - is_first_half: Whether this is a first half bet
        - home_team: Name of the home team (optional)
        - away_team: Name of the away team (optional)
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info(f"Finding DNB outcome for {outcome}, {home_team}, {away_team}")
            wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".m-table__wrapper")
            for w in wrappers:
                try:
                    header = w.find_element(By.CSS_SELECTOR, ".m-table-header .m-table-header-title")
                    if "draw no bet" in header.text.strip().lower():
                        logger.info(f"seen header")
                        cells = w.find_elements(By.CSS_SELECTOR, ".m-table-row.m-outcome .m-table-cell.m-table-cell--responsive")
                        logger.info(f"len of cells {len(cells)}")
                        # Dump the outerHTML of each cell so we can see the actual markup
                        # for idx, cell in enumerate(cells):
                        #     try:
                        #         html = cell.get_attribute("outerHTML")
                        #         logger.info(f"cell[{idx}] HTML: {html}")
                        #     except Exception as ex:
                        #         logger.warning(f"Could not get HTML for cell[{idx}]: {ex}")
                        for cell in cells:
                            labels = cell.find_elements(By.CSS_SELECTOR, ".m-table-cell-item")
                            logger.info(f"labels: {len(labels)}")
                            # for idx, label in enumerate(labels):
                            #     try:
                            #         html = label.get_attribute("outerHTML")
                            #         logger.info(f"cell[{idx}] HTML: {html}")
                            #     except Exception as ex:
                            #         logger.warning(f"Could not get HTML for cell[{idx}]: {ex}")
                            if len(labels) >= 2:
                                label = labels[0].text.strip().lower()
                                odds_text = labels[1].text.strip()
                                logger.info(f"label {label}")
                                logger.info(f"odds_text {odds_text}")

                                if outcome == label:
                                    try:
                                        return cell, float(odds_text)
                                    except Exception:
                                        return cell, None
                except Exception:
                    continue
            return None, None
            
        except Exception as e:
            logger.error(f"Error finding DNB outcome: {e}")
            return None, None

    def __find_basketball_moneyline_outcome(self, outcome, is_first_half=False):
        """
        Find the basketball moneyline outcome element for sportybet.
        Full game: prefer "Match Result (OT)" then "Match winner", fallback "Match Result (No OT)".
        First half: use "1st Half Winner" (same page for basketball).
        
        Parameters:
        - outcome: 'home', 'draw', or 'away'
        - is_first_half: whether to target 1st-half winner market
        
        Returns:
        - Tuple of (button_element, odds) or (None, None) if not found
        """
        try:
            logger.info(f"Finding basketball moneyline outcome for {('1st Half ' if is_first_half else 'Full Game ')}{outcome}")
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")

            # Priority order of headers
            if is_first_half:
                target_headers = ["1st Half Winner"]
            else:
                target_headers = ["Match Result (OT)", "Match Result (No OT)"]

            moneyline_market_div = None
            for header_choice in target_headers:
                for market_div in event_markets:
                    try:
                        header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                        header_text = header.text.strip()
                        if header_choice.lower() in header_text.lower():
                            moneyline_market_div = market_div
                            logger.info(f"Found basketball moneyline market: {header_text}")
                            break
                    except Exception:
                        continue
                if moneyline_market_div:
                    break

            if not moneyline_market_div:
                logger.warning("No basketball moneyline market found")
                return None, None

            cells = moneyline_market_div.find_elements(By.CSS_SELECTOR, ".event-market__cell")
            if len(cells) < 2:
                logger.warning(f"Expected at least 2 cells for basketball moneyline, found {len(cells)}")
                return None, None

            # Determine outcome index based on number of cells
            if len(cells) == 3:
                outcome_index = {"home": 0, "draw": 1, "away": 2}
            else:
                outcome_index = {"home": 0, "away": 1}

            if outcome not in outcome_index:
                logger.error(f"Invalid basketball moneyline outcome for available cells: {outcome}")
                return None, None

            target_cell = cells[outcome_index[outcome]]
            button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")

            try:
                odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                odds_text = odds_element.text.strip()
                logger.info(f"Found basketball moneyline {outcome} with odds: {float(odds_text)}")
                return button, float(odds_text)
            except Exception as e:
                logger.error(f"Could not find odds in basketball moneyline outcome: {e}")
                return None, None
        except Exception as e:
            logger.error(f"Error finding basketball moneyline outcome: {e}")
            return None, None

    def __find_basketball_total_outcome(self, target_points, outcome, is_first_half=False):
        """
        Find the basketball total points outcome element for sportybet
        For basketball, first-half totals are not targeted; skip when is_first_half is True.
        Looks for "Total Points" market for full game totals.
        
        Parameters:
        - target_points: The points value to find
        - outcome: 'over' or 'under'
        - is_first_half: if True, skip search and return None
        
        Returns:
        - Element or None if not found
        """
        try:
            if is_first_half:
                logger.info("Skipping basketball 1st-half totals per strategy")
                return None, None

            logger.info(f"Finding basketball total outcome for {outcome} {target_points}")
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get all event-market divs and find the one with "Total Points"
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            
            totals_market_div = None
            for market_div in event_markets:
                try:
                    # Check if this market has "Total Points" in the header
                    header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                    header_text = header.text.strip()
                    
                    if "Total Points" in header_text:
                        totals_market_div = market_div
                        logger.info(f"Found basketball totals market: {header_text}")
                        break
                        
                except Exception:
                    # This market doesn't have the expected structure, continue to next
                    continue
            
            if not totals_market_div:
                logger.warning("No basketball totals market found")
                return None, None
            
            # Get all event-market__row divs within this totals market
            rows = totals_market_div.find_elements(By.CSS_SELECTOR, ".event-market__row")
            
            for row in rows:
                try:
                    # Each row has 2 cells: first for over, second for under
                    cells = row.find_elements(By.CSS_SELECTOR, ".event-market__cell")
                    
                    if len(cells) < 2:
                        logger.warning(f"Expected 2 cells for basketball totals row, found {len(cells)}")
                        continue
                    
                    # Check if this row has the target points by looking at cell titles
                    target_cell = None
                    found_points = False
                    
                    for cell in cells:
                        try:
                            # Get the cell title (e.g., "Over 231.5" or "Under 231.5")
                            title_element = cell.find_element(By.CSS_SELECTOR, ".event-market__cell-title")
                            title_text = title_element.text.strip()
                            
                            # Extract points from title (e.g., "Over 231.5" -> 231.5)
                            import re
                            points_match = re.search(r'(\d+\.?\d*)', title_text)
                            if points_match:
                                cell_points = float(points_match.group(1))
                                
                                # Check if this cell matches our target points and outcome
                                if abs(cell_points - float(target_points)) < 0.01:  # Allow small floating point differences
                                    # Check if the outcome matches (over/under)
                                    if (outcome == "over" and "Over" in title_text) or (outcome == "under" and "Under" in title_text):
                                        target_cell = cell
                                        found_points = True
                                        logger.info(f"Found basketball total {outcome} {target_points} in: {title_text}")
                                        break
                                        
                        except Exception:
                            # Cell doesn't have expected structure, continue to next
                            continue
                    
                    if found_points and target_cell:
                        break
                        
                except Exception:
                    # Row doesn't have expected structure, continue to next
                    continue
            
            if not target_cell:
                logger.warning(f"Could not find basketball total {outcome} {target_points}")
                return None, None
            
            # Get the button inside this cell
            try:
                button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                
                # Verify odds
                try:
                    odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                    odds_text = odds_element.text.strip()
                    logger.info(f"Found basketball total {outcome} {target_points} with odds: {float(odds_text)}")
                    return button, float(odds_text)
                except Exception as e:
                    logger.error(f"Could not find odds in basketball total outcome: {e}")
                    return None, None
            except Exception as e:
                logger.error(f"Error finding basketball total outcome: {e}")
                return None, None
                
        except Exception as e:
            logger.error(f"Error finding basketball total outcome: {e}")
            return None, None

    def __find_basketball_handicap_outcome(self, target_points, outcome, home_team, away_team, is_first_half=False):
        """
        Find the basketball handicap outcome element for sportybet
        Searches both "Handicap - Rolling Middle Line" and "Game Handicap" for full game,
        and "1st Half Handicap - Rolling Middle Line" for first-half bets.
        
        Parameters:
        - target_points: The handicap value to find
        - outcome: 'home' or 'away'
        - home_team: Name of the home team
        - away_team: Name of the away team
        - is_first_half: whether the bet is for 1st half
        
        Returns:
        - Element or None if not found
        """
        try:
            logger.info(f"Finding basketball handicap outcome for {outcome} {target_points} (1H={is_first_half})")
            # Get the active market group div
            market_group = self.driver.find_element(By.CSS_SELECTOR, ".event-details__market-group.event-details__market-group--active")
            
            # Get all event-market divs and find the one with the proper handicap header
            event_markets = market_group.find_elements(By.CSS_SELECTOR, ".event-market")
            
            target_headers = [
                "1st Half Handicap - Rolling Middle Line",
                "1st Half Handicap"
            ] if is_first_half else [
                "Handicap - Rolling Middle Line",
                "Game Handicap",
                "Handicap"
            ]
            
            # Collect candidate handicap market divs in priority order and try each until found
            candidate_market_divs = []
            seen_ids = set()
            for target in target_headers:
                for market_div in event_markets:
                    try:
                        header = market_div.find_element(By.CSS_SELECTOR, ".event-market__header span.event-market__name")
                        header_text = header.text.strip()
                        logger.info(f"header----- {header_text}")
                        if target.lower() in header_text.lower():
                            # Use element id to avoid duplicates across headers
                            el_id = id(market_div)
                            if el_id not in seen_ids:
                                seen_ids.add(el_id)
                                candidate_market_divs.append(market_div)
                                logger.info(f"Queued basketball handicap market: {header_text}")
                    except Exception:
                        continue
            
            if not candidate_market_divs:
                logger.warning("No basketball handicap market found for the selected period")
                return None, None
            
            target_cell = None
            found_handicap = False
            
            for handicap_market_div in candidate_market_divs:
                try:
                    # Get all event-market__row divs within this handicap market
                    rows = handicap_market_div.find_elements(By.CSS_SELECTOR, ".event-market__row")
                    
                    for row in rows:
                        try:
                            # Each row has 2 cells: first for home, second for away
                            cells = row.find_elements(By.CSS_SELECTOR, ".event-market__cell")
                            
                            if len(cells) < 2:
                                logger.warning(f"Expected 2 cells for basketball handicap row, found {len(cells)}")
                                continue
                            
                            for cell in cells:
                                try:
                                    title_element = cell.find_element(By.CSS_SELECTOR, ".event-market__cell-title")
                                    title_text = title_element.text.strip()
                                    
                                    import re
                                    handicap_match = re.search(r'([+-]?\d+\.?\d*)', title_text)
                                    if handicap_match:
                                        cell_handicap = float(handicap_match.group(1))
                                        
                                        if abs(cell_handicap - float(target_points)) < 0.01:
                                            is_home_cell = False
                                            if home_team and home_team.lower() in title_text.lower():
                                                is_home_cell = True
                                            elif away_team and away_team.lower() in title_text.lower():
                                                is_home_cell = False
                                            else:
                                                is_home_cell = (cells.index(cell) == 0)
                                            
                                            if (outcome == "home" and is_home_cell) or (outcome == "away" and not is_home_cell):
                                                target_cell = cell
                                                found_handicap = True
                                                logger.info(f"Found basketball handicap {outcome} {target_points} in: {title_text}")
                                                break
                                except Exception:
                                    continue
                            
                            if found_handicap and target_cell:
                                break
                        except Exception:
                            continue
                    
                    if found_handicap and target_cell:
                        break
                except Exception:
                    continue
            
            if not target_cell:
                logger.warning(f"Could not find basketball handicap {outcome} {target_points} in any handicap market div")
                return None, None
            
            # Get the button inside this cell
            try:
                button = target_cell.find_element(By.CSS_SELECTOR, "button.odds-button")
                
                # Verify odds
                try:
                    odds_element = button.find_element(By.CSS_SELECTOR, ".odds-button__price span")
                    odds_text = odds_element.text.strip()
                    logger.info(f"Found basketball handicap {outcome} {target_points} with odds: {float(odds_text)}")
                    return button, float(odds_text)
                except Exception as e:
                    logger.error(f"Could not find odds in basketball handicap outcome: {e}")
                    return None, None
            except Exception as e:
                logger.error(f"Error finding basketball handicap outcome: {e}")
                return None, None
                
        except Exception as e:
            logger.error(f"Error finding basketball handicap outcome: {e}")
            return None, None

        

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

            available_accounts = [account for account in self.__accounts if account.can_place_bet()]
            logger.info(f"Available accounts: {[a.username for a in available_accounts]}")
            
            def _place_for_account(account):
                logger.info(f"Checking account {account.username}")
                success = False
                try:
                    account.increment_bets()
                    self._current_shaped_data = bet_data["shaped_data"]
                    profile_base = os.path.join(os.getcwd(), "profiles")
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", account.username) if account and account.username else "default"
                    profile_path = os.path.join(profile_base, safe_name)
                    opener = WebsiteOpener(headless=self.__headless, proxy=account.proxy, config_file="config.json", profile_path=profile_path)
                    old_driver = getattr(self, 'driver', None)
                    self.driver = opener.driver
                    try:
                        success = self.__place_bet_with_selenium(
                            account,
                            self.__generate_sportybet_bet_url(bet_data["event_details"]),
                            bet_data["market_type"],
                            bet_data["outcome"],
                            bet_data["odds"],
                            bet_data["stake"],
                            bet_data["shaped_data"]["category"]["meta"].get("value"),
                            bet_data.get("is_first_half", False),
                            bet_data["shaped_data"]["game"]["home"],
                            bet_data["shaped_data"]["game"]["away"],
                            bet_data.get("sport_id", 1)
                        )
                    finally:
                        try:
                            if hasattr(self, 'driver') and self.driver:
                                self.driver.quit()
                        except Exception:
                            pass
                        self.driver = old_driver
                except Exception as e:
                    logger.error(f"Error placing bet for {account.username}: {e}")
                finally:
                    try:
                        account.decrement_bets()
                    except Exception:
                        pass
                return success
            
            if available_accounts:
                max_workers = min(max_total_bets, len(available_accounts))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_place_for_account, account): account for account in available_accounts}
                    for future in as_completed(futures):
                        try:
                            if future.result():
                                any_bet_placed = True
                                logger.info(f"Bet placed successfully with account {futures[future].username}")
                        except Exception as e:
                            logger.error(f"Worker error for {futures[future].username}: {e}")
            else:
                for account in self.__accounts:
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
        logger.info(f"fetching latest pinnacle odds for event id {event_id}")
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
            # try:
            #     ts = time.strftime("%Y%m%d-%H%M%S")
            #     fname = f"pinnacle_latest_odds_{re.sub(r'[^A-Za-z0-9_.-]','_', str(event_id))}_{ts}.json"
            #     with open(fname, "w") as f:
            #         json.dump(event_data, f)
            #     logger.info(f"Wrote Pinnacle latest odds response to {fname}")
            # except Exception:
            #     pass
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
            
            if line_type in ("spread", "total") and points is None:
                logger.info("Points not provided for line type requiring points; skipping latest odds fetch")
                return None
            
            if line_type == "money_line":
                money_line = period.get("money_line", {})
                if money_line:  # Check if money_line data exists
                    try:
                        val = money_line.get("home")
                        if val is not None:
                            decimal_prices["home"] = float(val)
                    except (ValueError, TypeError):
                        pass
                    try:
                        val = money_line.get("away")
                        if val is not None:
                            decimal_prices["away"] = float(val)
                    except (ValueError, TypeError):
                        pass
                    try:
                        val = money_line.get("draw")
                        if val is not None:
                            decimal_prices["draw"] = float(val)
                    except (ValueError, TypeError):
                        pass
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
                        try:
                            val = exact_spread.get("home")
                            if val is not None:
                                decimal_prices["home"] = float(val)
                        except (ValueError, TypeError):
                            pass
                        try:
                            val = exact_spread.get("away")
                            if val is not None:
                                decimal_prices["away"] = float(val)
                        except (ValueError, TypeError):
                            pass
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
                        try:
                            val = exact_total.get("over")
                            if val is not None:
                                decimal_prices["home"] = float(val)  # Over as home
                        except (ValueError, TypeError):
                            pass
                        try:
                            val = exact_total.get("under")
                            if val is not None:
                                decimal_prices["away"] = float(val)  # Under as away
                        except (ValueError, TypeError):
                            pass
                    else:
                        logger.info(f"No exact total match found for points: {points}")
                else:
                    logger.info("No totals data found in period")
            
            return decimal_prices if decimal_prices else None
            
        except Exception as e:
            logger.error(f"Error fetching latest odds: {e}")
            return None

    def __fetch_pinnacle_points_for_event(self, event_id, period_key):
        """
        Fetch available Pinnacle points for totals and spreads for a specific event/period.
        Returns a dict with keys 'totals' and 'spreads'.
        """
        logger.info(f"fetching available pinnacle points for event id {event_id}")
        if not event_id:
            logger.info("No event ID provided, cannot fetch available points")
            return {"totals": [], "spreads": []}

        pinnacle_api_host = os.getenv("PINNACLE_HOST")
        if not pinnacle_api_host:
            logger.info("Pinnacle Events API host not configured")
            return {"totals": [], "spreads": []}

        try:
            url = f"{pinnacle_api_host}/events/{event_id}"
            logger.info(f"Fetching available Pinnacle points from: {url}")

            response = requests.get(url)
            if response.status_code != 200:
                logger.info(f"Failed to fetch available points: HTTP {response.status_code}")
                return {"totals": [], "spreads": []}

            event_data = response.json()
            if not event_data or "data" not in event_data or not event_data["data"]:
                logger.info("No data returned from Pinnacle API for available points")
                return {"totals": [], "spreads": []}

            if event_data["data"] is None or event_data["data"] == "null":
                return {"totals": [], "spreads": []}

            periods = event_data["data"].get("periods", {}) or {}
            period = periods.get(period_key, {}) if periods else {}
            if not period:
                logger.info(f"No period data found for period key (points): {period_key}")
                return {"totals": [], "spreads": []}

            totals_points = []
            spreads_points = []

            totals = period.get("totals", {}) or {}
            for _, total_data in totals.items():
                try:
                    p = float(total_data.get("points"))
                    totals_points.append(p)
                except (TypeError, ValueError):
                    continue

            spreads = period.get("spreads", {}) or {}
            for _, spread_data in spreads.items():
                try:
                    p = float(spread_data.get("hdp"))
                    spreads_points.append(p)
                except (TypeError, ValueError):
                    continue

            # Deduplicate and sort
            totals_points = sorted({round(p, 2) for p in totals_points})
            spreads_points = sorted({round(p, 2) for p in spreads_points})

            logger.info(f"Available Pinnacle points for period {period_key}: totals={totals_points}, spreads={spreads_points}")
            return {"totals": totals_points, "spreads": spreads_points}

        except Exception as e:
            logger.error(f"Error fetching available Pinnacle points: {e}")
            return {"totals": [], "spreads": []}

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
        - bet_odds: The decimal odds offered by sportybet
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
    
    def __map_asian_handicap_to_sportybet(self, points):
        """
        Map Pinnacle Asian Handicap values to sportybet regular handicap format
        
        Asian handicaps with .5 are mapped to whole numbers by removing the decimal:
        -2.5 → -2, -1.5 → -1, -0.5 → 0, +0.5 → +1, +1.5 → +2, etc.
        
        Parameters:
        - points: Asian handicap value from Pinnacle
        
        Returns:
        - Mapped handicap value for sportybet
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
        sport_info = event_details.get("sport") or {}
        sport_name = (sport_info.get("name") or "").strip().lower()
        sport_id = sport_info.get("id") or ""
        
        # Generate game ID for outcome tracking
        game_id = self.__generate_game_id(home_team, away_team)
        
        # Identify if this event is basketball
        is_basketball = (sport_name == "basketball" or sport_id in ("2", "sr:sport:2"))
        
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
                        # Check if sporty odds exceed maximum allowed
                        if odds > self.__max_pinnacle_odds:
                            logger.info(f"Sporty odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
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
            
            # Strategy: skip 1st-half totals for basketball
            if is_basketball and is_first_half:
                logger.info("Skipping basketball 1st-half totals during EV scan")
                continue

            # Determine candidate total points from Pinnacle when basketball; fallback to defaults
            if is_basketball:
                event_id = shaped_data.get("eventId")
                period_key = "num_1" if is_first_half else "num_0"
                points_info = self.__fetch_pinnacle_points_for_event(event_id, period_key) or {}
                candidate_points = points_info.get("totals") or []
                logger.info(f"Pinnacle totals points for {home_team} vs {away_team} (1st Half: {is_first_half}): {candidate_points}")
                if not candidate_points:
                    logger.info("No Pinnacle totals points available; using default small totals")
                    candidate_points = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
            else:
                candidate_points = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7]
            
            for outcome in ["over", "under"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "total", outcome):
                    continue
                
                for points in candidate_points:
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
                            # Check if sportybet odds exceed maximum allowed
                            if odds > self.__max_pinnacle_odds:
                                logger.info(f"sportybet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                                continue
                            
                            # Calculate stake for this specific market
                            stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                            available_markets.append(("total", outcome, odds, actual_points, ev, is_first_half, stake))
                            
                            # Track this found outcome to avoid checking opposite outcomes
                            self.__add_found_outcome(game_id, "total", outcome)
        
        # Check Asian Handicap markets (with mapping to sportybet regular handicap)
        for is_first_half in [False, True]:
            period_suffix = " (1st Half)" if is_first_half else ""
            logger.info(f"\033[1m\033[1;36mChecking handicap markets{period_suffix} for {home_team} vs {away_team}\033[0m")
            # logger.info(f"Checking handicap markets{period_suffix} for {home_team} vs {away_team}")
            
            for outcome in ["home", "away"]:
                # Skip if we already found the opposite outcome
                if self.__should_skip_outcome(game_id, "spread", outcome):
                    continue
                    
                # Determine handicap points from Pinnacle for basketball; fallback to defaults
                if is_basketball:
                    event_id = shaped_data.get("eventId")
                    period_key = "num_1" if is_first_half else "num_0"
                    points_info = self.__fetch_pinnacle_points_for_event(event_id, period_key) or {}
                    base_points = points_info.get("spreads") or []
                    logger.info(f"Pinnacle spread points for {home_team} vs {away_team} (1st Half: {is_first_half}): {base_points}")
                    if not base_points:
                        logger.info("No Pinnacle spread points available; using default scan points")
                        base_points = [0.5, 1.5, 2.5, 3.5, 4.5]
                    # Expand to both negative and positive to match sportybet sides
                    candidate_points = sorted({round(float(p), 2) for p in base_points} | {round(-float(p), 2) for p in base_points})
                else:
                    candidate_points = [-5.5, -5, -4.5, -4, -3.5, -3, -2.5,-2, -1.5, -1, 0.5,1, 1.5, 2,2.5,3, 3.5,4, 4.5, 5.5]

                for points in candidate_points:
                    # Map Pinnacle Asian Handicap to sportybet regular handicap (skip mapping for basketball)
                    sportybet_points = points if is_basketball else self.__map_asian_handicap_to_sportybet(points)
                    logger.info(f"sportybet points: {sportybet_points}")
                    bet_code, odds, actual_points = self.__find_market_bet_code_with_points(
                        event_details, "spread", sportybet_points, outcome, is_first_half, sport_id, home_team, away_team
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
                            # Check if sportybet odds exceed maximum allowed
                            if odds > self.__max_pinnacle_odds:
                                logger.info(f"sportybet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                                continue
                            
                            # Calculate stake for this specific market
                            stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                            # Store the sportybet points for actual betting, but use Pinnacle points for EV display
                            available_markets.append(("spread", outcome, odds, sportybet_points, ev, is_first_half, stake))
                            
                            # Track this found outcome to avoid checking opposite outcomes
                            self.__add_found_outcome(game_id, "spread", outcome)
        
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
                        # Check if sportybet odds exceed maximum allowed
                        if odds > self.__max_pinnacle_odds:
                            logger.info(f"sportybet odds {odds:.2f} exceeds maximum allowed {self.__max_pinnacle_odds:.2f}, skipping bet")
                            continue
                        
                        # Calculate stake for this specific market
                        stake = self.__calculate_stake_for_market(odds, modified_shaped_data, self.__config["bet_settings"]["bankroll"])
                        available_markets.append(("spread", outcome, odds, 0.0, ev, is_first_half, stake))
                        
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
            
            # Step 1: Search for the event on sportybet
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
                    logger.info(f"Placing bet: {market_type}{period_suffix}, points: {points} - {outcome} with odds {odds} (EV: {ev:.2f}%)")
                    
                    # Create modified shaped data for this specific market
                    modified_shaped_data = shaped_data.copy()
                    modified_shaped_data["category"]["type"] = market_type
                    modified_shaped_data["category"]["meta"]["team"] = outcome
                    if points is not None:
                        modified_shaped_data["category"]["meta"]["value"] = points
                    if is_first_half:
                        modified_shaped_data["periodNumber"] = "1"
                    
                    # Check for duplicate bet before placing
                    logging.info(f"event details here: {event_details} ")
                    # Use primary event ID first, fallback to backup ID if missing
                    event_id = event_details.get("eventId") or event_details.get("id") or "unknown"
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
        Find the appropriate bet code in the sportybet event details and return the adjusted points value
        
        Parameters:
        - event_details: The event details from sportybet
        - line_type: The type of bet (spread, moneyline, total)
        - points: The points value for the bet
        - outcome: The outcome (home, away, draw, over, under)
        - is_first_half: Whether the bet is for the first half
        - sport_id: The sport ID (1 for soccer, 3 for basketball)
        
        Returns:
        - Tuple of (bet_code, odds, adjusted_points)
        """
        sport_info = event_details.get("sport") or {}
        sport_name = (sport_info.get("name") or "").strip().lower()
        is_basketball = sport_name == "basketball" or sport_id in ("2", "sr:sport:2")
        logger.info(f"Finding market for Game: {home_team} vs {away_team}: {line_type} - {outcome} - {points} - First Half: {is_first_half} - Sport: {'Basketball' if is_basketball else 'Football'}")
        markets_sp = event_details.get("markets") or []
        if markets_sp:
            fh_keys = ("first half", "1st half", "half-time", "halftime", "half time", "fh", "ht")
            filtered_markets = []
            for _m in markets_sp:
                _n = (_m.get("name") or _m.get("desc") or "").strip().lower()
                _g = (_m.get("group") or "").strip().lower()
                _t = (_m.get("title") or "").strip().lower()
                _s = f"{_n} {_g} {_t}"
                _has_half = any(k in _s for k in fh_keys)
                if is_first_half and not _has_half:
                    continue
                if not is_first_half and _has_half:
                    continue
                filtered_markets.append(_m)
            mn = ("1x2", "match result", "result")
            tn = ("over/under", "total")
            hn = ("asian handicap",)
            dn = ("draw no bet", "dnb")
            lt = line_type.lower()
            if lt == "money_line":
                for m in filtered_markets:
                    name = (m.get("name")).strip().lower()
                    if (is_basketball and name == "1x2") or name == "1x2" or (is_first_half and name == "1st half - 1x2"):
                        mm = {"home": "home", "away": "away", "draw": "draw"}
                        tgt = mm.get(outcome.lower())
                        for o in m.get("outcomes", []):
                            lbl = (o.get("desc") or "").strip().lower()
                            if lbl == tgt:
                                odds = o.get("odds") or o.get("value")
                                return o.get("id"), float(odds), None
            elif lt == "total":
                rp = float(points) if points is not None else None
                for m in filtered_markets:
                    name = (m.get("name") or "").strip().lower()
                    # Build exact target names based on sport and period
                    if is_basketball:
                        if is_first_half:
                            target = "1st half - total"
                        else:
                            target = "over/under (incl. overtime)"
                    else:
                        if is_first_half:
                            target = "1st half - over/under"
                        else:
                            target = "over/under"
                    if name == target:
                        for o in m.get("outcomes", []):
                            txt = (o.get("desc") or "").strip().lower()
                            mm = re.search(r"(over|under)\s*(\d+\.?\d*)", txt)
                            if mm:
                                side = mm.group(1)
                                pts = float(mm.group(2))
                                print(f"total points gotten {pts}")
                                if side == outcome.lower() and rp is not None and abs(pts - rp) < 0.01:
                                    odds = o.get("odds") or o.get("value")
                                    return o.get("id"), float(odds), pts
            elif lt == "spread":
                # THIS IS DNB
                if points is not None and abs(float(points)) < 0.01:
                    for m in filtered_markets:
                        name = (m.get("desc") or "").strip().lower()
                        if any(k in name for k in dn):
                            for o in m.get("outcomes", []):
                                lbl = (o.get("desc") or "").strip().lower()
                                if outcome.lower() == lbl:
                                    odds = o.get("odds") or o.get("value")
                                    return o.get("id"), float(odds), 0.0
                else:
                    rp = float(points) if points is not None else None
                    for m in filtered_markets:
                        name = (m.get("desc") or "").strip().lower()
                        if any(k in name for k in hn):
                            for o in m.get("outcomes", []):
                                txt = (o.get("desc") or "").strip().lower()
                                sd = txt
                                # if home_team and home_team.lower() in txt:
                                #     sd = "home"
                                # elif away_team and away_team.lower() in txt:
                                #     sd = "away"
                                mm = re.search(r"([+-]?\d+\.?\d*)", txt)
                                if sd == outcome.lower() and mm and rp is not None:
                                    pts = float(mm.group(1))
                                    print(f"asian handicap points gotten {pts}")
                                    if abs(pts - rp) < 0.01:
                                        odds = o.get("odds") or o.get("value")
                                        return o.get("id"), float(odds), pts
            return None, None, None
       
        else:
            logger.info("No markets found in event details")
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
        Place a bet on sportybet
        
        Parameters:
        - event_details: Event details from sportybet
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
            logger.info(f"Placing sportybet bet immediately: {line_type}{period_suffix} - {outcome} with odds {odds}")
            
            # Extract sport_id from event_details.sport
            sport_info = event_details.get("sport") or {}
            sport_id = sport_info.get("id") or ""
            
            logger.info(f"Sport ID: {sport_id}")
            # Create bet data
            bet_data = {
                "event_details": event_details,
                "market_type": line_type,
                "outcome": outcome,
                "odds": odds,
                "shaped_data": modified_shaped_data,
                "is_first_half": is_first_half,
                "stake": stake,  # Include pre-calculated stake
                "sport_id": sport_id,  # Include sport_id for basketball support
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
            logger.info(f"Queueing sportybet bet: {line_type}{period_suffix} - {outcome} with odds {odds}")
            
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
        
        Find the appropriate bet code in the sportybet event details
        
        Parameters:
        - event_details: The event details from sportybet
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
        Public method to search for an event on sportybet
        
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
        Public method to get detailed information about an event from sportybet
        
        Parameters:
        - event_id: The event ID to get details for
        
        Returns:
        - Event details dictionary or None if not found
        """
        return self.__get_event_details(event_id)
    
    def generate_sportybet_bet_url(self, event_details):
        """
        Public method to generate sportybet betting URL based on event details
        
        Parameters:
        - event_details: Event details dictionary
        
        Returns:
        - Betting URL string or None if generation fails
        """
        return self.__generate_sportybet_bet_url(event_details)
    
    def find_market_bet_code_with_points(self, event_details, line_type, points, outcome, is_first_half=False, sport_id=1, home_team=None, away_team=None):
        """
        Public method to find the appropriate bet code in the sportybet event details
        
        Parameters:
        - event_details: The event details from sportybet
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
            bet_url = self.generate_sportybet_bet_url(event_details)
            
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
            # time.sleep(5)
            
            # Test the new selector system
            market_element = self.__get_market_selector(line_type, outcome, points, is_first_half=False, sport_id=sport_id)
            
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
        - bet_odds: The decimal odds offered by sportybet
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
        - bet_odds: The decimal odds offered by sportybet
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
        - bet_odds: The decimal odds offered by Sportybet
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
