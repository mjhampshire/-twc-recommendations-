"""Scheduled jobs for the recommendation service."""
from .ab_test_promoter import run_auto_promotion

__all__ = ["run_auto_promotion"]
