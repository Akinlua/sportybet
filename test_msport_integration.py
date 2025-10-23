#!/usr/bin/env python3
"""
Test script for MSport bet engine integration
Tests both login functionality and bet placement
"""

import os
import json
import time
import logging
from bet_engine import BetEngine

# Set up logging for tests
def setup_test_logging():
    """Set up structured logging for the test suite"""
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # File handlers for different components
    test_handler = logging.FileHandler('logs/tests.log')
    test_handler.setLevel(logging.INFO)
    test_handler.setFormatter(detailed_formatter)
    
    error_handler = logging.FileHandler('logs/errors.log')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    
    # Create loggers
    test_logger = logging.getLogger('tests')
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(test_handler)
    test_logger.addHandler(console_handler)
    
    error_logger = logging.getLogger('test_errors')
    error_logger.setLevel(logging.ERROR)
    error_logger.addHandler(error_handler)
    error_logger.addHandler(console_handler)
    
    return test_logger, error_logger

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Initialize loggers
test_logger, error_logger = setup_test_logging()

def test_login():
    """Test login functionality"""
    test_logger.info("=" * 50)
    test_logger.info("TESTING MSPORT LOGIN")
    test_logger.info("=" * 50)
    
    # Initialize bet engine
    bet_engine = BetEngine(
        headless=False,  # Set to False to see browser actions
        config_file="config.json"
    )
    
    try:
        # Test login for first account
        if bet_engine._BetEngine__accounts:
            account = bet_engine._BetEngine__accounts[0]
            test_logger.info(f"Testing login for account: {account.username}")
            
            login_success = bet_engine._BetEngine__do_login_for_account(account)
            
            if login_success:
                test_logger.info("✅ Login successful!")
                return True
            else:
                test_logger.info("❌ Login failed!")
                return False
        else:
            test_logger.info("❌ No accounts configured in config.json")
            return False
            
    except Exception as e:
        error_logger.error(f"❌ Login test failed with error: {e}")
        return False
    finally:
        # Cleanup
        bet_engine.cleanup()

def test_event_search():
    """Test event search functionality"""
    test_logger.info("\n" + "=" * 50)
    test_logger.info("TESTING EVENT SEARCH")
    test_logger.info("=" * 50)
    
    bet_engine = BetEngine(
        config_file="config.json",
        skip_initial_login=True
    )
    
    try:
        # Test search with sample teams
        home_team = "Harem Spor Kulubu"
        away_team = "Darussafaka"
        
        test_logger.info(f"Searching for event: {home_team} vs {away_team}")
        event_id = bet_engine.search_event(home_team, away_team)
        
        if event_id:
            test_logger.info(f"✅ Event found! Event ID: {event_id}")
            
            # Test getting event details
            test_logger.info("Getting event details...")
            event_details = bet_engine.get_event_details(event_id)
            
            if event_details:
                test_logger.info(f"✅ Event details retrieved!")
                test_logger.info(f"Event: {event_details.get('homeTeam')} vs {event_details.get('awayTeam')}")
                test_logger.info(f"Markets available: {len(event_details.get('markets', []))}")
                return True, event_details
            else:
                test_logger.info("❌ Failed to get event details")
                print("❌ Failed to get event details")
                return False, None
        else:
            test_logger.info("❌ Event not found!")
            return False, None
            
    except Exception as e:
        error_logger.error(f"❌ Event search failed with error: {e}")
        return False, None
    finally:
        bet_engine.cleanup()

def test_market_finding(event_details):
    """Test market finding functionality"""
    test_logger.info("\n" + "=" * 50)
    test_logger.info("TESTING MARKET FINDING")
    test_logger.info("=" * 50)
    
    bet_engine = BetEngine(config_file="config.json")
    
    try:
        # Test different bet types
        test_cases = [
            {
                "line_type": "money_line",
                "outcome": "home",
                "points": None,
                "description": "Moneyline - Home Win"
            },
            {
                "line_type": "total",
                "outcome": "over",
                "points": "2.5",
                "description": "Total Over 2.5"
            },
            {
                "line_type": "spread",
                "outcome": "home",
                "points": "-0.5",
                "description": "Asian Handicap Home -0.5"
            }
        ]
        
        for test_case in test_cases:
            test_logger.info(f"\nTesting: {test_case['description']}")
            
            outcome_id, odds, adjusted_points = bet_engine.find_market_bet_code_with_points(
                event_details,
                test_case["line_type"],
                test_case["points"],
                test_case["outcome"],
                False,  # is_first_half
                1,      # sport_id (soccer)
                event_details.get('homeTeam'),
                event_details.get('awayTeam')
            )
            
            if outcome_id and odds:
                test_logger.info(f"✅ Market found! Outcome ID: {outcome_id}, Odds: {odds}, Points: {adjusted_points}")
            else:
                test_logger.info(f"❌ Market not found for {test_case['description']}")
        
        return True
        
    except Exception as e:
        error_logger.error(f"❌ Market finding test failed with error: {e}")
        return False

