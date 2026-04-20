"""Scheduled job for A/B test auto-promotion.

This job can be run via cron or Kubernetes CronJob to automatically:
1. Check all active A/B tests for statistical significance
2. Promote winning variants as new defaults
3. Generate and start new test iterations

Usage:
    python -m src.jobs.ab_test_promoter

Environment variables:
    CLICKHOUSE_HOST: ClickHouse host (required)
    CLICKHOUSE_PORT: ClickHouse port (default: 8123)
    CLICKHOUSE_USERNAME: ClickHouse username (default: default)
    CLICKHOUSE_PASSWORD: ClickHouse password (default: empty)
    CLICKHOUSE_DATABASE: ClickHouse database (default: default)
"""
import json
import logging
import os
import sys
from datetime import datetime

from ..config.clickhouse import get_clickhouse_config
from ..engine.ab_test_analyzer import ABTestAnalyzer


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ab_test_promoter")


def run_auto_promotion() -> list[dict]:
    """
    Run the auto-promotion job.

    Returns:
        List of actions taken during this run
    """
    logger.info("Starting A/B test auto-promotion job")

    # Check for required configuration
    if not os.getenv("CLICKHOUSE_HOST"):
        logger.error("CLICKHOUSE_HOST environment variable not set")
        return []

    try:
        config = get_clickhouse_config()
        analyzer = ABTestAnalyzer(config)

        actions = analyzer.auto_promote_and_iterate()

        # Log results
        if actions:
            logger.info(f"Completed {len(actions)} action(s):")
            for action in actions:
                if action.get("action") == "error":
                    logger.error(f"  Test {action['test_id']}: {action['error']}")
                else:
                    logger.info(
                        f"  Test {action['test_id']}: {action['action']} - "
                        f"winner: {action.get('winner_weights')}, "
                        f"lift: {action.get('lift', 0):.2%}, "
                        f"p-value: {action.get('p_value', 1):.4f}"
                    )
                    if action.get("new_test_id"):
                        logger.info(
                            f"    New test started: {action['new_test_id']} "
                            f"({action.get('new_treatment_weights')})"
                        )
        else:
            logger.info("No actions taken - tests still collecting data or no active tests")

        return actions

    except Exception as e:
        logger.exception(f"Error running auto-promotion job: {e}")
        return [{"action": "error", "error": str(e)}]


def main():
    """Entry point for the scheduled job."""
    start_time = datetime.utcnow()
    logger.info(f"Job started at {start_time.isoformat()}")

    actions = run_auto_promotion()

    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()
    logger.info(f"Job completed in {duration:.2f}s")

    # Output JSON summary for logging/monitoring
    summary = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": duration,
        "actions": actions,
        "action_count": len(actions),
    }
    print(json.dumps(summary, indent=2))

    # Exit with error code if any errors occurred
    if any(a.get("action") == "error" for a in actions):
        sys.exit(1)


if __name__ == "__main__":
    main()
