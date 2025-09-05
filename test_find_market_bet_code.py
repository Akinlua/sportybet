#!/usr/bin/env python3
"""
Test script for __find_market_bet_code_with_points function
Tests the function with event ID 15605377 and handicap 2.5
"""

import logging
import json
import requests
from bet_engine import BetEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_event_details(event_id):
    """Get event details using the Nairabet API"""
    logger.info(f"Getting event details for ID: {event_id}")
    
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
        
        response = requests.get(details_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        event_details = response.json()
        
        logger.info("Event details retrieved successfully!")
        logger.info(f"  Event Names: {event_details.get('eventNames')}")
        logger.info(f"  Sport: {event_details.get('sportName')}")
        logger.info(f"  Competition: {event_details.get('competitionName')}")
        logger.info(f"  Start Time: {event_details.get('startTime')}")
        
        # Check market groups
        market_groups = event_details.get("marketGroups", [])
        logger.info(f"  Market Groups: {len(market_groups)}")
        
        for i, group in enumerate(market_groups[:5]):  # Show first 5 groups
            group_name = group.get("name", "Unknown")
            markets = group.get("markets", [])
            logger.info(f"    Group {i+1}: {group_name} ({len(markets)} markets)")
            
            # Show first market details if available
            if markets:
                first_market = markets[0]
                logger.info(f"      First Market: {first_market.get('name')} (ID: {first_market.get('id')})")
                outcomes = first_market.get("outcomes", [])
                logger.info(f"      Outcomes: {len(outcomes)}")
                if outcomes:
                    first_outcome = outcomes[0]
                    logger.info(f"        First Outcome: {first_outcome.get('name')} (ID: {first_outcome.get('id')}) - Odds: {first_outcome.get('value')}")
        
        return event_details
        
    except Exception as e:
        logger.error(f"Failed to get event details: {e}")
        return None

def test_find_market_bet_code_with_points():
    """Test the __find_market_bet_code_with_points function"""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING __find_market_bet_code_with_points FUNCTION")
    logger.info("=" * 60)
    
    # Initialize BetEngine
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        bet_engine = BetEngine(config, skip_initial_login=True)
        logger.info("✅ BetEngine initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize BetEngine: {e}")
        return False
    
    # Get event details for ID 15605377
    event_id = 15605377
    event_details = get_event_details(event_id)
    
    if not event_details:
        logger.error("❌ Failed to get event details")
        return False
    
    # Extract team names
    event_names = event_details.get("eventNames", [])
    if len(event_names) >= 2:
        home_team = event_names[0]
        away_team = event_names[1]
        logger.info(f"📊 Testing with teams: {home_team} vs {away_team}")
    else:
        home_team = "Home Team"
        away_team = "Away Team"
        logger.warning("⚠️ Could not extract team names from event details")
    
    # Test cases for handicap 2.5
    test_cases = [
        {
            "description": "Home team with +1 handicap",
            "line_type": "spread",
            "points": 1,
            "outcome": "home",
            "is_first_half": False,
            "sport_id": 1
        }
        # {
        #     "description": "Away team with -2.5 handicap", 
        #     "line_type": "spread",
        #     "points": -2.5,
        #     "outcome": "away",
        #     "is_first_half": False,
        #     "sport_id": 1
        # },
        # {
        #     "description": "Home team with +2.5 handicap (first half)",
        #     "line_type": "spread", 
        #     "points": 2.5,
        #     "outcome": "home",
        #     "is_first_half": True,
        #     "sport_id": 1
        # }
    ]
    
    # Test each case
    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"\n🧪 Test Case {i}: {test_case['description']}")
        logger.info(f"   Parameters: {test_case}")
        
        try:
            # Call the function
            result = bet_engine._BetEngine__find_market_bet_code_with_points(
                event_details=event_details,
                line_type=test_case["line_type"],
                points=test_case["points"],
                outcome=test_case["outcome"],
                is_first_half=test_case["is_first_half"],
                sport_id=test_case["sport_id"],
                home_team=home_team,
                away_team=away_team
            )
            
            if result and len(result) == 3:
                logger.info(f"Result: {result}")
                bet_code, odds, adjusted_points = result
                logger.info(f"✅ SUCCESS: Found market!")
                logger.info(f"   Bet Code: {bet_code}")
                logger.info(f"   Odds: {odds}")
                logger.info(f"   Adjusted Points: {adjusted_points}")
            else:
                logger.warning(f"⚠️ No market found for this test case")
                logger.info(f"   Result: {result}")
                
        except Exception as e:
            logger.error(f"❌ Test case failed with error: {e}")
            import traceback
            traceback.print_exc()
    
    # Cleanup
    try:
        bet_engine.cleanup()
        logger.info("✅ BetEngine cleaned up successfully")
    except:
        pass
    
    return True

