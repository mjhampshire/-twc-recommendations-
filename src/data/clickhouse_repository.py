"""ClickHouse repository layer.

Fetches customer and product data from ClickHouse and transforms
it into the recommendation engine's domain models.

Note: clickhouse-connect is synchronous. For FastAPI async endpoints,
these methods can be called directly (ClickHouse queries are fast) or
wrapped with run_in_executor if needed.
"""
import json
from typing import Optional
from datetime import datetime, timedelta

import clickhouse_connect

from ..models import (
    Customer, CustomerPreferences, CustomerDislikes, PreferenceItem, PreferenceSource,
    PurchaseHistory, WishlistSummary, BrowsingBehavior,
    Product, ProductAttributes, ProductSizing, ProductMetrics,
)
from ..config.clickhouse import ClickHouseConfig


def _get_client(config: ClickHouseConfig):
    """Create a ClickHouse client from config."""
    return clickhouse_connect.get_client(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        database=config.database,
        secure=config.secure,
    )


class ClickHouseCustomerRepository:
    """Repository for customer data from ClickHouse."""

    def __init__(self, config: ClickHouseConfig):
        self.config = config

    def get_customer(self, tenant_id: str, customer_id: str) -> Optional[Customer]:
        """
        Fetch and assemble a complete customer profile.

        Args:
            tenant_id: The retailer/tenant ID (e.g., "camillaandmarc-au")
            customer_id: The customer ID (customerId from preferences table)

        Returns:
            Complete Customer model with all signals populated
        """
        client = _get_client(self.config)

        try:
            # Fetch all data in parallel (ClickHouse is fast)
            preferences_data = self._fetch_preferences(client, tenant_id, customer_id)
            purchase_data = self._fetch_purchase_history(client, tenant_id, customer_id)
            wishlist_data = self._fetch_wishlist(client, tenant_id, customer_id)
            browsing_data = self._fetch_browsing(client, tenant_id, customer_id)

            if not preferences_data and not purchase_data and not wishlist_data:
                # Customer not found in any table
                return None

            # Parse preferences JSON
            preferences, dislikes = self._parse_preferences_json(
                preferences_data.get("preferences", "{}") if preferences_data else "{}"
            )

            return Customer(
                customer_id=customer_id,
                retailer_id=tenant_id,
                is_vip=True,  # Could be derived from purchase history
                preferences=preferences,
                dislikes=dislikes,
                purchase_history=purchase_data or PurchaseHistory(),
                wishlist=wishlist_data or WishlistSummary(),
                browsing=browsing_data or BrowsingBehavior(),
            )
        finally:
            client.close()

    def _fetch_preferences(self, client, tenant_id: str, customer_id: str) -> Optional[dict]:
        """Fetch customer preferences from preferences table."""
        # Get the primary preference (isPrimary=1) or most recent
        query = """
            SELECT
                customerId,
                preferences,
                rangeName,
                updatedAt
            FROM PREFERENCES
            WHERE tenantId = {tenant_id:String}
              AND customerId = {customer_id:String}
              AND deleted = '0'
            ORDER BY isPrimary DESC, updatedAt DESC
            LIMIT 1
        """

        result = client.query(
            query,
            parameters={"tenant_id": tenant_id, "customer_id": customer_id}
        )

        if result.row_count == 0:
            return None

        row = result.first_row
        return {
            "customer_id": row[0],
            "preferences": row[1],
            "range_name": row[2],
            "updated_at": row[3],
        }

    def _fetch_purchase_history(self, client, tenant_id: str, customer_id: str) -> PurchaseHistory:
        """Fetch and aggregate purchase history."""
        # Aggregate order stats
        stats_query = """
            SELECT
                count(DISTINCT o.orderId) as total_orders,
                sum(o.amount) as total_spend,
                avg(o.amount) as avg_order_value,
                max(o.orderDate) as last_purchase_date
            FROM ALLORDERS o
            WHERE o.tenantId = {tenant_id:String}
              AND o.customerRef = {customer_id:String}
        """

        stats_result = client.query(
            stats_query,
            parameters={"tenant_id": tenant_id, "customer_id": customer_id}
        )

        if stats_result.row_count == 0:
            return PurchaseHistory()

        stats = stats_result.first_row
        total_orders = stats[0] or 0
        total_spend = float(stats[1] or 0)
        avg_order_value = float(stats[2] or 0)
        last_purchase = stats[3]

        # Get top categories and brands from order lines joined to products
        top_query = """
            SELECT
                p.category,
                p.brand,
                p.color,
                count(*) as cnt
            FROM ORDERLINE ol
            JOIN TWCVARIANT p ON ol.variantRef = p.variantRef AND ol.tenantId = p.tenantId
            WHERE ol.tenantId = {tenant_id:String}
              AND ol.customerRef = {customer_id:String}
            GROUP BY p.category, p.brand, p.color
            ORDER BY cnt DESC
            LIMIT 20
        """

        top_result = client.query(
            top_query,
            parameters={"tenant_id": tenant_id, "customer_id": customer_id}
        )

        # Aggregate top categories, brands, colors
        category_counts = {}
        brand_counts = {}
        color_counts = {}

        for row in top_result.result_rows:
            category, brand, color, cnt = row
            if category:
                category_counts[category] = category_counts.get(category, 0) + cnt
            if brand:
                brand_counts[brand] = brand_counts.get(brand, 0) + cnt
            if color:
                color_counts[color] = color_counts.get(color, 0) + cnt

        top_categories = sorted(category_counts.keys(), key=lambda x: category_counts[x], reverse=True)[:5]
        top_brands = sorted(brand_counts.keys(), key=lambda x: brand_counts[x], reverse=True)[:5]
        top_colors = sorted(color_counts.keys(), key=lambda x: color_counts[x], reverse=True)[:5]

        # Get recent product IDs
        recent_query = """
            SELECT DISTINCT ol.variantRef
            FROM ORDERLINE ol
            WHERE ol.tenantId = {tenant_id:String}
              AND ol.customerRef = {customer_id:String}
            ORDER BY ol.orderLineDate DESC
            LIMIT 10
        """

        recent_result = client.query(
            recent_query,
            parameters={"tenant_id": tenant_id, "customer_id": customer_id}
        )
        recent_product_ids = [row[0] for row in recent_result.result_rows]

        return PurchaseHistory(
            total_purchases=total_orders,
            total_spend=total_spend,
            average_order_value=avg_order_value,
            last_purchase_date=last_purchase,
            top_categories=top_categories,
            top_brands=top_brands,
            top_colors=top_colors,
            recent_product_ids=recent_product_ids,
        )

    def _fetch_wishlist(self, client, tenant_id: str, customer_id: str) -> WishlistSummary:
        """Fetch wishlist summary."""
        query = """
            SELECT
                wi.productRef,
                wi.category,
                wi.brandId
            FROM TWCWISHLIST w
            JOIN WISHLISTITEM wi ON w.wishlistId = wi.wishlistId AND w.tenantId = wi.tenantId
            WHERE w.tenantId = {tenant_id:String}
              AND w.customerId = {customer_id:String}
              AND w.deleted = '0'
              AND wi.deleted = '0'
              AND wi.purchased = '0'
        """

        result = client.query(
            query,
            parameters={"tenant_id": tenant_id, "customer_id": customer_id}
        )

        if result.row_count == 0:
            return WishlistSummary()

        product_ids = []
        category_counts = {}
        brand_counts = {}

        for row in result.result_rows:
            product_ref, category, brand_id = row
            if product_ref:
                product_ids.append(product_ref)
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1
            if brand_id:
                brand_counts[brand_id] = brand_counts.get(brand_id, 0) + 1

        return WishlistSummary(
            total_wishlisted=len(product_ids),
            active_wishlist_items=product_ids[:20],  # Limit to 20
            wishlist_categories=sorted(category_counts.keys(), key=lambda x: category_counts[x], reverse=True)[:5],
            wishlist_brands=sorted(brand_counts.keys(), key=lambda x: brand_counts[x], reverse=True)[:5],
            wishlist_colors=[],  # Would need product join for colors
        )

    def _fetch_browsing(self, client, tenant_id: str, customer_id: str) -> BrowsingBehavior:
        """Fetch browsing behavior from clickstream."""
        # Last 30 days of browsing
        cutoff_date = datetime.now() - timedelta(days=30)

        query = """
            SELECT
                productRef,
                productType,
                brand,
                eventType,
                timeStamp
            FROM TWCCLICKSTREAM
            WHERE tenantId = {tenant_id:String}
              AND customerRef = {customer_id:String}
              AND timeStamp >= {cutoff:DateTime}
            ORDER BY timeStamp DESC
            LIMIT 500
        """

        result = client.query(
            query,
            parameters={
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "cutoff": cutoff_date,
            }
        )

        if result.row_count == 0:
            return BrowsingBehavior()

        viewed_products = []
        category_counts = {}
        brand_counts = {}
        cart_products = []
        last_browse = None
        sessions = set()

        for row in result.result_rows:
            product_ref, product_type, brand, event_type, timestamp = row

            if last_browse is None:
                last_browse = timestamp

            # Track unique sessions (by date)
            sessions.add(timestamp.date())

            if product_ref and product_ref not in viewed_products:
                viewed_products.append(product_ref)

            if product_type:
                category_counts[product_type] = category_counts.get(product_type, 0) + 1
            if brand:
                brand_counts[brand] = brand_counts.get(brand, 0) + 1

            # Track cart events
            if event_type and 'cart' in event_type.lower() and product_ref:
                if product_ref not in cart_products:
                    cart_products.append(product_ref)

        return BrowsingBehavior(
            viewed_product_ids=viewed_products[:20],
            view_count_last_30_days=result.row_count,
            viewed_categories=sorted(category_counts.keys(), key=lambda x: category_counts[x], reverse=True)[:5],
            viewed_brands=sorted(brand_counts.keys(), key=lambda x: brand_counts[x], reverse=True)[:5],
            viewed_colors=[],  # Would need product join
            cart_product_ids=cart_products[:10],
            abandoned_cart_product_ids=[],  # Would need purchase cross-reference
            cart_categories=[],
            cart_brands=[],
            last_browse_date=last_browse,
            sessions_last_30_days=len(sessions),
        )

    def _parse_preferences_json(self, preferences_json: str) -> tuple[CustomerPreferences, CustomerDislikes]:
        """
        Parse the retailer-specific preferences JSON into our domain models.

        Handles the camillaandmarc-au format:
        {
            "dresses": [{"id": "size_8", "value": "8", "source": "staff"}],
            "categories": [{"id": "evening", "value": "evening", "source": "staff"}],
            "colours": [{"id": "black", "value": "black", "source": "staff"}],
            ...
        }

        Dislikes are items with "dislike": true flag.
        """
        try:
            data = json.loads(preferences_json) if preferences_json else {}
        except json.JSONDecodeError:
            data = {}

        preferences = CustomerPreferences()
        dislikes = CustomerDislikes()

        # Category preferences
        for item in data.get("categories", []):
            pref_item = self._to_preference_item(item)
            if item.get("dislike"):
                dislikes.categories.append(pref_item)
            else:
                preferences.categories.append(pref_item)

        # Color preferences
        for item in data.get("colours", []):
            pref_item = self._to_preference_item(item)
            if item.get("dislike"):
                dislikes.colors.append(pref_item)
            else:
                preferences.colors.append(pref_item)

        # Size preferences by category
        # Map category keys to our size fields
        size_mapping = {
            "dresses": "size_dress",
            "tops": "size_top",
            "bottoms": "size_bottom",
            "blazers": "size_top",  # Use top size for blazers
            "outerwear": "size_top",
            "knitwear": "size_top",
            "denim": "size_bottom",
            "footwear": "size_shoe",
        }

        for category_key, size_field in size_mapping.items():
            items = data.get(category_key, [])
            if items:
                # Take first size value
                first_item = items[0]
                size_value = first_item.get("value", "")
                if size_value and not getattr(preferences, size_field, None):
                    setattr(preferences, size_field, size_value)

        # Note: brands, fabrics, styles would be extracted similarly if present
        # Currently not in the camillaandmarc schema

        return preferences, dislikes

    def _to_preference_item(self, item: dict) -> PreferenceItem:
        """Convert a preference dict to PreferenceItem."""
        source_str = item.get("source", "staff")
        source = PreferenceSource.CUSTOMER if source_str == "customer" else PreferenceSource.STAFF
        return PreferenceItem(
            value=item.get("value", item.get("id", "")),
            source=source,
        )


