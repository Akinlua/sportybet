#!/usr/bin/env python3
"""
Simple test script for testing event search functionality.
"""

import json
import logging
from bet_engine import BetEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_event_search():
    """Test the event search functionality"""
    logger.info("🚀 Testing Event Search Functionality")
    
    try:
        # Load config
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        # Initialize BetEngine (skip login since we only need search)
        bet_engine = BetEngine(config, skip_initial_login=True)
        logger.info("✅ BetEngine initialized")
        
        # Check proxy configuration
        if config.get("use_proxies", False):
            logger.info("🔒 Proxy usage is enabled in config")
            if config.get("accounts"):
                proxy_count = sum(1 for acc in config["accounts"] if acc.get("proxy"))
                logger.info(f"📡 Found {proxy_count} accounts with proxy configuration")
        else:
            logger.info("🌐 Proxy usage is disabled in config")
        
        # Test cases
        test_cases = [
            {
                "home_team": "NAC Breda",
                "away_team": "AZ Alkmaar",
                "description": "Dutch Eredivisie match"
            },
            {
                "home_team": "Manchester United",
                "away_team": "Liverpool",
                "description": "Premier League classic"
            },
            {
                "home_team": "Real Madrid",
                "away_team": "Barcelona",
                "description": "El Clasico"
            }
        ]
        
        logger.info(f"📋 Testing {len(test_cases)} search cases...")
        
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"\n🎯 Test Case {i}: {test_case['description']}")
            logger.info(f"Searching for: {test_case['home_team']} vs {test_case['away_team']}")
            
            try:
                # Call the search function
                event_id = bet_engine._BetEngine__search_event(
                    home_team=test_case['home_team'],
                    away_team=test_case['away_team']
                )
                
                if event_id:
                    logger.info(f"✅ Found event ID: {event_id}")
                    
                    # Optionally get event details
                    try:
                        event_details = bet_engine._BetEngine__get_event_details(event_id)
                        if event_details:
                            logger.info(f"📊 Event details retrieved successfully")
                            logger.info(f"   Event: {event_details.get('homeTeam', 'N/A')} vs {event_details.get('awayTeam', 'N/A')}")
                        else:
                            logger.warning("⚠️ Could not retrieve event details")
                    except Exception as details_error:
                        logger.error(f"❌ Error getting event details: {details_error}")
                else:
                    logger.warning("⚠️ No event found")
                    
            except Exception as search_error:
                logger.error(f"❌ Search failed: {search_error}")
        
        logger.info("\n🏁 Event search testing completed!")
        
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
    test_event_search()
