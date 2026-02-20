"""Product scoring logic for recommendations.

This module contains the core scoring algorithm that evaluates how well
a product matches a customer's profile based on configurable weights.
"""
from typing import Optional
from ..models import Customer, Product, ScoredProduct
from ..config import RecommendationWeights, DEFAULT_WEIGHTS


def _normalize(value: float, max_value: float = 1.0) -> float:
    """Normalize a value to 0-1 range."""
    if max_value <= 0:
        return 0.0
    return min(max(value / max_value, 0.0), 1.0)


def _list_overlap_score(list1: list[str], list2: list[str]) -> float:
    """Calculate overlap score between two lists (case-insensitive)."""
    if not list1 or not list2:
        return 0.0
    set1 = {item.lower() for item in list1}
    set2 = {item.lower() for item in list2}
    intersection = len(set1 & set2)
    # Jaccard-like but biased toward matching any of customer's preferences
    return intersection / len(set1) if set1 else 0.0


def _item_in_list(item: Optional[str], items: list[str]) -> float:
    """Check if item is in list (case-insensitive), return 1.0 or 0.0."""
    if not item or not items:
        return 0.0
    return 1.0 if item.lower() in {i.lower() for i in items} else 0.0


def score_product(
    product: Product,
    customer: Customer,
    weights: RecommendationWeights = DEFAULT_WEIGHTS,
) -> ScoredProduct:
    """
    Score a product for a customer based on their profile and configurable weights.

    Returns a ScoredProduct with the total score, breakdown, and human-readable reasons.
    """
    scores: dict[str, float] = {}
    reasons: list[str] = []

    prefs = customer.preferences
    history = customer.purchase_history
    wishlist = customer.wishlist
    attrs = product.attributes

    # --- Preference Matching ---

    # Category match
    if attrs.category:
        cat_score = _item_in_list(attrs.category, prefs.categories)
        scores['preference_category'] = cat_score * weights.preference_category
        if cat_score > 0:
            reasons.append(f"Matches preferred category: {attrs.category}")

    # Color match
    color_items = attrs.colors if attrs.colors else ([attrs.color] if attrs.color else [])
    color_score = _list_overlap_score(prefs.colors, color_items)
    scores['preference_color'] = color_score * weights.preference_color
    if color_score > 0:
        matched = [c for c in color_items if c.lower() in {p.lower() for p in prefs.colors}]
        reasons.append(f"Matches preferred color: {', '.join(matched)}")

    # Fabric match
    fabric_items = attrs.fabrics if attrs.fabrics else ([attrs.fabric] if attrs.fabric else [])
    fabric_score = _list_overlap_score(prefs.fabrics, fabric_items)
    scores['preference_fabric'] = fabric_score * weights.preference_fabric
    if fabric_score > 0:
        matched = [f for f in fabric_items if f.lower() in {p.lower() for p in prefs.fabrics}]
        reasons.append(f"Matches preferred fabric: {', '.join(matched)}")

    # Style match
    if attrs.style:
        style_score = _item_in_list(attrs.style, prefs.styles)
        scores['preference_style'] = style_score * weights.preference_style
        if style_score > 0:
            reasons.append(f"Matches preferred style: {attrs.style}")

    # Brand match
    if attrs.brand:
        brand_score = _item_in_list(attrs.brand, prefs.brands)
        scores['preference_brand'] = brand_score * weights.preference_brand
        if brand_score > 0:
            reasons.append(f"Preferred brand: {attrs.brand}")

    # --- Purchase History Matching ---

    # Category from history
    if attrs.category:
        hist_cat_score = _item_in_list(attrs.category, history.top_categories)
        scores['purchase_history_category'] = hist_cat_score * weights.purchase_history_category
        if hist_cat_score > 0 and 'preference_category' not in [r.split(':')[0] for r in reasons]:
            reasons.append(f"Previously purchased: {attrs.category}")

    # Brand from history
    if attrs.brand:
        hist_brand_score = _item_in_list(attrs.brand, history.top_brands)
        scores['purchase_history_brand'] = hist_brand_score * weights.purchase_history_brand
        if hist_brand_score > 0 and f"Preferred brand: {attrs.brand}" not in reasons:
            reasons.append(f"Previously purchased from: {attrs.brand}")

    # Color from history
    hist_color_score = _list_overlap_score(history.top_colors, color_items)
    scores['purchase_history_color'] = hist_color_score * weights.purchase_history_color

    # --- Wishlist Similarity ---

    # Check if product matches wishlist patterns
    wishlist_score = 0.0
    wishlist_matches = 0

    if attrs.category and attrs.category.lower() in {c.lower() for c in wishlist.wishlist_categories}:
        wishlist_score += 0.4
        wishlist_matches += 1
    if attrs.brand and attrs.brand.lower() in {b.lower() for b in wishlist.wishlist_brands}:
        wishlist_score += 0.4
        wishlist_matches += 1
    if _list_overlap_score(wishlist.wishlist_colors, color_items) > 0:
        wishlist_score += 0.2
        wishlist_matches += 1

    scores['wishlist_similarity'] = min(wishlist_score, 1.0) * weights.wishlist_similarity
    if wishlist_matches >= 2:
        reasons.append("Similar to wishlisted items")

    # --- Product Performance ---

    # Popularity (normalize against reasonable max)
    popularity_score = _normalize(product.metrics.total_purchases, 100) * 0.5
    popularity_score += _normalize(product.metrics.total_wishlisted, 200) * 0.3
    popularity_score += _normalize(product.metrics.trending_score, 1.0) * 0.2
    scores['product_popularity'] = popularity_score * weights.product_popularity
    if product.metrics.trending_score > 0.7:
        reasons.append("Trending now")

    # --- New Arrival Boost ---

    if product.is_new_arrival:
        scores['new_arrival_boost'] = weights.new_arrival_boost
        reasons.append("New arrival")
    else:
        scores['new_arrival_boost'] = 0.0

    # --- Size Match ---

    size_score = 0.0
    if product.sizing.available_sizes:
        customer_sizes = []
        if prefs.size_top:
            customer_sizes.append(prefs.size_top)
        if prefs.size_bottom:
            customer_sizes.append(prefs.size_bottom)
        if prefs.size_dress:
            customer_sizes.append(prefs.size_dress)
        if prefs.size_shoe:
            customer_sizes.append(prefs.size_shoe)

        if customer_sizes:
            available_lower = {s.lower() for s in product.sizing.available_sizes}
            if any(s.lower() in available_lower for s in customer_sizes):
                size_score = 1.0
                reasons.append("Available in your size")

    scores['size_match_boost'] = size_score * weights.size_match_boost

    # --- Calculate Total Score ---

    total_score = sum(scores.values())

    # Normalize by total weights for interpretability
    total_weight = weights.total_weight()
    if total_weight > 0:
        normalized_score = total_score / total_weight
    else:
        normalized_score = total_score

    return ScoredProduct(
        product=product,
        score=normalized_score,
        score_breakdown=scores,
        reasons=reasons[:5],  # Limit to top 5 reasons
    )
