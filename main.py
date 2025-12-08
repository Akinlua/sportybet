#!/usr/bin/env python3
import os
import signal
import sys
import time
import dotenv
import traceback
from bet_engine import BetEngine
from odds_engine import OddsEngine

def signal_handler(sig, frame):
    """Gracefully shut down when CTRL+C is pressed"""
    print('\nShutting down BetAlert...')
    # Global bet_engine and odds_engine will be cleaned up when exiting
    sys.exit(0)

def main():
    """
    Main entry point for the BetAlert application.
    Initializes the bet and odds engines and starts monitoring for odds alerts.
    Handles errors and gracefully shuts down when interrupted.
    """
    try:
        # Load environment variables
        dotenv.load_dotenv()
        
        print("Starting BetAlert application...")
        
        # Initialize bet engine
        bet_engine = None
        odds_engine = None
        
        try:
            # Initialize bet engine with configuration file
            print("Initializing Bet Engine...")
            bet_engine = BetEngine(
                headless=os.getenv("ENVIRONMENT") == "production",
                config_file="config.json"
            )
            
            # Initialize odds engine with Pinnacle hosts from environment variables
            print("Initializing Odds Engine...")
            odds_engine = OddsEngine(
                bet_engine=bet_engine,
                pinnacle_host=os.getenv("PINNACLE_HOST"),
                pinnacle_api_host=os.getenv("PINNACLE_API_HOST")
            )
            
            # Set up signal handler for graceful shutdown
            signal.signal(signal.SIGINT, signal_handler)
            
            # Start monitoring for odds alerts
            print("Starting odds monitoring...")
            odds_engine.start_monitoring(
                interval=int(os.getenv("ODDS_CHECK_INTERVAL", "30"))
            )
            
            # Keep the main thread running to allow the monitoring to continue
            print("BetAlert running. Press Ctrl+C to exit.")
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\nShutting down BetAlert...")
        except Exception as e:
            print(f"Error in BetAlert: {e}")
            traceback.print_exc()
        finally:
            # Clean up resources
            if odds_engine:
                print("Stopping odds monitoring...")
                odds_engine.stop()
            
            if bet_engine:
                print("Cleaning up browser...")
                bet_engine.cleanup()
                
            print("BetAlert shut down successfully")
            
    except Exception as e:
        print(f"Fatal error in BetAlert: {e}")
        traceback.print_exc()
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