class ClickHouseProductRepository:
    """Repository for product data from ClickHouse."""

    def __init__(self, config: ClickHouseConfig):
        self.config = config

    def get_product(self, tenant_id: str, product_id: str) -> Optional[Product]:
        """Fetch a single product by variant ref."""
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    productRef,
                    variantRef,
                    productName,
                    variantName,
                    brand,
                    category,
                    color,
                    size,
                    price,
                    imageUrl,
                    productUrl,
                    inStock
                FROM TWCVARIANT
                WHERE tenantId = {tenant_id:String}
                  AND variantRef = {product_id:String}
                LIMIT 1
            """

            result = client.query(
                query,
                parameters={"tenant_id": tenant_id, "product_id": product_id}
            )

            if result.row_count == 0:
                return None

            return self._row_to_product(tenant_id, result.first_row)
        finally:
            client.close()

    def get_products_for_retailer(
        self,
        tenant_id: str,
        in_stock_only: bool = False,  # NOTE: inStock not yet populated - frontend handles filtering
        limit: int = 1000,
    ) -> list[Product]:
        """Fetch all active products for a retailer."""
        client = _get_client(self.config)

        try:
            stock_filter = "AND inStock = 1" if in_stock_only else ""

            query = f"""
                SELECT
                    productRef,
                    variantRef,
                    productName,
                    variantName,
                    brand,
                    category,
                    color,
                    size,
                    price,
                    imageUrl,
                    productUrl,
                    inStock
                FROM TWCVARIANT
                WHERE tenantId = {{tenant_id:String}}
                  {stock_filter}
                ORDER BY updatedAt DESC
                LIMIT {{limit:UInt32}}
            """

            result = client.query(
                query,
                parameters={"tenant_id": tenant_id, "limit": limit}
            )

            return [self._row_to_product(tenant_id, row) for row in result.result_rows]
        finally:
            client.close()

    def _row_to_product(self, tenant_id: str, row: tuple) -> Product:
        """Convert a database row to a Product model."""
        (
            product_ref, variant_ref, product_name, variant_name,
            brand, category, color, size, price, image_url, product_url, in_stock
        ) = row

        return Product(
            product_id=variant_ref,
            retailer_id=tenant_id,
            name=product_name or "",
            price=float(price or 0),
            image_url=image_url,
            product_url=product_url,
            attributes=ProductAttributes(
                category=category,
                brand=brand,
                color=color,
                colors=[color] if color else [],
                # fabric and style not available yet
            ),
            sizing=ProductSizing(
                available_sizes=[size] if size else [],
                size_type="AU",  # Assuming AU sizing
            ),
            is_in_stock=bool(in_stock),
        )
