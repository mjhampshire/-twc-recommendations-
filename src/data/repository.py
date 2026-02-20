"""Data repository layer.

This module provides the interface for fetching customer and product data.
Currently uses mock data for development. Replace with DynamoDB/ClickHouse
implementations for production.
"""
from typing import Optional
from datetime import datetime, timedelta

from ..models import (
    Customer, CustomerPreferences, PurchaseHistory, WishlistSummary,
    Product, ProductAttributes, ProductSizing, ProductMetrics,
)


class CustomerRepository:
    """Repository for customer data."""

    async def get_customer(self, retailer_id: str, customer_id: str) -> Optional[Customer]:
        """
        Fetch a customer profile by retailer and customer ID.

        In production, this would:
        1. Fetch base customer data from DynamoDB
        2. Aggregate purchase history from ClickHouse
        3. Aggregate wishlist data
        4. Compute derived metrics
        """
        # For now, return mock data
        return MOCK_CUSTOMERS.get(f"{retailer_id}:{customer_id}")

    async def get_vip_customers(self, retailer_id: str) -> list[Customer]:
        """Fetch all VIP customers for a retailer."""
        return [
            c for c in MOCK_CUSTOMERS.values()
            if c.retailer_id == retailer_id and c.is_vip
        ]


class ProductRepository:
    """Repository for product data."""

    async def get_product(self, retailer_id: str, product_id: str) -> Optional[Product]:
        """Fetch a single product."""
        products = MOCK_PRODUCTS.get(retailer_id, [])
        for p in products:
            if p.product_id == product_id:
                return p
        return None

    async def get_products_for_retailer(self, retailer_id: str) -> list[Product]:
        """
        Fetch all active products for a retailer.

        In production, this would:
        1. Fetch from product catalog (DynamoDB or Shopify)
        2. Enrich with performance metrics from ClickHouse
        3. Filter by availability
        """
        return MOCK_PRODUCTS.get(retailer_id, [])


# =============================================================================
# MOCK DATA FOR DEVELOPMENT
# =============================================================================

# Sample VIP customer with rich profile
_customer_sarah = Customer(
    customer_id="cust_001",
    retailer_id="retailer_luxe",
    email="sarah.j@email.com",
    name="Sarah Johnson",
    is_vip=True,
    preferences=CustomerPreferences(
        categories=["Dresses", "Tops", "Accessories"],
        colors=["Navy", "Black", "Cream", "Blush"],
        fabrics=["Silk", "Cashmere", "Linen"],
        styles=["Classic", "Minimalist"],
        brands=["Zimmermann", "Scanlan Theodore", "Camilla"],
        size_dress="10",
        size_top="S",
        price_sensitivity="luxury",
    ),
    purchase_history=PurchaseHistory(
        total_purchases=24,
        total_spend=18500.00,
        average_order_value=770.00,
        last_purchase_date=datetime.now() - timedelta(days=14),
        top_categories=["Dresses", "Tops", "Knitwear"],
        top_brands=["Zimmermann", "Scanlan Theodore"],
        top_colors=["Navy", "Black", "White"],
        recent_product_ids=["prod_001", "prod_015"],
    ),
    wishlist=WishlistSummary(
        total_wishlisted=12,
        active_wishlist_items=["prod_008", "prod_022"],
        wishlist_categories=["Dresses", "Accessories"],
        wishlist_brands=["Zimmermann", "Camilla"],
        wishlist_colors=["Navy", "Blush"],
    ),
)

# New customer with minimal data
_customer_emma = Customer(
    customer_id="cust_002",
    retailer_id="retailer_luxe",
    email="emma.w@email.com",
    name="Emma Williams",
    is_vip=True,
    preferences=CustomerPreferences(
        categories=["Dresses"],
        colors=["Red", "Black"],
        styles=["Bold"],
        size_dress="8",
    ),
    purchase_history=PurchaseHistory(
        total_purchases=0,
        total_spend=0,
    ),
    wishlist=WishlistSummary(
        total_wishlisted=0,
    ),
)

# Customer with strong purchase history but few stated preferences
_customer_michael = Customer(
    customer_id="cust_003",
    retailer_id="retailer_luxe",
    email="michael.c@email.com",
    name="Michael Chen",
    is_vip=True,
    preferences=CustomerPreferences(
        size_top="M",
        size_bottom="32",
    ),
    purchase_history=PurchaseHistory(
        total_purchases=18,
        total_spend=12000.00,
        average_order_value=666.00,
        last_purchase_date=datetime.now() - timedelta(days=7),
        top_categories=["Shirts", "Trousers", "Jackets"],
        top_brands=["Zegna", "Hugo Boss"],
        top_colors=["Navy", "Grey", "White"],
        recent_product_ids=["prod_050"],
    ),
    wishlist=WishlistSummary(
        total_wishlisted=5,
        active_wishlist_items=["prod_055"],
        wishlist_categories=["Jackets"],
        wishlist_brands=["Zegna"],
        wishlist_colors=["Navy"],
    ),
)

