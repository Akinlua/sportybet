#!/usr/bin/env python3
"""
Test script to verify first half market handling in Nairabet API
"""

import json

# Sample event details with market groups
sample_event = {
    "id": "15351054",
    "eventNames": ["Lincoln FC", "SC Braga"],  # Array format
    "marketGroups": [
        {
            "name": "Main",
            "markets": [
                {
                    "id": "1x2",
                    "name": "1x2",
                    "outcomes": [
                        {"id": "HOME", "name": "Lincoln FC", "value": "17.00"},
                        {"id": "DRAW", "name": "Draw", "value": "7.00"},
                        {"id": "AWAY", "name": "SC Braga", "value": "1.14"}
                    ]
                }
            ]
        },
        {
            "name": "1st Half",
            "markets": [
                {
                    "id": "FH1X2",
                    "name": "First Half Win/Draw/Win",
                    "outcomes": [
                        {"id": "HOME", "name": "Lincoln FC", "value": "11.00"},
                        {"id": "DRAW", "name": "Draw", "value": "2.90"},
                        {"id": "AWAY", "name": "SC Braga", "value": "1.48"}
                    ]
                },
                {
                    "id": "HTGOU_LS",
                    "name": "Half time Goals - Under/Over",
                    "outcomes": [
                        {"id": "UNDER", "name": "Under 0.5", "value": "3.70"},
                        {"id": "OVER", "name": "Over 0.5", "value": "1.22"}
                    ]
                }
            ]
        }
    ]
}

# Test data for search response format
search_response_data = [
    {
        "id": "15393747",
        "eventNames": ["Karlbergs BK v IK Brage Borlange"],  # Single string format with "v"
        "startTime": 1755619200000
    },
    {
        "id": "15351054", 
        "eventNames": ["Lincoln FC", "SC Braga"],  # Array format
        "startTime": 1755802800000
    }
]

def test_event_names_parsing():
    """Test event names parsing for both formats"""
    print("=== Testing Event Names Parsing ===")
    
    for event in search_response_data:
        print(f"\nEvent ID: {event['id']}")
        event_names = event.get("eventNames", [])
        
        # Handle both array format and single string format
        if isinstance(event_names, list) and len(event_names) >= 2:
            # Array format: ["Team A", "Team B"]
            home_team_name = event_names[0].lower()
            away_team_name = event_names[1].lower()
            print(f"  Array format: {home_team_name} vs {away_team_name}")
        elif isinstance(event_names, list) and len(event_names) == 1:
            # Single string format: ["Team A v Team B"]
            team_string = event_names[0]
            if " v " in team_string:
                parts = team_string.split(" v ")
                if len(parts) == 2:
                    home_team_name = parts[0].strip().lower()
                    away_team_name = parts[1].strip().lower()
                    print(f"  Single string format: {home_team_name} vs {away_team_name}")
                else:
                    print(f"  Invalid single string format: {team_string}")
            else:
                print(f"  No 'v' separator found: {team_string}")
        else:
            print(f"  Invalid format: {event_names}")

def test_time_comparison():
    """Test time comparison logic"""
    print("\n=== Testing Time Comparison ===")
    
    # Test with millisecond timestamps
    pinnacle_time = 1755619200000  # Example Pinnacle time in milliseconds
    nairabet_time = 1755619200000  # Same time in milliseconds
    
    time_diff_hours = abs(int(pinnacle_time) - nairabet_time) / (1000 * 60 * 60)
    print(f"Pinnacle time: {pinnacle_time}")
    print(f"Nairabet time: {nairabet_time}")
    print(f"Time difference: {time_diff_hours:.2f} hours")
    
    if time_diff_hours <= 1.0833:  # Within 1 hour and 5 minutes
        print("✅ Time match found!")
    else:
        print("❌ Time difference too large")
    
    # Test with different times
    nairabet_time_2 = 1755619200000 + (30 * 60 * 1000)  # 30 minutes later
    time_diff_hours_2 = abs(int(pinnacle_time) - nairabet_time_2) / (1000 * 60 * 60)
    print(f"\nNairabet time 2: {nairabet_time_2}")
    print(f"Time difference 2: {time_diff_hours_2:.2f} hours")
    
    if time_diff_hours_2 <= 1.0833:
        print("✅ Time match found!")
    else:
        print("❌ Time difference too large")

def test_market_extraction():
    """Test market extraction logic"""
    print("\n=== Testing Market Extraction ===")
    
    # Simulate the market extraction logic
    all_markets = []
    first_half_markets = []
    
    for group in sample_event.get("marketGroups", []):
        group_name = group.get("name", "").lower()
        group_markets = group.get("markets", [])
        
        # Check if this is a first half group
        if "1st half" in group_name or "first half" in group_name:
            first_half_markets.extend(group_markets)
            print(f"Found first half group: {group.get('name')} with {len(group_markets)} markets")
        else:
            all_markets.extend(group_markets)
            print(f"Found main group: {group.get('name')} with {len(group_markets)} markets")
    
    print(f"\nTotal markets: {len(all_markets)}")
    print(f"First half markets: {len(first_half_markets)}")
    
    # Test first half market finding
    print("\n=== Testing First Half Market Finding ===")
    
    # Simulate looking for FH1X2 market
    target_market_id = "FH1X2"
    found_market = None
    
    for market in first_half_markets:
        if market.get("id") == target_market_id:
            found_market = market
            break
    
    if found_market:
        print(f"Found first half market: {found_market.get('name')}")
        print(f"Market ID: {found_market.get('id')}")
        print(f"Outcomes: {len(found_market.get('outcomes', []))}")
        
        # Test outcome finding
        target_outcome = "HOME"
        for outcome in found_market.get("outcomes", []):
            if outcome.get("id") == target_outcome:
                print(f"Found {target_outcome} outcome with odds: {outcome.get('value')}")
                break
    else:
        print(f"Market {target_market_id} not found in first half markets")
    
    # Test total goals market finding
    print("\n=== Testing Total Goals Market Finding ===")
    
    target_market_id = "HTGOU_LS"
    found_market = None
    
    for market in first_half_markets:
        if market.get("id") == target_market_id:
            found_market = market
            break
    
    if found_market:
        print(f"Found total goals market: {found_market.get('name')}")
        print(f"Market ID: {found_market.get('id')}")
        print(f"Outcomes: {len(found_market.get('outcomes', []))}")
        
        # Test outcome finding
        target_outcome = "OVER"
        for outcome in found_market.get("outcomes", []):
            if outcome.get("id") == target_outcome:
                print(f"Found {target_outcome} outcome with odds: {outcome.get('value')}")
                break
    else:
        print(f"Market {target_market_id} not found in first half markets")

if __name__ == "__main__":
    test_event_names_parsing()
    test_time_comparison()
    test_market_extraction() 