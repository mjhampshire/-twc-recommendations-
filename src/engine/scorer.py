"""Product scoring logic for recommendations.

This module contains the core scoring algorithm that evaluates how well
a product matches a customer's profile based on configurable weights.
"""
from typing import Optional
from ..models import Customer, Product, ScoredProduct, PreferenceItem, PreferenceSource, CustomerDislikes
from ..config import RecommendationWeights, DEFAULT_WEIGHTS


def _normalize(value: float, max_value: float = 1.0) -> float:
    """Normalize a value to 0-1 range."""
    if max_value <= 0:
        return 0.0
    return min(max(value / max_value, 0.0), 1.0)


def _extract_values(pref_items: list[PreferenceItem]) -> list[str]:
    """Extract just the values from a list of PreferenceItems."""
    return [item.value for item in pref_items]


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


def _item_in_pref_list(
    item: Optional[str],
    pref_items: list[PreferenceItem],
    weights: RecommendationWeights,
) -> float:
    """Check if item matches a preference list, applying source multiplier.

    Returns weighted score (0.0 if no match, multiplied score if match).
    """
    if not item or not pref_items:
        return 0.0
    item_lower = item.lower()
    for pref in pref_items:
        if pref.value.lower() == item_lower:
            multiplier = (
                weights.customer_source_multiplier
                if pref.source == PreferenceSource.CUSTOMER
                else weights.staff_source_multiplier
            )
            return 1.0 * multiplier
    return 0.0


def _pref_list_overlap_score(
    pref_items: list[PreferenceItem],
    product_values: list[str],
    weights: RecommendationWeights,
) -> float:
    """Calculate overlap score with source-weighted preferences.

    For multiple matches, uses the highest source multiplier found.
    """
    if not pref_items or not product_values:
        return 0.0

    product_set = {v.lower() for v in product_values}
    matches = []

    for pref in pref_items:
        if pref.value.lower() in product_set:
            multiplier = (
                weights.customer_source_multiplier
                if pref.source == PreferenceSource.CUSTOMER
                else weights.staff_source_multiplier
            )
            matches.append(multiplier)

    if not matches:
        return 0.0

    # Base overlap score (proportion of preferences matched)
    base_score = len(matches) / len(pref_items)
    # Apply the highest multiplier among matches
    return base_score * max(matches)


def matches_dislikes(product: Product, dislikes: CustomerDislikes) -> bool:
    """Check if a product matches any customer dislikes.

    Returns True if product should be filtered out.
    """
    attrs = product.attributes

    # Check category
    if attrs.category:
        dislike_categories = {d.value.lower() for d in dislikes.categories}
        if attrs.category.lower() in dislike_categories:
            return True

    # Check brand
    if attrs.brand:
        dislike_brands = {d.value.lower() for d in dislikes.brands}
        if attrs.brand.lower() in dislike_brands:
            return True

    # Check style
    if attrs.style:
        dislike_styles = {d.value.lower() for d in dislikes.styles}
        if attrs.style.lower() in dislike_styles:
            return True

    # Check colors
    product_colors = attrs.colors if attrs.colors else ([attrs.color] if attrs.color else [])
    if product_colors:
        dislike_colors = {d.value.lower() for d in dislikes.colors}
        if any(c.lower() in dislike_colors for c in product_colors):
            return True

    # Check fabrics
    product_fabrics = attrs.fabrics if attrs.fabrics else ([attrs.fabric] if attrs.fabric else [])
    if product_fabrics:
        dislike_fabrics = {d.value.lower() for d in dislikes.fabrics}
        if any(f.lower() in dislike_fabrics for f in product_fabrics):
            return True

    return False


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

    # --- Preference Matching (with source multipliers) ---

    # Category match
    if attrs.category:
        cat_score = _item_in_pref_list(attrs.category, prefs.categories, weights)
        scores['preference_category'] = cat_score * weights.preference_category
        if cat_score > 0:
            reasons.append(f"Matches preferred category: {attrs.category}")

    # Color match
    color_items = attrs.colors if attrs.colors else ([attrs.color] if attrs.color else [])
    color_score = _pref_list_overlap_score(prefs.colors, color_items, weights)
    scores['preference_color'] = color_score * weights.preference_color
    if color_score > 0:
        pref_color_values = {p.value.lower() for p in prefs.colors}
        matched = [c for c in color_items if c.lower() in pref_color_values]
        reasons.append(f"Matches preferred color: {', '.join(matched)}")

    # Fabric match
    fabric_items = attrs.fabrics if attrs.fabrics else ([attrs.fabric] if attrs.fabric else [])
    fabric_score = _pref_list_overlap_score(prefs.fabrics, fabric_items, weights)
    scores['preference_fabric'] = fabric_score * weights.preference_fabric
    if fabric_score > 0:
        pref_fabric_values = {p.value.lower() for p in prefs.fabrics}
        matched = [f for f in fabric_items if f.lower() in pref_fabric_values]
        reasons.append(f"Matches preferred fabric: {', '.join(matched)}")

    # Style match
    if attrs.style:
        style_score = _item_in_pref_list(attrs.style, prefs.styles, weights)
        scores['preference_style'] = style_score * weights.preference_style
        if style_score > 0:
            reasons.append(f"Matches preferred style: {attrs.style}")

    # Brand match
    if attrs.brand:
        brand_score = _item_in_pref_list(attrs.brand, prefs.brands, weights)
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

    # --- Browsing Behavior ---

    browsing = customer.browsing

    # Category they've been browsing
    if attrs.category:
        browse_cat_score = _item_in_list(attrs.category, browsing.viewed_categories)
        scores['browsing_viewed_category'] = browse_cat_score * weights.browsing_viewed_category
        if browse_cat_score > 0 and not any("category" in r.lower() for r in reasons):
            reasons.append(f"Recently browsed: {attrs.category}")

    # Brands they've been viewing
    if attrs.brand:
        browse_brand_score = _item_in_list(attrs.brand, browsing.viewed_brands)
        scores['browsing_viewed_brand'] = browse_brand_score * weights.browsing_viewed_brand

    # Cart similarity (high intent signal!)
    cart_score = 0.0
    cart_matches = 0

    # Check if matches cart patterns
    if attrs.category and attrs.category.lower() in {c.lower() for c in browsing.cart_categories}:
        cart_score += 0.5
        cart_matches += 1
    if attrs.brand and attrs.brand.lower() in {b.lower() for b in browsing.cart_brands}:
        cart_score += 0.5
        cart_matches += 1

    scores['browsing_cart_similarity'] = min(cart_score, 1.0) * weights.browsing_cart_similarity
    if cart_matches >= 1:
        reasons.append("Similar to items in your cart")

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
