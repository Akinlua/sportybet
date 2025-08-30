#!/usr/bin/env python3
"""
Simple test script for testing individual bet placements.
Quick way to test specific scenarios without running full alert flow.
"""

import json
import logging
from datetime import datetime, timedelta

# Setup logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger("test_single_bet")

logger = logging.getLogger('nairabet_betting')
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

def create_quick_alert(home_team, away_team, line_type, outcome, points=None, is_first_half=False):
    """
    Create a quick test alert for immediate testing
    """
    start_time = (datetime.now() + timedelta(hours=2)).isoformat() + "Z"
    
    alert = {
        "home": home_team,
        "away": away_team,
        "lineType": line_type,
        "outcome": outcome,
        "sportId": 1,  # Soccer
        "type": "prematch",
        "periodNumber": "1" if is_first_half else "0",
        "eventId": 15465549,
        "starts": 1756651500000
    }
    
    if points is not None:
        alert["points"] = points
    
    return alert

def shape_alert_data(alert):
    """Transform alert to BetEngine format"""
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
        "sportId": alert["sportId"],
        "stake": 50
    }

def test_quick_scenarios():
    """Pre-defined quick test scenarios"""
    scenarios = {
        "1": {
            "name": "Moneyline Home Win",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "moneyline", "home")
        },
        "2": {
            "name": "Over 3.5 Goals",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "total", "over", points=3.5)
        },
        "3": {
            "name": "Handicap +2",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "spread", "home", points=2)
        },
        "4": {
            "name": "First Half Under 1.5",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "total", "under", points=1.5, is_first_half=True)
        },
        "5": {
            "name": "DNB (Zero Handicap)",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "spread", "home", points=0.0)
        },
        "6": {
            "name": "Asian Handicap -2.5 (maps to -2)",
            "alert": create_quick_alert("NAC Breda", "AZ Alkmaar", "spread", "home", points=-2.5)
        }
    }
    
    return scenarios

def run_single_test(bet_engine, alert_data, scenario_name):
    """Run a single bet test - directly place bet without odds checking"""
    logger.info(f"\n🎯 Testing: {scenario_name}")
    logger.info(f"Match: {alert_data['home']} vs {alert_data['away']}")
    logger.info(f"Bet: {alert_data['lineType']} - {alert_data['outcome']}")
    if alert_data.get('points'):
        logger.info(f"Points: {alert_data['points']}")
    if alert_data.get('periodNumber') == "1":
        logger.info("Period: First Half")
    
    try:
        # Shape data for bet engine
        shaped_data = shape_alert_data(alert_data)
        
        # Create mock event details (since we're bypassing Pinnacle lookup)
        event_details = {
            "home": alert_data['home'],
            "away": alert_data['away'],
            "event_id": alert_data.get('eventId', 15446589),
            "starts": alert_data.get('starts', 1756321200000),
            "sport_id": alert_data.get('sportId', 1)
        }
        
        # Mock odds (you can adjust these test values)
        test_odds = 1.69  # Default test odds
        
        # Extract bet parameters
        line_type = alert_data['lineType']
        outcome = alert_data['outcome']
        is_first_half = alert_data.get('periodNumber') == "1"
        
        # Map line types to expected format
        if line_type == "moneyline":
            mapped_line_type = "money_line"
        elif line_type == "total":
            mapped_line_type = "total"
        elif line_type == "spread":
            mapped_line_type = "spread"
        else:
            mapped_line_type = line_type
        
        logger.info(f"🎯 Placing bet directly: {mapped_line_type} - {outcome} @ {test_odds}")
        
        # Call __place_bet directly (bypassing Pinnacle odds check)
        result = bet_engine._BetEngine__place_bet(
            event_details=event_details,
            line_type=mapped_line_type,
            outcome=outcome,
            odds=test_odds,
            modified_shaped_data=shaped_data,
            is_first_half=is_first_half,
            stake=50  # Let bet engine calculate stake
        )
        
        if result:
            logger.info("✅ Test completed successfully")
        else:
            logger.error("❌ Bet placement failed")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main execution"""
    logger.info("🚀 Single Bet Test Script")
    
    try:
        # Import and setup
        from bet_engine import BetEngine
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        bet_engine = BetEngine(config, skip_initial_login=True)
        logger.info("✅ BetEngine initialized")
        
        # Show available scenarios
        scenarios = test_quick_scenarios()
        
        print("\n📋 Available Test Scenarios:")
        for key, scenario in scenarios.items():
            alert = scenario["alert"]
            points_info = f" ({alert['points']})" if alert.get('points') else ""
            period_info = " [1st Half]" if alert.get('periodNumber') == "1" else ""
            print(f"  {key}. {scenario['name']}{points_info}{period_info}")
            print(f"     {alert['home']} vs {alert['away']}")
        
        print(f"  7. Custom bet (enter details manually)")
        print(f"  8. Run all scenarios")
        
        choice = input("\nEnter your choice (1-8): ").strip()
        
        if choice in scenarios:
            # Run single scenario
            scenario = scenarios[choice]
            success = run_single_test(bet_engine, scenario["alert"], scenario["name"])
            
        elif choice == "7":
            # Custom bet
            print("\n📝 Custom Bet Setup:")
            home = input("Home team: ").strip()
            away = input("Away team: ").strip()
            
            print("Bet types: moneyline, total, spread")
            bet_type = input("Bet type: ").strip()
            
            if bet_type == "moneyline":
                print("Outcomes: home, away, draw")
                outcome = input("Outcome: ").strip()
                points = None
            elif bet_type == "total":
                print("Outcomes: over, under")
                outcome = input("Outcome: ").strip()
                points = float(input("Points (e.g., 2.5): ").strip())
            elif bet_type == "spread":
                print("Outcomes: home, away")
                outcome = input("Outcome: ").strip()
                points = float(input("Points (e.g., -1.5): ").strip())
            else:
                logger.error("Invalid bet type")
                return
            
            is_first_half = input("First half? (y/n): ").strip().lower() == 'y'
            
            custom_alert = create_quick_alert(home, away, bet_type, outcome, points, is_first_half)
            success = run_single_test(bet_engine, custom_alert, "Custom Bet")
            
        elif choice == "8":
            # Run all scenarios
            logger.info(f"\n🎯 Running all {len(scenarios)} scenarios...")
            successes = 0
            
            for key, scenario in scenarios.items():
                success = run_single_test(bet_engine, scenario["alert"], scenario["name"])
                if success:
                    successes += 1
                
                # Small delay between tests
                import time
                time.sleep(2)
            
            logger.info(f"\n📊 Results: {successes}/{len(scenarios)} scenarios successful")
            
        else:
            logger.error("Invalid choice")
            return
        
        logger.info("🏁 Test completed!")
        
    except KeyboardInterrupt:
        logger.info("\n⏹️ Test interrupted by user")
    except FileNotFoundError:
        logger.error("❌ config.json not found")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if 'bet_engine' in locals():
                bet_engine.cleanup()
        except:
            pass

if __name__ == "__main__":
    main()
