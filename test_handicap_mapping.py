#!/usr/bin/env python3
"""
Test script specifically for Asian Handicap to Nairabet regular handicap mapping.
Verifies the conversion logic matches the expected POD/Nairabet mapping.
"""

import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_handicap_mapping():
    """Test the handicap mapping function with known values"""
    
    # Import the mapping function
    try:
        from bet_engine import BetEngine
        import json
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        bet_engine = BetEngine(config)
        mapping_func = bet_engine._BetEngine__map_asian_handicap_to_nairabet
        
    except Exception as e:
        logger.error(f"Failed to import mapping function: {e}")
        return False
    
    # Test cases based on the POD/Nairabet mapping image
    test_cases = [
        # (Pinnacle Asian, Expected Nairabet)
        (0.5, 1),    # +0.5 → +1
        (1.5, 2),    # +1.5 → +2  
        (2.5, 3),    # +2.5 → +3
        (-1.5, -1),  # -1.5 → -1
        (-2.5, -2),  # -2.5 → -2
        (-3.5, -3),  # -3.5 → -3
        (-0.5, 0),   # -0.5 → 0 (becomes DNB)
        
        # Whole numbers should stay the same
        (1.0, 1),    # +1 → +1
        (2.0, 2),    # +2 → +2
        (3.0, 3),    # +3 → +3
        (-1.0, -1),  # -1 → -1
        (-2.0, -2),  # -2 → -2
        (-3.0, -3),  # -3 → -3
        (0.0, 0),    # 0 → 0 (DNB)
    ]
    
    logger.info("🧪 Testing Asian Handicap to Nairabet Mapping")
    logger.info("=" * 50)
    
    passed = 0
    failed = 0
    
    for pinnacle_value, expected_nairabet in test_cases:
        try:
            actual_nairabet = mapping_func(pinnacle_value)
            
            if actual_nairabet == expected_nairabet:
                logger.info(f"✅ {pinnacle_value:+5.1f} → {actual_nairabet:+2d} (Expected: {expected_nairabet:+2d})")
                passed += 1
            else:
                logger.error(f"❌ {pinnacle_value:+5.1f} → {actual_nairabet:+2d} (Expected: {expected_nairabet:+2d})")
                failed += 1
                
        except Exception as e:
            logger.error(f"❌ {pinnacle_value:+5.1f} → ERROR: {e}")
            failed += 1
    
    logger.info("=" * 50)
    logger.info(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        logger.info("🎉 All handicap mapping tests passed!")
        return True
    else:
        logger.error(f"💥 {failed} tests failed!")
        return False

def test_dnb_detection():
    """Test detection of when handicap should become DNB (Draw No Bet)"""
    logger.info("\n🧪 Testing DNB Detection (Zero Handicaps)")
    logger.info("=" * 40)
    
    try:
        from bet_engine import BetEngine
        import json
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        bet_engine = BetEngine(config)
        mapping_func = bet_engine._BetEngine__map_asian_handicap_to_nairabet
        
    except Exception as e:
        logger.error(f"Failed to import mapping function: {e}")
        return False
    
    # Values that should become DNB (map to 0)
    dnb_values = [-0.5, 0.0]
    
    for value in dnb_values:
        mapped = mapping_func(value)
        if mapped == 0:
            logger.info(f"✅ {value:+4.1f} → 0 (DNB) ✓")
        else:
            logger.error(f"❌ {value:+4.1f} → {mapped} (Expected: 0 for DNB)")
            return False
    
    logger.info("🎉 DNB detection tests passed!")
    return True

def create_comprehensive_test_alerts():
    """Create test alerts using the mapping to verify full flow"""
    logger.info("\n🧪 Creating Test Alerts with Mapping")
    logger.info("=" * 45)
    
    from datetime import datetime, timedelta
    
    start_time = (datetime.now() + timedelta(hours=2)).isoformat() + "Z"
    
    test_alerts = [
        {
            "name": "Asian -2.5 → Nairabet -2",
            "alert": {
                "home": "Manchester City",
                "away": "Sheffield Wednesday", 
                "lineType": "spread",
                "outcome": "home",
                "points": -2.5,  # Should map to -2
                "sportId": 1,
                "type": "prematch",
                "periodNumber": "0",
                "eventId": 12345678,
                "starts": start_time
            }
        },
        {
            "name": "Asian +1.5 → Nairabet +2",
            "alert": {
                "home": "Brighton",
                "away": "Manchester City",
                "lineType": "spread", 
                "outcome": "home",
                "points": 1.5,  # Should map to +2
                "sportId": 1,
                "type": "prematch",
                "periodNumber": "0",
                "eventId": 12345679,
                "starts": start_time
            }
        },
        {
            "name": "Asian -0.5 → DNB",
            "alert": {
                "home": "Arsenal",
                "away": "Chelsea",
                "lineType": "spread",
                "outcome": "home", 
                "points": -0.5,  # Should map to 0 (DNB)
                "sportId": 1,
                "type": "prematch",
                "periodNumber": "0",
                "eventId": 12345680,
                "starts": start_time
            }
        }
    ]
    
    for test in test_alerts:
        alert = test["alert"]
        logger.info(f"📝 {test['name']}")
        logger.info(f"   {alert['home']} vs {alert['away']}")
        logger.info(f"   Handicap: {alert['points']:+.1f} ({alert['outcome']})")
        
    return test_alerts

def main():
    """Main test execution"""
    logger.info("🚀 Handicap Mapping Test Suite")
    
    try:
        # Test basic mapping
        mapping_success = test_handicap_mapping()
        
        # Test DNB detection
        dnb_success = test_dnb_detection()
        
        # Show example test alerts
        test_alerts = create_comprehensive_test_alerts()
        
        # Overall result
        if mapping_success and dnb_success:
            logger.info("\n🎉 All mapping tests passed!")
            logger.info("✅ Handicap mapping is working correctly")
            logger.info("✅ DNB detection is working correctly")
            
            # Option to run actual bet tests
            run_bets = input("\nRun actual bet tests with these mappings? (y/n): ").strip().lower()
            if run_bets == 'y':
                logger.info("🎯 Running actual bet placement tests...")
                
                from bet_engine import BetEngine
                import json
                
                with open('config.json', 'r') as f:
                    config = json.load(f)
                
                bet_engine = BetEngine(config)
                
                def shape_alert_data(alert):
                    return {
                        "game": {
                            "home": alert["home"],
                            "away": alert["away"],
                        },
                        "category": {
                            "type": alert["lineType"],
                            "meta": {
                               "value": alert.get("points"),
                               "team": alert["outcome"], 
                               "value_of_under_over": None,
                            }   
                        },
                        "match_type": alert["type"],
                        "periodNumber": alert["periodNumber"],
                        "eventId": alert["eventId"],
                        "starts": alert["starts"],
                        "sportId": alert["sportId"]
                    }
                
                for test in test_alerts:
                    logger.info(f"\n🎯 Testing: {test['name']}")
                    try:
                        shaped_data = shape_alert_data(test["alert"])
                        bet_engine.notify(shaped_data)
                        logger.info("✅ Test completed")
                    except Exception as e:
                        logger.error(f"❌ Test failed: {e}")
                
                bet_engine.cleanup()
            
        else:
            logger.error("💥 Some mapping tests failed!")
            return False
            
    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    main()
