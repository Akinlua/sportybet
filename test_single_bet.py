#!/usr/bin/env python3
"""
Simple test script for testing individual bet placements.
Quick way to test specific scenarios without running full alert flow.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

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
BET_ENGINE = None
SERVER_THREAD = None
SERVER = None

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
        "sportId": 1,  # Football (Sporty: sr:sport:1)
        "type": "prematch",
        "periodNumber": "1" if is_first_half else "0",
        "eventId": "sr:match:65897796",
        "starts": 1774544400000
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
        "stake": 10
    }

def test_quick_scenarios():
    """Pre-defined quick test scenarios"""
    scenarios = {
        # "1": {
        #     "name": "Moneyline Home Win",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "home")
        # },
        # "2": {
        #     "name": "Moneyline Home Draw",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "draw")
        # },
        # "3": {
        #     "name": "Moneyline Home away",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "away")
        # },
        # "4": {
        #     "name": "Over 0.5 Goals",
        #     "alert": create_quick_alert("Turkiye", "Romania", "total", "over", points=0.5)
        # },
        # "5": {
        #     "name": "Under 0.5 Goals",
        #     "alert": create_quick_alert("Turkiye", "Romania", "total", "under", points=0.5)
        # },
        # "6": {
        #     "name": "Asian Handicap 1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=1.5)
        # },
        #  "7": {
        #     "name": "Asian Handicap -1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=-1.5)
        # },
        # "8": {
        #     "name": "DNB (Zero Handicap)",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=0.0) 
        # },
        # "9": {
        #     "name": "DNB (Zero Handicap)",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=0.0) 
        # },
        # "10": {
        #     "name": "First half Moneyline Home Win",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "home", is_first_half=True)
        # },
        # "11": {
        #     "name": "First half Moneyline Home Draw",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "draw", is_first_half=True)
        # },
        # "12": {
        #     "name": "First half Moneyline Home away",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "away", is_first_half=True)
        # },
        # "13": {
        #     "name": "First half Over 1.5 Goals",
        #     "alert": create_quick_alert("Turkiye", "Romania", "total", "over", points=1.5, is_first_half=True)
        # },
        # "14": {
        #     "name": "First half Under 1.5 Goals",
        #     "alert": create_quick_alert("Turkiye", "Romania", "total", "under", points=1.5, is_first_half=True)
        # },
        # "15": {
        #     "name": "First half Asian Handicap 1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=1.5, is_first_half=True)
        # },
        # "16": {
        #     "name": "First half Asian Handicap -1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=-1.5, is_first_half=True)
        # },
        # "17": {
        #     "name": "First half DNB (Zero Handicap)",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=0.0, is_first_half=True) 
        # },
        # "18": {
        #     "name": "First half DNB (Zero Handicap)",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=0.0, is_first_half=True) 
        # }


        "1": {
            "name": "Moneyline Home Win",
            "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "home")
        },
        "2": {
            "name": "Moneyline Home Draw",
            "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "draw")
        },
        "3": {
            "name": "Moneyline Home away",
            "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "away")
        },
        "4": {
            "name": "Over 158.5 Goals",
            "alert": create_quick_alert("Turkiye", "Romania", "total", "over", points=158.5)  
        },
        "5": {
            "name": "Under 161.5 Goals",
            "alert": create_quick_alert("Turkiye", "Romania", "total", "under", points=161.5)  
        },
        # "6": {
        #     "name": "Asian Handicap 1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=1.5)
        # },
        #  "7": {
        #     "name": "Asian Handicap -1.5",
        #     "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=-1.5)
        # },
        "8": {
            "name": "DNB (Zero Handicap)",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=0.0) 
        },
        "9": {
            "name": "DNB (Zero Handicap)",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=0.0) 
        },
        # "10": {
        #     "name": "First half Moneyline Home Win",
        #     "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "home", is_first_half=True)
        # },
        "11": {
            "name": "First half Moneyline Home Draw",
            "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "draw", is_first_half=True)
        },
        "12": {
            "name": "First half Moneyline Home away",
            "alert": create_quick_alert("Turkiye", "Romania", "moneyline", "away", is_first_half=True)
        },
        "13": {
            "name": "First half Over 78.5 Goals",
            "alert": create_quick_alert("Turkiye", "Romania", "total", "over", points=78.5, is_first_half=True)
        },
        "14": {
            "name": "First half Under 78.5 Goals",
            "alert": create_quick_alert("Turkiye", "Romania", "total", "under", points=78.5, is_first_half=True)
        },
        "15": {
            "name": "First half Asian Handicap 3.5",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=3.5, is_first_half=True)
        },
        "16": {
            "name": "First half Asian Handicap -3.5",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=-3.5, is_first_half=True)
        },
        "17": {
            "name": "First half DNB (Zero Handicap)",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "home", points=0.0, is_first_half=True) 
        },
        "18": {
            "name": "First half DNB (Zero Handicap)",
            "alert": create_quick_alert("Turkiye", "Romania", "spread", "away", points=0.0, is_first_half=True) 
        }
    }
    
    return scenarios

class QueueHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/enqueue":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8"))
                alert = data.get("alert") or data
                shaped = shape_alert_data(alert)
                line_type = alert["lineType"]
                if line_type == "moneyline":
                    mapped_line_type = "money_line"
                elif line_type == "total":
                    mapped_line_type = "total"
                elif line_type == "spread":
                    mapped_line_type = "spread"
                else:
                    mapped_line_type = line_type
                outcome = alert["outcome"]
                is_first_half = alert.get("periodNumber") == "1"
                event_details = {
                    "eventId": alert.get("eventId", "sr:match:61300743"),
                    "estimateStartTime": alert.get("starts", 1756321200000),
                    "status": 0,
                    "homeTeamName": alert["home"],
                    "awayTeamName": alert["away"],
                    "homeTeam": alert["home"],
                    "awayTeam": alert["away"],
                    "sport": {"id": "sr:sport:1", "name": "Football", "category": {"id": "sr:category:1", "name": "", "tournament": {"id": "", "name": ""}}},
                    "sportId": alert.get("sportId", 1),
                    "markets": []
                }
                odds = float(data.get("odds", 2.0))
                BET_ENGINE.set_bet_placement_mode(immediate=False)
                ok = BET_ENGINE._BetEngine__place_bet(
                    event_details=event_details,
                    line_type=mapped_line_type,
                    outcome=outcome,
                    odds=odds,
                    modified_shaped_data=shaped,
                    is_first_half=is_first_half,
                    stake=shaped.get("stake", 50)
                )
                resp = {"ok": bool(ok)}
                out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                out = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
        else:
            self.send_response(404)
            self.end_headers()

def start_queue_server_async():
    global SERVER, SERVER_THREAD
    port = int(os.getenv("TEST_SERVER_PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), QueueHandler)
    logger.info(f"Queue server listening on http://127.0.0.1:{port}/enqueue")
    if SERVER_THREAD and SERVER_THREAD.is_alive():
        logger.info("Queue server already running")
        SERVER = srv
        return srv
    SERVER = srv
    SERVER_THREAD = threading.Thread(target=srv.serve_forever, daemon=True)
    SERVER_THREAD.start()
    return srv

def run_single_test(bet_engine, alert_data, scenario_name):
    """Run a single bet test - directly place bet without odds checking"""
    logger.info(f"\n🎯 Testing: {scenario_name}")
    logger.info(f"Match: {alert_data['home']} vs {alert_data['away']}")
    logger.info(f"Bet: {alert_data['lineType']} - {alert_data['outcome']}")
    sport_id = alert_data.get('sportId')
    sport_info = (
        {"id": "sr:sport:1", "name": "Football"} if sport_id in (1, "1", "sr:sport:1") else
        {"id": "sr:sport:2", "name": "Basketball"} if sport_id in (2, "2", "sr:sport:2") else
        {"id": str(sport_id), "name": ""}
    )
    logger.info(f"Sport: {sport_info['name']} ({sport_info['id']})")
    if alert_data.get('points'):
        logger.info(f"Points: {alert_data['points']}")
    if alert_data.get('periodNumber') == "1":
        logger.info("Period: First Half")
    
    try:
        # Shape data for bet engine
        shaped_data = shape_alert_data(alert_data)
        
        # Create mock event details (since we're bypassing Pinnacle lookup)
        event_details = {
            # Sporty-style event details
            "eventId": alert_data.get('eventId', "sr:match:61300743"),
            "estimateStartTime": alert_data.get('starts', 1774544400000),
            "status": 0,
            "homeTeamName": alert_data['home'],
            "awayTeamName": alert_data['away'],
            # Provide both forms to satisfy engine getters
            "homeTeam": alert_data['home'],
            "awayTeam": alert_data['away'],
            "sport": {
                "id": "sr:sport:1",
                "name": "Football",
                "category": {
                    "id": "sr:category:4",
                    "name": "International",
                    "tournament": {
                        "id": "sr:tournament:11",
                        "name": "FIFA World Cup Qualification, UEFA"
                    }
                }
            },
            "sportId": 2,
            # "sport": sport_info,
            # Markets not needed for direct placement, but kept for completeness
            "markets": []
        }
        
        # Mock odds (you can adjust these test values)
        test_odds = 1.57  # Default test odds
        
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
            stake=10  # Let bet engine calculate stake
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
        
        global BET_ENGINE
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        BET_ENGINE = BetEngine(headless=os.getenv("ENVIRONMENT") == "production", config_file="config.json", skip_initial_login=True)
        bet_engine = BET_ENGINE
        logger.info("✅ BetEngine initialized")
        
        while True:
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
            print(f"  9. Start queue server (background)")
            print(f"  10. Run scenario multiple times (queued)")
            print(f"  0. Exit")
            choice = input("\nEnter your choice (1-10 or 0 to exit): ").strip().lower()
            if choice in scenarios:
                scenario = scenarios[choice]
                run_single_test(bet_engine, scenario["alert"], scenario["name"])
            elif choice == "7":
                print("\n📝 Custom Bet Setup:")
                home = input("Home team: ").strip()
                away = input("Away team: ").strip()
                print("Bet types: moneyline, total, spread")
                bet_type = input("Bet type: ").strip()
                if bet_type == "moneyline":
                    outcome = input("Outcome (home/away/draw): ").strip()
                    points = None
                elif bet_type == "total":
                    outcome = input("Outcome (over/under): ").strip()
                    points = float(input("Points (e.g., 2.5): ").strip())
                elif bet_type == "spread":
                    outcome = input("Outcome (home/away): ").strip()
                    points = float(input("Points (e.g., -1.5): ").strip())
                else:
                    logger.error("Invalid bet type")
                    continue
                is_first_half = input("First half? (y/n): ").strip().lower() == 'y'
                custom_alert = create_quick_alert(home, away, bet_type, outcome, points, is_first_half)
                run_single_test(bet_engine, custom_alert, "Custom Bet")
            elif choice == "8":
                logger.info(f"\n🎯 Running all {len(scenarios)} scenarios...")
                successes = 0
                for key, scenario in scenarios.items():
                    if run_single_test(bet_engine, scenario["alert"], scenario["name"]):
                        successes += 1
                    import time
                    time.sleep(2)
                logger.info(f"\n📊 Results: {successes}/{len(scenarios)} scenarios successful")
            elif choice == "9":
                bet_engine.set_bet_placement_mode(immediate=False)
                start_queue_server_async()
                continue
            elif choice == "10":
                bet_engine.set_bet_placement_mode(immediate=False)
                key = input("Scenario number: ").strip()
                try:
                    count = int(input("How many times to enqueue: ").strip())
                except Exception:
                    logger.error("Invalid count")
                    continue
                scenario = scenarios.get(key)
                if not scenario:
                    logger.error("Invalid scenario number")
                    continue
                alert = scenario["alert"]
                shaped = shape_alert_data(alert)
                line_type = alert["lineType"]
                mapped_line_type = "money_line" if line_type == "moneyline" else ("total" if line_type == "total" else ("spread" if line_type == "spread" else line_type))
                outcome = alert["outcome"]
                is_first_half = alert.get("periodNumber") == "1"
                # event_details = {
                #     "eventId": alert.get("eventId", "sr:match:61300743"),
                #     "estimateStartTime": alert.get("starts", 1756321200000),
                #     "status": 0,
                #     "homeTeamName": alert["home"],
                #     "awayTeamName": alert["away"],
                #     "homeTeam": alert["home"],
                #     "awayTeam": alert["away"],
                #     "sport": {"id": "sr:sport:1", "name": "Football", "category": {"id": "sr:category:1", "name": "", "tournament": {"id": "", "name": ""}}},
                #     "sportId": alert.get("sportId", 1),
                #     "markets": []
                # }
                event_details = {
                    # Sporty-style event details
                    "eventId": alert.get('eventId', "sr:match:61300743"),
                    "estimateStartTime": alert.get('starts', 1774544400000),
                    "status": 0,
                    "homeTeamName": alert['home'],
                    "awayTeamName": alert['away'],
                    # Provide both forms to satisfy engine getters
                    "homeTeam": alert['home'],
                    "awayTeam": alert['away'],
                    "sport": {
                        "id": "sr:sport:1",
                        "name": "Football",
                        "category": {
                            "id": "sr:category:4",
                            "name": "International",
                            "tournament": {
                                "id": "sr:tournament:11",
                                "name": "FIFA World Cup Qualification, UEFA"
                            }
                        }
                    },
                    "sportId": 2,
                    # "sport": sport_info,
                    # Markets not needed for direct placement, but kept for completeness
                    "markets": []
                }
                
                odds = 1.57
                import time
                for _ in range(count):
                    BET_ENGINE._BetEngine__place_bet(
                        event_details=event_details,
                        line_type=mapped_line_type,
                        outcome=outcome,
                        odds=odds,
                        modified_shaped_data=shaped,
                        is_first_half=is_first_half,
                        stake=shaped.get("stake", 10)
                    )
                    time.sleep(0.5)
                logger.info(f"Enqueued scenario {key} {count} times")
                continue
            elif choice in ("0", "q"):
                break
            else:
                logger.error("Invalid choice")
                continue
        
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
