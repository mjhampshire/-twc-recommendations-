"""Main recommendation engine.

This module orchestrates the recommendation process:
1. Fetch candidate products
2. Score each product against customer profile
3. Filter and rank results
4. Return top recommendations
"""
from typing import Optional
from ..models import Customer, Product, ScoredProduct
from ..config import RecommendationWeights, DEFAULT_WEIGHTS, NEW_CUSTOMER_WEIGHTS
from .scorer import score_product, matches_dislikes


class RecommendationEngine:
    """
    Main recommendation engine for generating personalized product suggestions.

    Usage:
        engine = RecommendationEngine()
        recommendations = engine.recommend(
            customer=customer,
            products=product_catalog,
            n=4,
        )
    """

    def __init__(
        self,
        default_weights: RecommendationWeights = DEFAULT_WEIGHTS,
        min_score_threshold: float = 0.1,
    ):
        self.default_weights = default_weights
        self.min_score_threshold = min_score_threshold

    def _select_weights(
        self,
        customer: Customer,
        weights: Optional[RecommendationWeights],
    ) -> RecommendationWeights:
        """Select appropriate weights based on customer profile."""
        if weights:
            return weights

        # Auto-select weights based on customer data richness
        has_purchase_history = customer.purchase_history.total_purchases > 0
        has_wishlist = customer.wishlist.total_wishlisted > 0
        has_preferences = bool(
            customer.preferences.categories or
            customer.preferences.brands or
            customer.preferences.colors
        )

        # New customer with limited data
        if not has_purchase_history and not has_wishlist:
            return NEW_CUSTOMER_WEIGHTS

        return self.default_weights

    def _filter_products(
        self,
        products: list[Product],
        customer: Customer,
        weights: RecommendationWeights,
        exclude_product_ids: Optional[set[str]] = None,
    ) -> list[Product]:
        """Apply pre-scoring filters to reduce candidate set."""
        filtered = []
        exclude_ids = exclude_product_ids or set()

        # Add recently purchased items to exclusion list
        exclude_ids.update(customer.purchase_history.recent_product_ids)

        for product in products:
            # Skip excluded products
            if product.product_id in exclude_ids:
                continue

            # Skip out of stock if required
            if weights.in_stock_requirement and not product.is_in_stock:
                continue

            # Must be same retailer
            if product.retailer_id != customer.retailer_id:
                continue

            # Filter out products matching customer dislikes (hard filter)
            if matches_dislikes(product, customer.dislikes):
                continue

            filtered.append(product)

        return filtered

    def recommend(
        self,
        customer: Customer,
        products: list[Product],
        n: int = 4,
        weights: Optional[RecommendationWeights] = None,
        exclude_product_ids: Optional[set[str]] = None,
        diversity_factor: float = 0.3,
    ) -> list[ScoredProduct]:
        """
        Generate top N product recommendations for a customer.

        Args:
            customer: Customer profile to generate recommendations for
            products: Candidate product catalog
            n: Number of recommendations to return
            weights: Custom weights (auto-selected if not provided)
            exclude_product_ids: Products to exclude (e.g., already in cart)
            diversity_factor: How much to penalize similar consecutive items (0-1)

        Returns:
            List of ScoredProduct with scores and explanations
        """
        # Select appropriate weights
        effective_weights = self._select_weights(customer, weights)

        # Filter candidates
        candidates = self._filter_products(
            products, customer, effective_weights, exclude_product_ids
        )

        if not candidates:
            return []

        # Score all candidates
        scored = [
            score_product(product, customer, effective_weights)
            for product in candidates
        ]

        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)

        # Apply minimum score threshold
        scored = [s for s in scored if s.score >= self.min_score_threshold]

        # Apply diversity if requested (avoid showing 4 similar items)
        if diversity_factor > 0 and len(scored) > n:
            scored = self._diversify(scored, n, diversity_factor)

        return scored[:n]

    def _diversify(
        self,
        scored: list[ScoredProduct],
        n: int,
        factor: float,
    ) -> list[ScoredProduct]:
        """
        Re-rank to ensure diversity in recommendations.

        Uses a greedy approach: after selecting each item, penalize
        similar items still in the pool.
        """
        if len(scored) <= n:
            return scored

        selected: list[ScoredProduct] = []
        remaining = scored.copy()

        while len(selected) < n and remaining:
            # Take the highest scoring item
            best = remaining.pop(0)
            selected.append(best)

            # Penalize similar items in remaining pool
            best_attrs = best.product.attributes
            for item in remaining:
                penalty = 0.0
                item_attrs = item.product.attributes

                # Same category penalty
                if (best_attrs.category and item_attrs.category and
                    best_attrs.category.lower() == item_attrs.category.lower()):
                    penalty += 0.3

                # Same brand penalty
                if (best_attrs.brand and item_attrs.brand and
                    best_attrs.brand.lower() == item_attrs.brand.lower()):
                    penalty += 0.2

                # Same color penalty
                if (best_attrs.color and item_attrs.color and
                    best_attrs.color.lower() == item_attrs.color.lower()):
                    penalty += 0.1

                # Apply penalty
                item.score *= (1 - penalty * factor)

            # Re-sort remaining
            remaining.sort(key=lambda x: x.score, reverse=True)

        return selected

    def explain_recommendation(self, scored_product: ScoredProduct) -> str:
        """Generate a human-readable explanation for a recommendation."""
        reasons = scored_product.reasons
        if not reasons:
            return "Recommended based on overall popularity."

        if len(reasons) == 1:
            return reasons[0]

        return f"{reasons[0]}. Also: {', '.join(reasons[1:3]).lower()}"

    def find_alternatives(
        self,
        sold_out_product: Product,
        products: list[Product],
        n: int = 3,
    ) -> list[ScoredProduct]:
        """
        Find in-stock alternatives for a sold-out wishlist item.

        Scores products based on similarity to the sold-out product:
        - Same category (strong signal)
        - Same brand (strong signal)
        - Same style
        - Similar color
        - Similar price range
        - Similar fabric

        Args:
            sold_out_product: The product that is out of stock
            products: Candidate product catalog
            n: Number of alternatives to return

        Returns:
            List of ScoredProduct alternatives
        """
        alternatives: list[tuple[float, Product, list[str]]] = []
        source_attrs = sold_out_product.attributes

        for product in products:
            # Must be in stock
            if not product.is_in_stock:
                continue

            # Must be same retailer
            if product.retailer_id != sold_out_product.retailer_id:
                continue

            # Skip the same product
            if product.product_id == sold_out_product.product_id:
                continue

            score = 0.0
            reasons = []
            attrs = product.attributes

            # Category match (most important)
            if (source_attrs.category and attrs.category and
                source_attrs.category.lower() == attrs.category.lower()):
                score += 0.30
                reasons.append(f"Same category: {attrs.category}")

            # Brand match
            if (source_attrs.brand and attrs.brand and
                source_attrs.brand.lower() == attrs.brand.lower()):
                score += 0.25
                reasons.append(f"Same brand: {attrs.brand}")

            # Style match
            if (source_attrs.style and attrs.style and
                source_attrs.style.lower() == attrs.style.lower()):
                score += 0.15
                reasons.append(f"Same style: {attrs.style}")

            # Color match
            source_colors = set(c.lower() for c in (source_attrs.colors or [source_attrs.color] if source_attrs.color else []))
            product_colors = set(c.lower() for c in (attrs.colors or [attrs.color] if attrs.color else []))
            if source_colors & product_colors:
                score += 0.10
                matched_color = list(source_colors & product_colors)[0].title()
                reasons.append(f"Same color: {matched_color}")

            # Fabric match
            source_fabrics = set(f.lower() for f in (source_attrs.fabrics or [source_attrs.fabric] if source_attrs.fabric else []))
            product_fabrics = set(f.lower() for f in (attrs.fabrics or [attrs.fabric] if attrs.fabric else []))
            if source_fabrics & product_fabrics:
                score += 0.10
                matched_fabric = list(source_fabrics & product_fabrics)[0].title()
                reasons.append(f"Same fabric: {matched_fabric}")

            # Price similarity (within 30% range)
            if sold_out_product.price > 0 and product.price > 0:
                price_ratio = product.price / sold_out_product.price
                if 0.7 <= price_ratio <= 1.3:
                    score += 0.10
                    reasons.append("Similar price range")

            # Only include if there's meaningful similarity
            if score >= 0.25:
                alternatives.append((score, product, reasons))

        # Sort by score descending
        alternatives.sort(key=lambda x: x[0], reverse=True)

        # Convert to ScoredProduct
        return [
            ScoredProduct(
                product=product,
                score=score,
                score_breakdown={"similarity": score},
                reasons=reasons[:3],
            )
            for score, product, reasons in alternatives[:n]
        ]

    def get_wishlist_alternatives(
        self,
        customer: Customer,
        products: list[Product],
        n_per_item: int = 2,
    ) -> dict[str, list[ScoredProduct]]:
        """
        Find alternatives for all sold-out items in a customer's wishlist.

        Args:
            customer: Customer with wishlist
            products: Product catalog
            n_per_item: Number of alternatives per sold-out item

        Returns:
            Dict mapping sold_out_product_id -> list of alternatives
        """
        # Build product lookup
        product_map = {p.product_id: p for p in products}

        alternatives = {}

        for wishlist_product_id in customer.wishlist.active_wishlist_items:
            product = product_map.get(wishlist_product_id)

            # Skip if product not found or is in stock
            if not product or product.is_in_stock:
                continue

            # Find alternatives for this sold-out item
            alts = self.find_alternatives(product, products, n=n_per_item)
            if alts:
                alternatives[wishlist_product_id] = alts

        return alternatives
