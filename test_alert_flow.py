#!/usr/bin/env python3
"""
Test script for Nairabet alert flow and bet placement.
This script creates dummy alerts to test the complete betting pipeline.
"""

import json
import time
import random
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_dummy_alert(home_team, away_team, line_type, outcome, points=None, sport_id=1, period_number="0"):
    """
    Create a dummy alert that mimics what would come from Pinnacle
    
    Parameters:
    - home_team: Name of home team
    - away_team: Name of away team  
    - line_type: Type of bet ("moneyline", "total", "spread")
    - outcome: Outcome to bet on ("home", "away", "draw", "over", "under")
    - points: Points value for totals/spreads
    - sport_id: Sport ID (1 for soccer, 3 for basketball)
    - period_number: "0" for full match, "1" for first half
    
    Returns:
    - Dictionary formatted as Pinnacle alert
    """
    # Generate realistic start time (next few hours)
    start_time = datetime.now() + timedelta(hours=random.randint(1, 24))
    start_time_str = start_time.isoformat() + "Z"
    
    alert = {
        "home": home_team,
        "away": away_team,
        "lineType": line_type,
        "outcome": outcome,
        "sportId": sport_id,
        "type": "live" if random.choice([True, False]) else "prematch",
        "periodNumber": period_number,
        "eventId": random.randint(10000000, 99999999),
        "starts": start_time_str
    }
    
    # Add points for totals and spreads
    if points is not None:
        alert["points"] = points
    
    return alert

def test_moneyline_alerts():
    """Test moneyline (1X2) alerts"""
    logger.info("=== Testing Moneyline Alerts ===")
    
    alerts = [
        # Premier League matches
        create_dummy_alert("Manchester City", "Liverpool", "moneyline", "home"),
        create_dummy_alert("Arsenal", "Chelsea", "moneyline", "away"),
        create_dummy_alert("Tottenham", "Manchester United", "moneyline", "draw"),
        
        # Championship matches
        create_dummy_alert("Leeds United", "Leicester City", "moneyline", "home"),
        create_dummy_alert("Norwich City", "West Bromwich Albion", "moneyline", "away"),
        
        # First half moneyline
        create_dummy_alert("Burnley", "Sheffield United", "moneyline", "home", period_number="1"),
    ]
    
    return alerts

def test_total_alerts():
    """Test over/under total alerts"""
    logger.info("=== Testing Total Alerts ===")
    
    alerts = [
        # Common totals
        create_dummy_alert("Barcelona", "Real Madrid", "total", "over", points=2.5),
        create_dummy_alert("Bayern Munich", "Borussia Dortmund", "total", "under", points=3.5),
        create_dummy_alert("PSG", "Marseille", "total", "over", points=1.5),
        create_dummy_alert("Juventus", "AC Milan", "total", "under", points=4.5),
        
        # First half totals
        create_dummy_alert("Inter Milan", "Napoli", "total", "over", points=1.5, period_number="1"),
        create_dummy_alert("AS Roma", "Lazio", "total", "under", points=0.5, period_number="1"),
    ]
    
    return alerts

def test_handicap_alerts():
    """Test Asian handicap alerts"""
    logger.info("=== Testing Handicap Alerts ===")
    
    alerts = [
        # Positive handicaps
        create_dummy_alert("Brighton", "Crystal Palace", "spread", "home", points=0.5),
        create_dummy_alert("Brentford", "Fulham", "spread", "away", points=1.0),
        create_dummy_alert("Southampton", "Everton", "spread", "home", points=1.5),
        
        # Negative handicaps  
        create_dummy_alert("Manchester City", "Sheffield Wednesday", "spread", "home", points=-1.5),
        create_dummy_alert("Liverpool", "Luton Town", "spread", "home", points=-2.5),
        create_dummy_alert("Arsenal", "Bournemouth", "spread", "away", points=-1.0),
        
        # First half handicaps
        create_dummy_alert("Chelsea", "Brighton", "spread", "home", points=-0.5, period_number="1"),
        create_dummy_alert("Tottenham", "Aston Villa", "spread", "away", points=1.5, period_number="1"),
    ]
    
    return alerts

def test_mixed_sports_alerts():
    """Test alerts for different sports"""
    logger.info("=== Testing Mixed Sports Alerts ===")
    
    alerts = [
        # Basketball (sport_id=3)
        create_dummy_alert("Lakers", "Warriors", "moneyline", "home", sport_id=3),
        create_dummy_alert("Celtics", "Heat", "total", "over", points=220.5, sport_id=3),
        create_dummy_alert("Nuggets", "Suns", "spread", "home", points=-5.5, sport_id=3),
        
        # More soccer with different leagues
        create_dummy_alert("Real Betis", "Sevilla", "moneyline", "away"),
        create_dummy_alert("Atletico Madrid", "Valencia", "total", "under", points=2.5),
    ]
    
    return alerts

def test_edge_case_alerts():
    """Test edge cases and special scenarios"""
    logger.info("=== Testing Edge Case Alerts ===")
    
    alerts = [
        # Zero handicap (should trigger DNB)
        create_dummy_alert("Everton", "Nottingham Forest", "spread", "home", points=0.0),
        create_dummy_alert("Wolves", "Ipswich Town", "spread", "away", points=0.0),
        
        # Very high/low totals
        create_dummy_alert("Watford", "Millwall", "total", "over", points=5.5),
        create_dummy_alert("Reading", "Coventry City", "total", "under", points=0.5),
        
        # Large handicaps
        create_dummy_alert("Manchester City", "Macclesfield Town", "spread", "home", points=-3.5),
        create_dummy_alert("Salford City", "Manchester United", "spread", "away", points=4.5),
    ]
    
    return alerts

