"""Main recommendation engine.

This module orchestrates the recommendation process:
1. Fetch candidate products
2. Score each product against customer profile
3. Filter and rank results
4. Deduplicate variants (same product, same color = keep one)
5. Return top recommendations
"""
from collections import defaultdict
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

            # Skip out of stock if required (check stock_status field)
            if weights.in_stock_requirement and product.stock_status == "out_of_stock":
                continue

            # Must be same retailer
            if product.retailer_id != customer.retailer_id:
                continue

            # Filter out products matching customer dislikes (hard filter)
            if matches_dislikes(product, customer.dislikes):
                continue

            filtered.append(product)

        return filtered

    def _get_customer_color_affinity(self, customer: Customer) -> set[str]:
        """Get colors the customer has shown interest in.

        Sources (in order of signal strength):
        - Stated color preferences
        - Colors from purchase history
        - Colors from wishlist items
        - Colors from browsing behavior
        """
        colors = set()

        # Stated preferences (strongest signal)
        for pref in customer.preferences.colors:
            colors.add(pref.value.lower())

        # Purchase history
        for color in customer.purchase_history.top_colors:
            colors.add(color.lower())

        # Wishlist
        for color in customer.wishlist.wishlist_colors:
            colors.add(color.lower())

        # Browsing behavior (weaker but still relevant)
        for color in customer.browsing.viewed_colors:
            colors.add(color.lower())

        return colors

    def _deduplicate_variants(
        self,
        scored: list[ScoredProduct],
        customer: Customer,
    ) -> list[ScoredProduct]:
        """Deduplicate product variants to avoid recommending same product in multiple sizes.

        Rules:
        1. Same product_ref + same color = keep only highest-scoring variant (different sizes)
        2. Same product_ref + different colors = keep multiple only if customer has
           affinity for those colors (via preferences, purchase history, or wishlist)
        """
        if not scored:
            return scored

        customer_colors = self._get_customer_color_affinity(customer)

        # First pass: group by (product_ref, color) and keep highest scorer per group
        # This eliminates same product/same color in different sizes
        by_product_color: dict[tuple[str, str], ScoredProduct] = {}

        for item in scored:
            product_ref = item.product.product_ref
            color = (item.product.attributes.color or "").lower()

            # If no product_ref, can't dedupe - keep it
            if not product_ref:
                # Use product_id as fallback key
                key = (item.product.product_id, color)
            else:
                key = (product_ref, color)

            # Keep highest scoring variant for each (product_ref, color) combo
            if key not in by_product_color or item.score > by_product_color[key].score:
                by_product_color[key] = item

        # Second pass: for each product_ref, decide which colors to keep
        # Group the deduplicated items by product_ref
        by_product: dict[str, list[ScoredProduct]] = defaultdict(list)
        for (product_ref_or_id, _), item in by_product_color.items():
            ref = item.product.product_ref or item.product.product_id
            by_product[ref].append(item)

        # For each product, keep colors the customer has affinity for,
        # or just the highest-scoring color if no affinity matches
        deduplicated = []
        for product_ref, items in by_product.items():
            # Sort by score descending
            items.sort(key=lambda x: x.score, reverse=True)

            # Always keep the top-scoring variant
            deduplicated.append(items[0])

            # For additional colors, only keep if customer has affinity
            for item in items[1:]:
                item_color = (item.product.attributes.color or "").lower()
                if item_color and item_color in customer_colors:
                    deduplicated.append(item)

        # Re-sort by score
        deduplicated.sort(key=lambda x: x.score, reverse=True)
        return deduplicated

    def _get_popularity_fallback(
        self,
        candidates: list[Product],
        exclude_product_ids: set[str],
        exclude_product_refs: set[str],
        n: int,
    ) -> list[ScoredProduct]:
        """Get generic recommendations based on popularity when personalized results are insufficient.

        Args:
            candidates: Filtered product candidates (already passed dislikes/stock filters)
            exclude_product_ids: Product IDs already in personalized results
            exclude_product_refs: Product refs already in results (to avoid variants)
            n: Number of fallback recommendations needed

        Returns:
            List of ScoredProduct ranked by popularity
        """
        fallback_candidates = []

        for product in candidates:
            # Skip products already in results
            if product.product_id in exclude_product_ids:
                continue

            # Skip variants of products already in results
            if product.product_ref and product.product_ref in exclude_product_refs:
                continue

            fallback_candidates.append(product)

        if not fallback_candidates:
            return []

        # Score by popularity metrics only
        scored_fallback = []
        for product in fallback_candidates:
            metrics = product.metrics
            # Combine popularity signals
            popularity_score = 0.0
            reasons = []

            # Purchase popularity (normalized, assume max ~1000 purchases)
            if metrics.total_purchases > 0:
                purchase_score = min(metrics.total_purchases / 500, 1.0) * 0.4
                popularity_score += purchase_score
                reasons.append(f"Popular item ({metrics.total_purchases} purchases)")

            # Wishlist popularity
            if metrics.total_wishlisted > 0:
                wishlist_score = min(metrics.total_wishlisted / 200, 1.0) * 0.2
                popularity_score += wishlist_score

            # Trending score (already 0-1)
            if metrics.trending_score > 0:
                popularity_score += metrics.trending_score * 0.2
                reasons.append("Trending")

            # New arrival bonus
            if product.is_new_arrival:
                popularity_score += 0.2
                reasons.append("New arrival")

            # Fallback minimum score if no metrics
            if popularity_score == 0:
                popularity_score = 0.05
                reasons.append("Available item")

            scored_fallback.append(ScoredProduct(
                product=product,
                score=popularity_score,
                score_breakdown={"popularity": popularity_score},
                reasons=reasons[:2] if reasons else ["Popular item"],
            ))

        # Sort by popularity score
        scored_fallback.sort(key=lambda x: x.score, reverse=True)

        # Deduplicate by product_ref + color (keep one variant per product/color)
        seen_product_colors: set[tuple[str, str]] = set()
        deduplicated = []

        for item in scored_fallback:
            product_ref = item.product.product_ref or item.product.product_id
            color = (item.product.attributes.color or "").lower()
            key = (product_ref, color)

            if key not in seen_product_colors:
                seen_product_colors.add(key)
                deduplicated.append(item)

            if len(deduplicated) >= n:
                break

        return deduplicated

    def recommend(
        self,
        customer: Customer,
        products: list[Product],
        n: int = 4,
        weights: Optional[RecommendationWeights] = None,
        exclude_product_ids: Optional[set[str]] = None,
        diversity_factor: float = 0.3,
        fill_with_popular: bool = True,
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
            fill_with_popular: If True, fill remaining slots with popular items
                when personalized recommendations are insufficient (default: True)

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

        # Deduplicate variants: same product + same color = keep one
        # Different colors of same product only if customer has affinity
        scored = self._deduplicate_variants(scored, customer)

        # Apply diversity if requested (avoid showing 4 similar items)
        if diversity_factor > 0 and len(scored) > n:
            scored = self._diversify(scored, n, diversity_factor)

        results = scored[:n]

        # If we don't have enough personalized recommendations, fill with popular items
        if fill_with_popular and len(results) < n:
            # Get product IDs and refs already in results to avoid duplicates
            result_product_ids = {r.product.product_id for r in results}
            result_product_refs = {
                r.product.product_ref for r in results
                if r.product.product_ref
            }

            # Get popularity-based fallback recommendations
            needed = n - len(results)
            fallback = self._get_popularity_fallback(
                candidates=candidates,
                exclude_product_ids=result_product_ids,
                exclude_product_refs=result_product_refs,
                n=needed,
            )

            results.extend(fallback)

        return results

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
            # Must be in stock (skip if explicitly out_of_stock)
            if product.stock_status == "out_of_stock":
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

            # Skip if product not found or is in stock (only find alternatives for out_of_stock items)
            if not product or product.stock_status != "out_of_stock":
                continue

            # Find alternatives for this sold-out item
            alts = self.find_alternatives(product, products, n=n_per_item)
            if alts:
                alternatives[wishlist_product_id] = alts

        return alternatives