MOCK_CUSTOMERS = {
    "retailer_luxe:cust_001": _customer_sarah,
    "retailer_luxe:cust_002": _customer_emma,
    "retailer_luxe:cust_003": _customer_michael,
}


# Sample product catalog
def _create_product(
    product_id: str,
    name: str,
    price: float,
    category: str,
    brand: str,
    color: str,
    fabric: str = None,
    style: str = None,
    is_new: bool = False,
    purchases: int = 0,
    wishlisted: int = 0,
    trending: float = 0.0,
    sizes: list[str] = None,
) -> Product:
    return Product(
        product_id=product_id,
        retailer_id="retailer_luxe",
        name=name,
        price=price,
        attributes=ProductAttributes(
            category=category,
            brand=brand,
            color=color,
            colors=[color],
            fabric=fabric,
            fabrics=[fabric] if fabric else [],
            style=style,
        ),
        sizing=ProductSizing(
            available_sizes=sizes or ["8", "10", "12"],
            size_type="clothing",
        ),
        metrics=ProductMetrics(
            total_purchases=purchases,
            total_wishlisted=wishlisted,
            trending_score=trending,
        ),
        is_new_arrival=is_new,
        is_in_stock=True,
    )


MOCK_PRODUCTS = {
    "retailer_luxe": [
        # Dresses
        _create_product("prod_002", "Zimmermann Floral Midi Dress", 850, "Dresses", "Zimmermann", "Navy", "Silk", "Classic", purchases=45, wishlisted=120, trending=0.8, sizes=["8", "10", "12"]),
        _create_product("prod_003", "Scanlan Theodore Wrap Dress", 695, "Dresses", "Scanlan Theodore", "Black", "Silk", "Minimalist", purchases=32, wishlisted=85),
        _create_product("prod_004", "Camilla Printed Maxi", 1200, "Dresses", "Camilla", "Blush", "Silk", "Bohemian", purchases=28, wishlisted=95, trending=0.6),
        _create_product("prod_005", "Zimmermann Lace Mini", 720, "Dresses", "Zimmermann", "Cream", "Lace", "Romantic", is_new=True, purchases=8, wishlisted=45, trending=0.9),
        _create_product("prod_006", "Aje Structured Dress", 550, "Dresses", "Aje", "Red", "Cotton", "Bold", purchases=22, wishlisted=60),

        # Tops
        _create_product("prod_010", "Scanlan Theodore Silk Blouse", 395, "Tops", "Scanlan Theodore", "Cream", "Silk", "Classic", purchases=55, wishlisted=140, sizes=["XS", "S", "M", "L"]),
        _create_product("prod_011", "Zimmermann Embroidered Top", 495, "Tops", "Zimmermann", "Navy", "Cotton", "Classic", purchases=38, wishlisted=92, sizes=["S", "M"]),
        _create_product("prod_012", "Camilla Kaftan Top", 450, "Tops", "Camilla", "Blush", "Silk", "Bohemian", is_new=True, purchases=12, wishlisted=55, trending=0.75),

        # Accessories
        _create_product("prod_020", "Zimmermann Leather Belt", 195, "Accessories", "Zimmermann", "Black", "Leather", purchases=80, wishlisted=45),
        _create_product("prod_021", "Camilla Silk Scarf", 220, "Accessories", "Camilla", "Navy", "Silk", "Classic", purchases=65, wishlisted=88),
        _create_product("prod_022", "Scanlan Theodore Clutch", 350, "Accessories", "Scanlan Theodore", "Blush", "Leather", "Minimalist", is_new=True, purchases=15, wishlisted=72, trending=0.65),

        # Knitwear
        _create_product("prod_030", "Scanlan Theodore Cashmere Sweater", 550, "Knitwear", "Scanlan Theodore", "Cream", "Cashmere", "Classic", purchases=42, wishlisted=110, sizes=["S", "M", "L"]),
        _create_product("prod_031", "Zimmermann Knit Cardigan", 480, "Knitwear", "Zimmermann", "Navy", "Cashmere", "Classic", purchases=35, wishlisted=78),

        # Out of stock item (should be filtered)
        Product(
            product_id="prod_099",
            retailer_id="retailer_luxe",
            name="Zimmermann Sold Out Dress",
            price=900,
            attributes=ProductAttributes(category="Dresses", brand="Zimmermann", color="Navy"),
            is_in_stock=False,
        ),
    ]
}
