"""Tests for the recommendation engine."""
import pytest
from datetime import datetime, timedelta

from src.models import (
    Customer, CustomerPreferences, CustomerDislikes, PreferenceItem, PreferenceSource,
    PurchaseHistory, WishlistSummary,
    Product, ProductAttributes, ProductSizing, ProductMetrics,
)
from src.config import DEFAULT_WEIGHTS, PREFERENCE_HEAVY_WEIGHTS, RecommendationWeights
from src.engine import RecommendationEngine, score_product


def pref(value: str, source: PreferenceSource = PreferenceSource.STAFF) -> PreferenceItem:
    """Helper to create PreferenceItem."""
    return PreferenceItem(value=value, source=source)


@pytest.fixture
def sample_customer():
    """Create a sample customer for testing."""
    return Customer(
        customer_id="test_001",
        retailer_id="test_retailer",
        name="Test Customer",
        is_vip=True,
        preferences=CustomerPreferences(
            categories=[pref("Dresses"), pref("Tops")],
            colors=[pref("Navy"), pref("Black")],
            fabrics=[pref("Silk")],
            styles=[pref("Classic")],
            brands=[pref("BrandA"), pref("BrandB")],
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
            stock_status=None,
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
            stock_status=None,
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
            stock_status=None,
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
            stock_status="out_of_stock",
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
        """Out of stock products should be excluded when in_stock_requirement=True."""
        engine = RecommendationEngine()
        weights = RecommendationWeights(in_stock_requirement=True)
        recs = engine.recommend(sample_customer, sample_products, n=10, weights=weights)
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


class TestDislikes:
    """Test dislike filtering."""

    def test_disliked_brand_filtered_out(self, sample_products):
        """Products matching disliked brand should be filtered out."""
        customer = Customer(
            customer_id="test_dislikes",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Dresses")],
            ),
            dislikes=CustomerDislikes(
                brands=[pref("BrandA")],  # Dislike BrandA
            ),
        )
        engine = RecommendationEngine()
        recs = engine.recommend(customer, sample_products, n=10)
        product_ids = [r.product.product_id for r in recs]
        # p1 is BrandA, should be filtered
        assert "p1" not in product_ids

    def test_disliked_color_filtered_out(self, sample_products):
        """Products matching disliked color should be filtered out."""
        customer = Customer(
            customer_id="test_dislikes",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Dresses")],
            ),
            dislikes=CustomerDislikes(
                colors=[pref("Navy")],  # Dislike Navy
            ),
        )
        engine = RecommendationEngine()
        recs = engine.recommend(customer, sample_products, n=10)
        product_ids = [r.product.product_id for r in recs]
        # p1 is Navy, should be filtered
        assert "p1" not in product_ids

    def test_disliked_category_filtered_out(self, sample_products):
        """Products matching disliked category should be filtered out."""
        customer = Customer(
            customer_id="test_dislikes",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],  # Has some preferences so score isn't zero
            ),
            dislikes=CustomerDislikes(
                categories=[pref("Dresses")],  # Dislike Dresses
            ),
        )
        engine = RecommendationEngine(min_score_threshold=0)  # Allow low scores for this test
        recs = engine.recommend(customer, sample_products, n=10)
        product_ids = [r.product.product_id for r in recs]
        # p1, p2 are Dresses, should be filtered
        assert "p1" not in product_ids
        assert "p2" not in product_ids
        # p3 is Tops, should remain
        assert "p3" in product_ids

    def test_no_dislikes_no_filtering(self, sample_customer, sample_products):
        """Without dislikes, no additional filtering happens."""
        engine = RecommendationEngine()
        recs = engine.recommend(sample_customer, sample_products, n=10)
        # All products should be candidates (stock filtering disabled by default)
        assert len(recs) == 4  # p1, p2, p3, p4


