# /Users/user/Documents/sportybet/test_fetch_pinnacle_odds.py
import os
import argparse
from bet_engine import BetEngine

# python3 test_fetch_pinnacle_odds.py --event-id "" --line-type "money_line" --outcome "home" 
def main():
    parser = argparse.ArgumentParser(description="Test fetch latest Pinnacle odds")
    parser.add_argument("--event-id", required=True, help="Pinnacle event ID (e.g., sr:match:62095766)")
    parser.add_argument("--line-type", required=True, choices=["money_line", "spread", "total"])
    parser.add_argument("--outcome", required=True, choices=["home", "away", "draw", "over", "under"])
    parser.add_argument("--points", type=float, help="Points required for spread/total")
    parser.add_argument("--period", type=int, default=0, choices=[0,1], help="0=full match, 1=first half")
    args = parser.parse_args()

    if args.line_type in ("spread","total") and args.points is None:
        print("points is required for spread/total")
        return

    if not os.getenv("PINNACLE_HOST"):
        print("PINNACLE_HOST env var is not set; example: export PINNACLE_HOST=https://api.example.com")
        return

    engine = BetEngine(skip_initial_login=True)
    period_key = "num_1" if args.period == 1 else "num_0"

    prices = engine._BetEngine__fetch_latest_pinnacle_odds(
        args.event_id, args.line_type, args.points, args.outcome, period_key
    )
    print("Latest decimal prices:", prices)

if __name__ == "__main__":
    main()