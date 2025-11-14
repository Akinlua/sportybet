import json
import logging
from bet_engine import BetEngine

logger = logging.getLogger('nairabet_betting')
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

def run_search_tests():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}
    be = BetEngine(config, skip_initial_login=True)
    scenarios = [
        ("Leeds", "Aston Villa"),
        # ("Orlando Magic", "Atlanta Hawks"),
    ]
    results = []
    for home, away in scenarios:
        logger.info(f"Searching event: {home} vs {away}")
        eid = be.search_event(home, away)
        if not eid:
            logger.info("Event not found")
            results.append((home, away, None))
            continue
        logger.info(f"Found eventId: {eid}")
        details = be.get_event_details(eid)
        if details:
            url = be.generate_sportybet_bet_url(details)
            logger.info(f"URL: {url}")
            results.append((home, away, eid))
        else:
            logger.info("No event details")
            results.append((home, away, eid))
    return results

def main():
    run_search_tests()

if __name__ == "__main__":
    main()