class TestPreferenceSource:
    """Test preference source multipliers."""

    def test_customer_source_multiplier_boosts_score(self, sample_products):
        """Customer-entered preferences with multiplier > 1 should boost score."""
        # Customer with customer-entered preference
        customer = Customer(
            customer_id="test_source",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                brands=[pref("BrandA", PreferenceSource.CUSTOMER)],
            ),
        )

        weights_boosted = RecommendationWeights(customer_source_multiplier=1.5)
        weights_normal = RecommendationWeights(customer_source_multiplier=1.0)

        scored_boosted = score_product(sample_products[0], customer, weights_boosted)
        scored_normal = score_product(sample_products[0], customer, weights_normal)

        assert scored_boosted.score > scored_normal.score

    def test_staff_source_multiplier_reduces_score(self, sample_products):
        """Staff-entered preferences with multiplier < 1 should reduce score."""
        customer = Customer(
            customer_id="test_source",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                brands=[pref("BrandA", PreferenceSource.STAFF)],
            ),
        )

        weights_reduced = RecommendationWeights(staff_source_multiplier=0.8)
        weights_normal = RecommendationWeights(staff_source_multiplier=1.0)

        scored_reduced = score_product(sample_products[0], customer, weights_reduced)
        scored_normal = score_product(sample_products[0], customer, weights_normal)

        assert scored_reduced.score < scored_normal.score

    def test_mixed_sources_uses_highest_multiplier(self, sample_products):
        """When multiple preferences match, use the highest source multiplier."""
        # Product p1 is Navy - customer has Navy from both sources
        customer = Customer(
            customer_id="test_source",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                colors=[
                    pref("Navy", PreferenceSource.STAFF),
                    pref("Black", PreferenceSource.CUSTOMER),  # Not on product
                ],
            ),
        )

        weights = RecommendationWeights(
            customer_source_multiplier=1.5,
            staff_source_multiplier=0.8,
        )

        # Only Navy matches, and it's staff-entered, so should use 0.8
        scored = score_product(sample_products[0], customer, weights)
        assert scored.score_breakdown.get('preference_color', 0) > 0


class TestPopularityFallback:
    """Test popularity fallback when personalized recommendations are insufficient."""

    def test_fills_with_popular_when_insufficient_personalized(self):
        """Should fill remaining slots with popular items when personalized results are few."""
        # Customer with preferences that match only one product well
        customer = Customer(
            customer_id="test_fallback",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Dresses")],
                colors=[pref("Navy")],
                brands=[pref("BrandA")],
            ),
        )

        products = [
            # This one matches preferences well
            Product(
                product_id="p_match",
                product_ref="base_match",
                retailer_id="test_retailer",
                name="Navy Dress by BrandA",
                price=100,
                attributes=ProductAttributes(category="Dresses", color="Navy", brand="BrandA"),
                metrics=ProductMetrics(total_purchases=10),
            ),
            # These are popular but don't match preferences
            Product(
                product_id="p_popular1",
                product_ref="base_pop1",
                retailer_id="test_retailer",
                name="Popular Item 1",
                price=100,
                attributes=ProductAttributes(category="Shoes", color="Red", brand="OtherBrand"),
                metrics=ProductMetrics(total_purchases=500, trending_score=0.8),
            ),
            Product(
                product_id="p_popular2",
                product_ref="base_pop2",
                retailer_id="test_retailer",
                name="Popular Item 2",
                price=100,
                attributes=ProductAttributes(category="Bags", color="Black", brand="OtherBrand2"),
                metrics=ProductMetrics(total_purchases=300),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0.1)
        recs = engine.recommend(customer, products, n=3, fill_with_popular=True)

        # Should get 3 results: 1 personalized + 2 popular fallback
        assert len(recs) == 3
        # First should be the personalized match (highest personalized score)
        assert recs[0].product.product_id == "p_match"
        # Remaining should be popular items
        fallback_ids = {r.product.product_id for r in recs[1:]}
        assert "p_popular1" in fallback_ids or "p_popular2" in fallback_ids

    def test_no_fallback_when_disabled(self):
        """Should not fill with popular items when fill_with_popular=False."""
        customer = Customer(
            customer_id="test_fallback",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Dresses")],
                colors=[pref("Navy")],
                brands=[pref("BrandA")],
            ),
        )

        products = [
            Product(
                product_id="p_match",
                product_ref="base_match",
                retailer_id="test_retailer",
                name="Navy Dress by BrandA",
                price=100,
                attributes=ProductAttributes(category="Dresses", color="Navy", brand="BrandA"),
            ),
            Product(
                product_id="p_popular",
                product_ref="base_pop",
                retailer_id="test_retailer",
                name="Popular Item",
                price=100,
                attributes=ProductAttributes(category="Shoes", color="Red"),
                metrics=ProductMetrics(total_purchases=500),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0.1)
        recs = engine.recommend(customer, products, n=3, fill_with_popular=False)

        # Should only get the personalized result, not filled with popular
        assert len(recs) == 1
        assert recs[0].product.product_id == "p_match"

    def test_fallback_respects_deduplication(self):
        """Fallback should not include variants of products already in results."""
        customer = Customer(
            customer_id="test_fallback",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
                colors=[pref("Navy")],
                brands=[pref("BrandA")],
            ),
        )

        products = [
            # This matches preferences well
            Product(
                product_id="v1_navy_m",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Navy M",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy", brand="BrandA"),
            ),
            # Same product, different size - should not appear in fallback
            Product(
                product_id="v1_navy_l",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Navy L",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy", brand="BrandA"),
                metrics=ProductMetrics(total_purchases=1000),  # Very popular
            ),
            # Different product - can appear in fallback
            Product(
                product_id="v2",
                product_ref="base2",
                retailer_id="test_retailer",
                name="Other Top",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Red", brand="OtherBrand"),
                metrics=ProductMetrics(total_purchases=50),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0.1)
        recs = engine.recommend(customer, products, n=2, fill_with_popular=True)

        # Should get 2: personalized navy + fallback other (not navy L variant)
        assert len(recs) == 2
        product_ids = {r.product.product_id for r in recs}
        # One of the navy variants should be there (they're deduplicated)
        assert "v1_navy_m" in product_ids or "v1_navy_l" in product_ids
        # The other product should fill the second slot
        assert "v2" in product_ids
        # Both navy variants should NOT both be there
        assert not ("v1_navy_m" in product_ids and "v1_navy_l" in product_ids)


