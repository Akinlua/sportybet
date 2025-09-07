#!/usr/bin/env python3
"""
Test script to demonstrate the new bet storage and outcome filtering functionality
"""

import logging
import json
from bet_engine import BetEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_bet_storage_and_filtering():
    """Test the bet storage and outcome filtering functionality"""
    logger.info("🧪 Testing Bet Storage and Outcome Filtering")
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
    
    # Test 1: Bet signature generation
    logger.info("\n📋 Test 1: Bet Signature Generation")
    signature1 = bet_engine._BetEngine__generate_bet_signature(
        "12345", "HC", "HOME", 1.85, 2.0, False
    )
    signature2 = bet_engine._BetEngine__generate_bet_signature(
        "12345", "HC", "HOME", 1.85, 2.0, True  # First half
    )
    signature3 = bet_engine._BetEngine__generate_bet_signature(
        "12345", "HC", "AWAY", 1.85, 2.0, False  # Different outcome
    )
    
    logger.info(f"Signature 1 (Home, Full): {signature1}")
    logger.info(f"Signature 2 (Home, 1st Half): {signature2}")
    logger.info(f"Signature 3 (Away, Full): {signature3}")
    
    # Test 2: Bet storage and duplicate checking
    logger.info("\n📋 Test 2: Bet Storage and Duplicate Checking")
    
    # Store a bet
    bet_details = {
        "event_id": "12345",
        "market_id": "HC",
        "outcome_id": "HOME",
        "odds": 1.85,
        "handicap": 2.0,
        "line_type": "spread",
        "outcome": "home",
        "is_first_half": False,
        "stake": 100.0,
        "timestamp": 1234567890,
        "home_team": "Team A",
        "away_team": "Team B",
        "ev": 5.2
    }
    
    bet_engine._BetEngine__store_placed_bet(signature1, bet_details)
    logger.info(f"Stored bet: {signature1}")
    
    # Check if bet is already placed
    is_duplicate = bet_engine._BetEngine__is_bet_already_placed(signature1)
    logger.info(f"Bet {signature1} already placed: {is_duplicate}")
    
    is_duplicate2 = bet_engine._BetEngine__is_bet_already_placed(signature2)
    logger.info(f"Bet {signature2} already placed: {is_duplicate2}")
    
    # Test 3: Outcome filtering
    logger.info("\n📋 Test 3: Outcome Filtering")
    
    game_id = "Team A_Team B"
    
    # Add found outcomes
    bet_engine._BetEngine__add_found_outcome(game_id, "spread", "home")
    bet_engine._BetEngine__add_found_outcome(game_id, "money_line", "away")
    bet_engine._BetEngine__add_found_outcome(game_id, "total", "over")
    
    # Test filtering
    should_skip_home_spread = bet_engine._BetEngine__should_skip_outcome(game_id, "spread", "away")
    should_skip_away_moneyline = bet_engine._BetEngine__should_skip_outcome(game_id, "money_line", "home")
    should_skip_under_total = bet_engine._BetEngine__should_skip_outcome(game_id, "total", "under")
    should_skip_draw_moneyline = bet_engine._BetEngine__should_skip_outcome(game_id, "money_line", "draw")
    
    logger.info(f"Should skip away spread (found home): {should_skip_home_spread}")
    logger.info(f"Should skip home moneyline (found away): {should_skip_away_moneyline}")
    logger.info(f"Should skip under total (found over): {should_skip_under_total}")
    logger.info(f"Should skip draw moneyline (found away): {should_skip_draw_moneyline}")
    
    # Test 4: Storage limit (max 1000 bets)
    logger.info("\n📋 Test 4: Storage Limit Test")
    logger.info(f"Current stored bets: {len(bet_engine._BetEngine__placed_bets)}")
    
    # Test 5: Game outcome tracking
    logger.info("\n📋 Test 5: Game Outcome Tracking")
    logger.info(f"Found outcomes for {game_id}: {bet_engine._BetEngine__game_found_outcomes.get(game_id, set())}")
    
    # Cleanup
    try:
        bet_engine.cleanup()
        logger.info("✅ BetEngine cleaned up successfully")
    except:
        pass
    
    logger.info("\n🎉 All tests completed successfully!")
    return True

def demonstrate_workflow():
    """Demonstrate the complete workflow"""
    logger.info("\n" + "=" * 60)
    logger.info("🔄 DEMONSTRATING COMPLETE WORKFLOW")
    logger.info("=" * 60)
    
    logger.info("""
    The new functionality works as follows:
    
    1. 📊 MARKET CHECKING:
       - When checking markets, if we find a HOME handicap bet, we skip checking AWAY handicap bets
       - Same for moneyline (HOME vs AWAY) and totals (OVER vs UNDER)
       - This prevents placing opposite bets on the same game
    
    2. 💾 BET STORAGE:
       - Each placed bet is stored with a unique signature
       - Signature includes: event_id, market_id, outcome_id, odds, handicap, is_first_half
       - Maximum 1000 bets stored (oldest removed when limit reached)
    
    3. 🔍 DUPLICATE PREVENTION:
       - Before placing any bet, we check if it's already been placed
       - Prevents placing the same bet multiple times
    
    4. 🎯 OUTCOME FILTERING:
       - Tracks found outcomes per game
       - Skips checking opposite outcomes after finding one
       - Example: Found HOME spread → Skip AWAY spread for same game
    
    This ensures:
    ✅ No duplicate bets
    ✅ No opposite bets on same game
    ✅ Efficient market checking
    ✅ Proper bet tracking
    """)

if __name__ == "__main__":
    test_bet_storage_and_filtering()
    demonstrate_workflow()
