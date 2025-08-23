#!/usr/bin/env python3
"""
Test script for Nairabet API integration
Tests the search and event details functionality with the new API endpoints
"""

import os
import sys
import json
import requests

def test_search_api():
    """Test the search API endpoint"""
    print("=== Testing Search API ===")
    
    search_url = "https://sports-api.nairabet.com/v2/events/search"
    params = {
        'country': 'NG',
        'group': 'g3',
        'platform': 'desktop',
        'locale': 'en',
        'text': 'Karlbergs'
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nairabet.com/",
        "x-sah-device": "5f40d3154db72f213ffd1fe7f7ad1cb8"
    }
    
    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        search_results = response.json()
        events = search_results.get("data", [])
        
        print(f"Search successful! Found {len(events)} events")
        
        if events:
            print("\nFirst event details:")
            first_event = events[0]
            print(f"  ID: {first_event.get('id')}")
            print(f"  Names: {first_event.get('eventNames')}")
            print(f"  Sport: {first_event.get('sportName')}")
            print(f"  Competition: {first_event.get('competitionName')}")
            print(f"  Start Time: {first_event.get('startTime')}")
            
            return first_event.get('id')
        else:
            print("No events found")
            return None
            
    except Exception as e:
        print(f"Search API test failed: {e}")
        return None

def test_event_details_api(event_id):
    """Test the event details API endpoint"""
    if not event_id:
        print("No event ID to test")
        return
        
    print(f"\n=== Testing Event Details API for ID: {event_id} ===")
    
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
    
    try:
        response = requests.get(details_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        event_details = response.json()
        
        print("Event details retrieved successfully!")
        print(f"  Event Names: {event_details.get('eventNames')}")
        print(f"  Sport: {event_details.get('sportName')}")
        print(f"  Competition: {event_details.get('competitionName')}")
        print(f"  Start Time: {event_details.get('startTime')}")
        
        # Check market groups
        market_groups = event_details.get("marketGroups", [])
        print(f"  Market Groups: {len(market_groups)}")
        
        for i, group in enumerate(market_groups[:3]):  # Show first 3 groups
            group_name = group.get("name", "Unknown")
            markets = group.get("markets", [])
            print(f"    Group {i+1}: {group_name} ({len(markets)} markets)")
            
            # Show first market details
            if markets:
                first_market = markets[0]
                print(f"      First Market: {first_market.get('name')} (ID: {first_market.get('id')})")
                outcomes = first_market.get("outcomes", [])
                print(f"      Outcomes: {len(outcomes)}")
                if outcomes:
                    first_outcome = outcomes[0]
                    print(f"        First Outcome: {first_outcome.get('name')} (ID: {first_outcome.get('id')}) - Odds: {first_outcome.get('value')}")
        
        return event_details
        
    except Exception as e:
        print(f"Event details API test failed: {e}")
        return None

def test_bet_engine_integration():
    """Test the BetEngine integration with the new API"""
    print("\n=== Testing BetEngine Integration ===")
    
    try:
        # Import BetEngine
        from bet_engine import BetEngine
        
        # Initialize with test configuration
        engine = BetEngine(
            headless=True,
            skip_initial_login=True,
            config_file="config.json" if os.path.exists("config.json") else None
        )
        
        print("BetEngine initialized successfully")
        
        # Test search functionality
        print("\nTesting search functionality...")
        event_id = engine._BetEngine__search_event("Karlbergs", "IK Brage Borlange")
        
        if event_id:
            print(f"Search successful! Found event ID: {event_id}")
            
            # Test event details
            print("\nTesting event details...")
            event_details = engine._BetEngine__get_event_details(event_id)
            
            if event_details:
                print("Event details retrieved successfully!")
                print(f"  Home Team: {event_details.get('homeTeam')}")
                print(f"  Away Team: {event_details.get('awayTeam')}")
                print(f"  Event ID: {event_details.get('eventId')}")
                
                # Test bet URL generation
                print("\nTesting bet URL generation...")
                bet_url = engine._BetEngine__generate_nairabet_bet_url(event_details)
                if bet_url:
                    print(f"Bet URL generated: {bet_url}")
                else:
                    print("Bet URL generation failed")
            else:
                print("Event details retrieval failed")
        else:
            print("Search failed")
            
        # Cleanup
        engine.cleanup()
        print("\nBetEngine cleanup completed")
        
    except ImportError as e:
        print(f"Could not import BetEngine: {e}")
    except Exception as e:
        print(f"BetEngine integration test failed: {e}")

def main():
    """Main test function"""
    print("Nairabet API Integration Test")
    print("=" * 40)
    
    # Test 1: Direct API calls
    event_id = test_search_api()
    if event_id:
        test_event_details_api(event_id)
    
    # Test 2: BetEngine integration
    test_bet_engine_integration()
    
    print("\n" + "=" * 40)
    print("Test completed!")

if __name__ == "__main__":
    main() 