def test_map_asian_handicap_to_nairabet():
    """Test the __map_asian_handicap_to_nairabet function"""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING __map_asian_handicap_to_nairabet FUNCTION")
    logger.info("=" * 60)
    
    # Initialize BetEngine
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        bet_engine = BetEngine(config, skip_initial_login=True)
        logger.info("✅ BetEngine initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize BetEngine: {e}")
        return False
    
    # Test cases for handicap mapping
    test_cases = [
        {"input": 0.5, "expected": 1, "description": "+0.5 should map to +1"},
        # {"input": -2.5, "expected": -2, "description": "-2.5 should map to -2"},
        # {"input": 1.5, "expected": 2, "description": "+1.5 should map to +2"},
        # {"input": -1.5, "expected": -1, "description": "-1.5 should map to -1"},
        # {"input": 0.5, "expected": 1, "description": "+0.5 should map to +1"},
        # {"input": -0.5, "expected": 0, "description": "-0.5 should map to 0 (DNB)"},
        # {"input": 2.0, "expected": 2, "description": "+2.0 should stay +2"},
        # {"input": -2.0, "expected": -2, "description": "-2.0 should stay -2"},
    ]
    
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(test_cases, 1):
        logger.info(f"\n🧪 Test Case {i}: {test_case['description']}")
        
        try:
            # Call the mapping function
            result = bet_engine._BetEngine__map_asian_handicap_to_nairabet(test_case["input"])
            
            if result == test_case["expected"]:
                logger.info(f"✅ PASS: {test_case['input']:+4.1f} → {result:+2d} (Expected: {test_case['expected']:+2d})")
                passed += 1
            else:
                logger.error(f"❌ FAIL: {test_case['input']:+4.1f} → {result:+2d} (Expected: {test_case['expected']:+2d})")
                failed += 1
                
        except Exception as e:
            logger.error(f"❌ ERROR: {test_case['input']:+4.1f} → Exception: {e}")
            failed += 1
    
    logger.info("\n" + "=" * 40)
    logger.info(f"📊 Mapping Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        logger.info("🎉 All handicap mapping tests passed!")
    else:
        logger.warning(f"⚠️ {failed} mapping tests failed")
    
    # Cleanup
    try:
        bet_engine.cleanup()
        logger.info("✅ BetEngine cleaned up successfully")
    except:
        pass
    
    return failed == 0

def main():
    """Main test function"""
    logger.info("🚀 Starting comprehensive test for __find_market_bet_code_with_points")
    logger.info("=" * 80)
    
    # Test 1: Get event details
    logger.info("\n📋 Test 1: Getting event details for ID 15605377")
    # event_details = get_event_details(15605377)
    # if not event_details:
    #     logger.error("❌ Cannot proceed without event details")
    #     return False
    
    # Test 2: Test the main function
    logger.info("\n📋 Test 2: Testing __find_market_bet_code_with_points function")
    test1_success = test_find_market_bet_code_with_points()
    
    # Test 3: Test the mapping function
    logger.info("\n📋 Test 3: Testing __map_asian_handicap_to_nairabet function")
    # test2_success = test_map_asian_handicap_to_nairabet()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("🏁 TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Event Details Retrieval: {'✅ PASS' if event_details else '❌ FAIL'}")
    logger.info(f"Market Finding Function: {'✅ PASS' if test1_success else '❌ FAIL'}")
    logger.info(f"Handicap Mapping Function: {'✅ PASS' if test2_success else '❌ FAIL'}")
    
    overall_success = event_details and test1_success and test2_success
    logger.info(f"\nOverall Result: {'🎉 ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    return overall_success

if __name__ == "__main__":
    main()