def test_bet_placement():
    """Test complete bet placement flow"""
    print("\n" + "=" * 50)
    print("TESTING BET PLACEMENT FLOW")
    print("=" * 50)
    
    bet_engine = BetEngine(
        config_file="config.json",
        skip_initial_login=True
    )
    
    try:
        # Test data similar to what would come from Pinnacle
        test_shaped_data = {
            "game": {
                "away": "Darussafaka",
                "home": "Harem Spor Kulubu"
            },
            "category": {
                "type": "money_line",
                "meta": {
                    "team": "home"
                }
            },
            "match_type": "oddsDrop",
            "sportId": 1
        }
        
        print("Testing complete bet placement flow...")
        print(f"Test data: {json.dumps(test_shaped_data, indent=2)}")
        
        # This will test the complete flow: search -> get details -> find market -> calculate EV -> place bet
        result = bet_engine.notify(test_shaped_data)
        
        if result:
            print("✅ Bet placement flow completed successfully!")
        else:
            print("❌ Bet placement flow failed (may be due to negative EV or other business logic)")
        
        return True
        
    except Exception as e:
        print(f"❌ Bet placement test failed with error: {e}")
        return False
    finally:
        bet_engine.cleanup()

def test_multi_market_notification():
    """Test multi-market notification logic by simulating a single game alert"""
    print("\n" + "=" * 50)
    print("TESTING MULTI-MARKET NOTIFICATION LOGIC")
    print("=" * 50)
    
    bet_engine = BetEngine(
        config_file="config.json",
        skip_initial_login=True,
    )
    
    try:
        # Simulate a single notification alert for a game
        # This will test the complete flow: search -> get details -> check all markets -> calculate EV -> place bets
        test_shaped_data = {
            "game": {
                "away": "Darussafaka",
                "home": "Harem Spor Kulubu"
            },
            "category": {
                "type": "spread",  # This will be ignored by the new multi-market logic
                "meta": {
                    "team": "home",  # This will be ignored by the new multi-market logic
                    "value": "0"     # This will trigger DNB market instead of handicap
                }
            },
            "match_type": "oddsDrop",
            "sportId": 3,
            "starts": "1754719511000"  # Add start time for unique game ID
        }
        
        print("Simulating notification alert for game...")
        print(f"Test data: {json.dumps(test_shaped_data, indent=2)}")
        
        # This will test the complete multi-market flow:
        # 1. Search for the event
        # 2. Get event details
        # 3. Check ALL available markets (Moneyline, Handicap, DNB, Totals) for both full match and first half
        # 4. Calculate EV for each market
        # 5. Place bets on all markets that meet the min_ev threshold
        result = bet_engine.notify(test_shaped_data)
        
        if result:
            print("✅ Multi-market bet placement completed successfully!")
        else:
            print("❌ Multi-market bet placement failed (may be due to negative EV or other business logic)")
        
        return True
        
    except Exception as e:
        print(f"❌ Multi-market bet placement test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        bet_engine.cleanup()

def test_url_generation():
    """Test MSport betting URL generation"""
    print("\n" + "=" * 50)
    print("TESTING URL GENERATION")
    print("=" * 50)
    
    bet_engine = BetEngine(config_file="config.json", skip_initial_login=True)
    
    try:
        # Sample event details
        event_details = {
            "homeTeam": "Harem Spor Kulubu",
            "awayTeam": "Darussafaka",
            "eventId": "sr:match:58052743"
        }
        
        url = bet_engine.generate_msport_bet_url(event_details)
        expected_pattern = "Harem Spor Kulubu/Darussafaka/sr:match:58052743"
        
        print(f"Generated URL: {url}")
        
        if expected_pattern in url:
            print("✅ URL generation successful!")
            return True
        else:
            print("❌ URL format doesn't match expected pattern")
            return False
            
    except Exception as e:
        print(f"❌ URL generation test failed with error: {e}")
        return False

def main():
    """Run all tests"""
    print("MSport Integration Test Suite")
    print("=" * 50)
    
    # Check if config file exists
    if not os.path.exists("config.json"):
        print("❌ config.json not found! Please create config file with MSport account details.")
        print("Sample config.json structure:")
        print("""{
    "accounts": [
        {
            "username": "your_msport_username",
            "password": "your_msport_password",
            "active": true,
            "balance": 1000
        }
    ]
}""")
        return False
    
    results = []
    
    # Test: Multi-Market Notification Alert (simulates a single game alert)
    # This tests the complete flow: search -> get details -> check all markets -> calculate EV -> place bets
    print("\n🧪 Testing Multi-Market Notification Logic")
    print("This will simulate a single game alert and check ALL available markets")
    results.append(test_multi_market_notification())
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1) 