class TestVariantDeduplication:
    """Test variant deduplication logic."""

    def test_same_product_same_color_different_sizes_deduplicated(self):
        """Same product+color in multiple sizes should return only one."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
                colors=[pref("Navy")],
            ),
        )

        # Same product (product_ref=base1) in 3 sizes, same color
        products = [
            Product(
                product_id="v1_s",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Navy Top - Small",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v1_m",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Navy Top - Medium",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v1_l",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Navy Top - Large",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should only get 1 recommendation (all are same product+color)
        assert len(recs) == 1

    def test_same_product_different_colors_with_affinity_kept(self):
        """Same product in different colors should be kept if customer has affinity for both."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
                colors=[pref("Navy"), pref("Black")],  # Has affinity for both
            ),
        )

        products = [
            Product(
                product_id="v1_navy",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Navy",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v1_black",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Black",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Black"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should get both colors since customer has affinity for both
        assert len(recs) == 2
        colors = {r.product.attributes.color for r in recs}
        assert colors == {"Navy", "Black"}

    def test_same_product_different_colors_without_affinity_one_kept(self):
        """Same product in different colors without affinity should only keep highest scoring."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
                colors=[pref("Navy")],  # Only has affinity for Navy
            ),
        )

        products = [
            Product(
                product_id="v1_navy",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Navy",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v1_red",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Red",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Red"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should only get Navy (has affinity) - Red should be deduplicated
        assert len(recs) == 1
        assert recs[0].product.attributes.color == "Navy"

    def test_purchase_history_color_creates_affinity(self):
        """Colors from purchase history should create affinity."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
            ),
            purchase_history=PurchaseHistory(
                total_purchases=5,
                top_colors=["Red", "Navy"],  # Has purchased these colors
            ),
        )

        products = [
            Product(
                product_id="v1_navy",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Navy",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v1_red",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Red",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Red"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should get both colors since customer has purchased both
        assert len(recs) == 2

    def test_wishlist_color_creates_affinity(self):
        """Colors from wishlist should create affinity."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
            ),
            wishlist=WishlistSummary(
                total_wishlisted=3,
                wishlist_colors=["Green"],  # Has wishlisted green items
            ),
        )

        products = [
            Product(
                product_id="v1_green",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Green",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Green"),
            ),
            Product(
                product_id="v1_blue",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top - Blue",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Blue"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should only get Green (from wishlist affinity)
        # Blue has no affinity so only highest scorer per product_ref is kept
        assert len(recs) == 1
        assert recs[0].product.attributes.color == "Green"

    def test_different_products_not_deduplicated(self):
        """Different products (different product_ref) should not be deduplicated."""
        customer = Customer(
            customer_id="test_dedupe",
            retailer_id="test_retailer",
            preferences=CustomerPreferences(
                categories=[pref("Tops")],
                colors=[pref("Navy")],
            ),
        )

        products = [
            Product(
                product_id="v1",
                product_ref="base1",
                retailer_id="test_retailer",
                name="Top A - Navy",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
            Product(
                product_id="v2",
                product_ref="base2",  # Different product
                retailer_id="test_retailer",
                name="Top B - Navy",
                price=100,
                attributes=ProductAttributes(category="Tops", color="Navy"),
            ),
        ]

        engine = RecommendationEngine(min_score_threshold=0)
        recs = engine.recommend(customer, products, n=3)

        # Should get both - they're different products
        assert len(recs) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
