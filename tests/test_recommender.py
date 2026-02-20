"""Tests for the recommendation engine."""
import pytest
from datetime import datetime, timedelta

from src.models import (
    Customer, CustomerPreferences, PurchaseHistory, WishlistSummary,
    Product, ProductAttributes, ProductSizing, ProductMetrics,
)
from src.config import DEFAULT_WEIGHTS, PREFERENCE_HEAVY_WEIGHTS
from src.engine import RecommendationEngine, score_product


@pytest.fixture
def sample_customer():
    """Create a sample customer for testing."""
    return Customer(
        customer_id="test_001",
        retailer_id="test_retailer",
        name="Test Customer",
        is_vip=True,
        preferences=CustomerPreferences(
            categories=["Dresses", "Tops"],
            colors=["Navy", "Black"],
            fabrics=["Silk"],
            styles=["Classic"],
            brands=["BrandA", "BrandB"],
            size_dress="10",
        ),
        purchase_history=PurchaseHistory(
            total_purchases=10,
            top_categories=["Dresses"],
            top_brands=["BrandA"],
            top_colors=["Navy"],
        ),
        wishlist=WishlistSummary(
            total_wishlisted=5,
            wishlist_categories=["Accessories"],
            wishlist_brands=["BrandA"],
        ),
    )


@pytest.fixture
def sample_products():
    """Create sample products for testing."""
    return [
        Product(
            product_id="p1",
            retailer_id="test_retailer",
            name="Navy Silk Dress by BrandA",
            price=500,
            attributes=ProductAttributes(
                category="Dresses",
                brand="BrandA",
                color="Navy",
                colors=["Navy"],
                fabric="Silk",
                style="Classic",
            ),
            sizing=ProductSizing(available_sizes=["8", "10", "12"]),
            metrics=ProductMetrics(total_purchases=50, total_wishlisted=100),
            is_in_stock=True,
        ),
        Product(
            product_id="p2",
            retailer_id="test_retailer",
            name="Red Cotton Dress by BrandC",
            price=300,
            attributes=ProductAttributes(
                category="Dresses",
                brand="BrandC",
                color="Red",
                colors=["Red"],
                fabric="Cotton",
                style="Casual",
            ),
            sizing=ProductSizing(available_sizes=["10"]),
            is_in_stock=True,
        ),
        Product(
            product_id="p3",
            retailer_id="test_retailer",
            name="Black Silk Top by BrandB",
            price=250,
            attributes=ProductAttributes(
                category="Tops",
                brand="BrandB",
                color="Black",
                colors=["Black"],
                fabric="Silk",
                style="Classic",
            ),
            sizing=ProductSizing(available_sizes=["S", "M"]),
            is_in_stock=True,
        ),
        Product(
            product_id="p4",
            retailer_id="test_retailer",
            name="Out of Stock Item",
            price=400,
            attributes=ProductAttributes(
                category="Dresses",
                brand="BrandA",
                color="Navy",
            ),
            is_in_stock=False,
        ),
    ]


class TestScoring:
    """Test the scoring logic."""

    def test_perfect_match_scores_high(self, sample_customer, sample_products):
        """Product matching all preferences should score highest."""
        # p1 matches: category, color, fabric, style, brand, purchase history
        scored = score_product(sample_products[0], sample_customer, DEFAULT_WEIGHTS)
        assert scored.score > 0.5  # Should be high
        assert len(scored.reasons) > 0

    def test_poor_match_scores_low(self, sample_customer, sample_products):
        """Product not matching preferences should score lower."""
        # p2 only matches category
        scored = score_product(sample_products[1], sample_customer, DEFAULT_WEIGHTS)
        assert scored.score <= 0.35  # Should be lower than good matches

    def test_score_breakdown_populated(self, sample_customer, sample_products):
        """Score breakdown should contain component scores."""
        scored = score_product(sample_products[0], sample_customer, DEFAULT_WEIGHTS)
        assert 'preference_category' in scored.score_breakdown
        assert 'preference_brand' in scored.score_breakdown

    def test_reasons_are_generated(self, sample_customer, sample_products):
        """Human-readable reasons should be generated."""
        scored = score_product(sample_products[0], sample_customer, DEFAULT_WEIGHTS)
        assert any("category" in r.lower() or "brand" in r.lower() for r in scored.reasons)


class TestRecommendationEngine:
    """Test the recommendation engine."""

    def test_returns_requested_count(self, sample_customer, sample_products):
        """Should return the requested number of recommendations."""
        engine = RecommendationEngine()
        recs = engine.recommend(sample_customer, sample_products, n=2)
        assert len(recs) <= 2

    def test_excludes_out_of_stock(self, sample_customer, sample_products):
        """Out of stock products should be excluded."""
        engine = RecommendationEngine()
        recs = engine.recommend(sample_customer, sample_products, n=10)
        product_ids = [r.product.product_id for r in recs]
        assert "p4" not in product_ids

    def test_excludes_specified_products(self, sample_customer, sample_products):
        """Should exclude products in exclusion list."""
        engine = RecommendationEngine()
        recs = engine.recommend(
            sample_customer,
            sample_products,
            n=10,
            exclude_product_ids={"p1"},
        )
        product_ids = [r.product.product_id for r in recs]
        assert "p1" not in product_ids

    def test_results_sorted_by_score(self, sample_customer, sample_products):
        """Results should be sorted by score descending."""
        engine = RecommendationEngine()
        recs = engine.recommend(sample_customer, sample_products, n=10)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_best_match_ranked_first(self, sample_customer, sample_products):
        """Best matching product should be ranked first."""
        engine = RecommendationEngine()
        recs = engine.recommend(sample_customer, sample_products, n=3)
        # p1 is the best match (Navy Silk Dress by BrandA)
        assert recs[0].product.product_id == "p1"

    def test_custom_weights_affect_ranking(self, sample_customer, sample_products):
        """Custom weights should change the scoring."""
        engine = RecommendationEngine()

        recs_default = engine.recommend(
            sample_customer, sample_products, n=3, weights=DEFAULT_WEIGHTS
        )
        recs_pref_heavy = engine.recommend(
            sample_customer, sample_products, n=3, weights=PREFERENCE_HEAVY_WEIGHTS
        )

        # Both should have same top product for this simple case
        # but scores should differ
        assert recs_default[0].score != recs_pref_heavy[0].score


class TestExplainRecommendation:
    """Test recommendation explanations."""

    def test_generates_explanation(self, sample_customer, sample_products):
        """Should generate a human-readable explanation."""
        engine = RecommendationEngine()
        scored = score_product(sample_products[0], sample_customer, DEFAULT_WEIGHTS)
        explanation = engine.explain_recommendation(scored)
        assert len(explanation) > 0
        assert isinstance(explanation, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
