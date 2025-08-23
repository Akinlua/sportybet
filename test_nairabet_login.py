import os
import sys
import argparse
import json
import time

from bet_engine import BetEngine


def main():
    parser = argparse.ArgumentParser(description="Test Nairabet login for a configured account")
    parser.add_argument("--account-index", type=int, default=0, help="Index of the account in config/env to test")
    parser.add_argument("--headless", type=str, default=os.getenv("ENVIRONMENT", "development") == "production", help="Run browser in headless mode (true/false)")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    args = parser.parse_args()

    headless_flag = str(args.headless).lower() in ("1", "true", "yes", "y")

    print("Initializing BetEngine...")
    engine = BetEngine(headless=headless_flag, config_file=args.config, skip_initial_login=True)

    try:
        # Access the accounts list prepared during initialization
        accounts = getattr(engine, f"_BetEngine__accounts", [])
        if not accounts:
            print("No accounts found. Ensure NAIRABET_USERNAME/NAIRABET_PASSWORD env vars or accounts in config.json.")
            sys.exit(1)

        if args.account_index < 0 or args.account_index >= len(accounts):
            print(f"Invalid --account-index {args.account_index}. Available: 0..{len(accounts)-1}")
            sys.exit(1)

        account = accounts[args.account_index]
        print(f"Attempting login for account: {account.username}")

        # Call the private login method via name-mangling
        do_login = getattr(engine, f"_BetEngine__do_login_for_account")
        success = do_login(account)

        print(f"Login success: {success}")
        print(f"Cookies set: {bool(account.cookie_jar)}")
        print(f"Balance: {account.balance}")

        # Optionally re-fetch balance to verify cookies via API
        fetch_balance = getattr(engine, f"_BetEngine__fetch_account_balance")
        refreshed_balance = fetch_balance(account)
        print(f"Refreshed balance via API: {refreshed_balance}")

    except Exception as e:
        print(f"Login test failed: {e}")
        raise
    finally:
        # Always cleanup browser
        try:
            engine.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main() 