def simulate_alert_processing(bet_engine, alerts, delay_between_alerts=2):
    """
    Simulate processing alerts through the bet engine
    
    Parameters:
    - bet_engine: Instance of BetEngine
    - alerts: List of alert dictionaries
    - delay_between_alerts: Seconds to wait between processing alerts
    """
    logger.info(f"Starting to process {len(alerts)} alerts...")
    
    successful_alerts = 0
    failed_alerts = 0
    
    for i, alert in enumerate(alerts, 1):
        try:
            logger.info(f"\n--- Processing Alert {i}/{len(alerts)} ---")
            logger.info(f"Alert: {alert['home']} vs {alert['away']} - {alert['lineType']} {alert['outcome']}")
            if alert.get('points'):
                logger.info(f"Points: {alert['points']}")
            if alert.get('periodNumber') == "1":
                logger.info("Period: First Half")
            
            # Shape the alert data (same as OddsEngine does)
            shaped_data = shape_alert_data(alert)
            
            if shaped_data:
                # Send to bet engine for processing
                bet_engine.notify(shaped_data)
                successful_alerts += 1
                logger.info(f"✅ Alert {i} processed successfully")
            else:
                logger.error(f"❌ Failed to shape alert {i}")
                failed_alerts += 1
            
            # Wait before next alert
            if i < len(alerts):
                logger.info(f"Waiting {delay_between_alerts} seconds before next alert...")
                time.sleep(delay_between_alerts)
                
        except Exception as e:
            logger.error(f"❌ Error processing alert {i}: {e}")
            failed_alerts += 1
            import traceback
            traceback.print_exc()
    
    logger.info(f"\n=== Alert Processing Summary ===")
    logger.info(f"Total alerts: {len(alerts)}")
    logger.info(f"Successful: {successful_alerts}")
    logger.info(f"Failed: {failed_alerts}")
    logger.info(f"Success rate: {(successful_alerts/len(alerts)*100):.1f}%")

def shape_alert_data(alert):
    """
    Transform alert data from test format to BetEngine format
    (Mimics the OddsEngine.__shape_alert_data function)
    """
    try:
        shaped_data = {
            "game": {
                "home": alert.get("home", ""),
                "away": alert.get("away", ""),
            },
            "category": {
                "type": alert.get("lineType", ""),
                "meta": {
                   "value": alert.get("points"),
                   "team": alert.get("outcome"), 
                   "value_of_under_over": None,
                }   
            },
            "match_type": alert.get("type", ""),
            "periodNumber": alert.get("periodNumber", "0"),
            "eventId": alert.get("eventId"),
            "starts": alert.get("starts"),
            "sportId": alert.get("sportId", 1)
        }
        
        return shaped_data
    except Exception as e:
        logger.error(f"Error shaping alert data: {e}")
        return None

def create_test_suite():
    """Create a comprehensive test suite of alerts"""
    all_alerts = []
    
    # Add different types of alerts
    all_alerts.extend(test_moneyline_alerts())
    all_alerts.extend(test_total_alerts())
    all_alerts.extend(test_handicap_alerts())
    all_alerts.extend(test_mixed_sports_alerts())
    all_alerts.extend(test_edge_case_alerts())
    
    # Shuffle alerts to simulate real-world randomness
    random.shuffle(all_alerts)
    
    return all_alerts

def main():
    """Main test execution"""
    logger.info("🚀 Starting Nairabet Alert Flow Test")
    
    try:
        # Import and initialize BetEngine
        from bet_engine import BetEngine
        
        # Load configuration
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        # Initialize bet engine
        bet_engine = BetEngine(config)
        logger.info("✅ BetEngine initialized successfully")
        
        # Create test suite
        test_alerts = create_test_suite()
        logger.info(f"✅ Created {len(test_alerts)} test alerts")
        
        # Option to run subset of tests
        print(f"\nTest options:")
        print(f"1. Run all {len(test_alerts)} alerts")
        print(f"2. Run first 5 alerts only")
        print(f"3. Run moneyline alerts only")
        print(f"4. Run total alerts only")
        print(f"5. Run handicap alerts only")
        print(f"6. Run edge case alerts only")
        
        choice = input("\nEnter your choice (1-6): ").strip()
        
        if choice == "2":
            test_alerts = test_alerts[:5]
        elif choice == "3":
            test_alerts = test_moneyline_alerts()
        elif choice == "4":
            test_alerts = test_total_alerts()
        elif choice == "5":
            test_alerts = test_handicap_alerts()
        elif choice == "6":
            test_alerts = test_edge_case_alerts()
        
        # Ask for delay between alerts
        delay = input(f"\nEnter delay between alerts in seconds (default 3): ").strip()
        delay = int(delay) if delay.isdigit() else 3
        
        # Start processing
        logger.info(f"\n🎯 Running {len(test_alerts)} alerts with {delay}s delay between each")
        simulate_alert_processing(bet_engine, test_alerts, delay)
        
        logger.info("🏁 Alert flow test completed!")
        
    except KeyboardInterrupt:
        logger.info("\n⏹️ Test interrupted by user")
    except FileNotFoundError:
        logger.error("❌ config.json not found. Please ensure config file exists.")
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            if 'bet_engine' in locals():
                bet_engine.cleanup()
                logger.info("✅ BetEngine cleaned up")
        except:
            pass

if __name__ == "__main__":
    main()
