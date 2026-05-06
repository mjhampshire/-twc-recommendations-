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

    def _get_customer_lookup_field(self, customer_id: str) -> str:
        """Determine lookup field based on customer_id format.

        Returns 'customerEmail' if customer_id contains '@', otherwise 'customerRef'.
        """
        return 'customerEmail' if '@' in customer_id else 'customerRef'

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
            # Determine lookup field based on customer_id format
            lookup_field = self._get_customer_lookup_field(customer_id)

            # Fetch all data in parallel (ClickHouse is fast)
            preferences_data = self._fetch_preferences(client, tenant_id, customer_id, lookup_field)
            purchase_data = self._fetch_purchase_history(client, tenant_id, customer_id, lookup_field)
            wishlist_data = self._fetch_wishlist(client, tenant_id, customer_id, lookup_field)
            browsing_data = self._fetch_browsing(client, tenant_id, customer_id, lookup_field)

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

    def _fetch_preferences(self, client, tenant_id: str, customer_id: str, lookup_field: str) -> Optional[dict]:
        """Fetch customer preferences from preferences table."""
        # Get the primary preference (isPrimary=1) or most recent
        query = f"""
            SELECT
                customerId,
                preferences,
                rangeName,
                updatedAt
            FROM TWCPREFERENCES FINAL
            WHERE tenantId = {{tenant_id:String}}
              AND {lookup_field} = {{customer_id:String}}
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

    def _fetch_purchase_history(self, client, tenant_id: str, customer_id: str, lookup_field: str) -> PurchaseHistory:
        """Fetch and aggregate purchase history."""
        # Aggregate order stats
        stats_query = f"""
            SELECT
                count(DISTINCT o.orderId) as total_orders,
                sum(o.amount) as total_spend,
                avg(o.amount) as avg_order_value,
                max(o.orderDate) as last_purchase_date
            FROM TWCALLORDERS o FINAL
            WHERE o.tenantId = {{tenant_id:String}}
              AND o.{lookup_field} = {{customer_id:String}}
              AND o.eventType != 'DELETE'
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
        top_query = f"""
            SELECT
                p.category,
                p.brand,
                p.color,
                count(*) as cnt
            FROM ORDERLINE ol FINAL
            JOIN TWCVARIANT p FINAL ON ol.variantRef = p.variantRef AND ol.tenantId = p.tenantId
            WHERE ol.tenantId = {{tenant_id:String}}
              AND ol.{lookup_field} = {{customer_id:String}}
              AND ol.eventType != 'DELETE'
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
        recent_query = f"""
            SELECT DISTINCT ol.variantRef
            FROM ORDERLINE ol FINAL
            WHERE ol.tenantId = {{tenant_id:String}}
              AND ol.{lookup_field} = {{customer_id:String}}
              AND ol.eventType != 'DELETE'
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

    def _fetch_wishlist(self, client, tenant_id: str, customer_id: str, lookup_field: str) -> WishlistSummary:
        """Fetch wishlist summary with product colors."""
        query = f"""
            SELECT
                wi.productRef,
                wi.category,
                wi.brandId,
                v.color
            FROM TWCWISHLIST w FINAL
            JOIN WISHLISTITEM wi FINAL ON w.wishlistId = wi.wishlistId AND w.tenantId = wi.tenantId
            LEFT JOIN TWCVARIANT v FINAL ON wi.variantRef = v.variantRef AND wi.tenantId = v.tenantId
            WHERE w.tenantId = {{tenant_id:String}}
              AND w.{lookup_field} = {{customer_id:String}}
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
        color_counts = {}

        for row in result.result_rows:
            product_ref, category, brand_id, color = row
            if product_ref:
                product_ids.append(product_ref)
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1
            if brand_id:
                brand_counts[brand_id] = brand_counts.get(brand_id, 0) + 1
            if color:
                color_counts[color] = color_counts.get(color, 0) + 1

        return WishlistSummary(
            total_wishlisted=len(product_ids),
            active_wishlist_items=product_ids[:20],  # Limit to 20
            wishlist_categories=sorted(category_counts.keys(), key=lambda x: category_counts[x], reverse=True)[:5],
            wishlist_brands=sorted(brand_counts.keys(), key=lambda x: brand_counts[x], reverse=True)[:5],
            wishlist_colors=sorted(color_counts.keys(), key=lambda x: color_counts[x], reverse=True)[:5],
        )

    def _fetch_browsing(self, client, tenant_id: str, customer_id: str, lookup_field: str) -> BrowsingBehavior:
        """Fetch browsing behavior from clickstream with product colors."""
        # Last 30 days of browsing
        cutoff_date = datetime.now() - timedelta(days=30)

        query = f"""
            SELECT
                c.productRef,
                c.productType,
                c.brand,
                c.eventType,
                c.timeStamp,
                v.color
            FROM TWCCLICKSTREAM c
            LEFT JOIN TWCVARIANT v FINAL ON c.variantRef = v.variantRef AND c.tenantId = v.tenantId
            WHERE c.tenantId = {{tenant_id:String}}
              AND c.{lookup_field} = {{customer_id:String}}
              AND c.timeStamp >= {{cutoff:DateTime}}
            ORDER BY c.timeStamp DESC
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
        color_counts = {}
        cart_products = []
        cart_categories = {}
        cart_brands = {}
        last_browse = None
        sessions = set()

        for row in result.result_rows:
            product_ref, product_type, brand, event_type, timestamp, color = row

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
            if color:
                color_counts[color] = color_counts.get(color, 0) + 1

            # Track cart events
            if event_type and 'cart' in event_type.lower() and product_ref:
                if product_ref not in cart_products:
                    cart_products.append(product_ref)
                if product_type:
                    cart_categories[product_type] = cart_categories.get(product_type, 0) + 1
                if brand:
                    cart_brands[brand] = cart_brands.get(brand, 0) + 1

        return BrowsingBehavior(
            viewed_product_ids=viewed_products[:20],
            view_count_last_30_days=result.row_count,
            viewed_categories=sorted(category_counts.keys(), key=lambda x: category_counts[x], reverse=True)[:5],
            viewed_brands=sorted(brand_counts.keys(), key=lambda x: brand_counts[x], reverse=True)[:5],
            viewed_colors=sorted(color_counts.keys(), key=lambda x: color_counts[x], reverse=True)[:5],
            cart_product_ids=cart_products[:10],
            abandoned_cart_product_ids=[],  # Would need purchase cross-reference
            cart_categories=sorted(cart_categories.keys(), key=lambda x: cart_categories[x], reverse=True)[:5],
            cart_brands=sorted(cart_brands.keys(), key=lambda x: cart_brands[x], reverse=True)[:5],
            last_browse_date=last_browse,
            sessions_last_30_days=len(sessions),
        )

    def _parse_preferences_json(self, preferences_json: str) -> tuple[CustomerPreferences, CustomerDislikes]:
        """
        Parse retailer-specific preferences JSON into our domain models.

        Uses pattern matching to handle different retailer schemas:
        - Single-brand: {"categories": [...], "colours": [...], "dresses": [sizes]}
        - Multi-brand womens: {"womens_brands": [...], "womens_categories": [...]}
        - Multi-brand mens: {"mens_brands": [...], "mens_clothing": [...]}

        Keys are matched using substring patterns:
        - *brand* → brands
        - *color*, *colour* → colors
        - *categor*, *clothing*, *footwear*, *accessor*, *lifestyle* → categories
        - *fit*, *style*, *cut* → styles
        - *occasion* → occasions
        - *fabric* → fabrics
        - Garment keys (dresses, tops, etc.) → sizes

        Dislikes are items with "dislike": true flag.
        """
        try:
            data = json.loads(preferences_json) if preferences_json else {}
        except json.JSONDecodeError:
            data = {}

        preferences = CustomerPreferences()
        dislikes = CustomerDislikes()

        # Size key mappings - these keys contain size values, not preference values
        size_key_mapping = {
            "dresses": "size_dress",
            "dress": "size_dress",
            "tops": "size_top",
            "top": "size_top",
            "bottoms": "size_bottom",
            "bottom": "size_bottom",
            "blazers": "size_top",
            "blazer": "size_top",
            "outerwear": "size_top",
            "knitwear": "size_top",
            "knit": "size_top",
            "denim": "size_bottom",
            "jeans": "size_bottom",
            "pants": "size_bottom",
            "skirts": "size_bottom",
            "skirt": "size_bottom",
            "shorts": "size_bottom",
            "footwear": "size_shoe",
            "shoes": "size_shoe",
            "shoe": "size_shoe",
            "sweaters": "size_top",
            "shirts": "size_top",
            "jackets": "size_top",
            "coats": "size_top",
        }

        for key, items in data.items():
            if not isinstance(items, list) or not items:
                continue

            key_lower = key.lower()

            # Check if this is a size key first
            size_field = self._get_size_field_for_key(key_lower, size_key_mapping)
            if size_field:
                # Extract size value
                first_item = items[0]
                size_value = first_item.get("value", "")
                if size_value and not getattr(preferences, size_field, None):
                    setattr(preferences, size_field, size_value)
                continue

            # Determine which preference field this key maps to
            target_field = self._get_preference_field_for_key(key_lower)
            if not target_field:
                continue

            # Add items to the appropriate preference/dislike list
            for item in items:
                pref_item = self._to_preference_item(item)
                if item.get("dislike"):
                    getattr(dislikes, target_field).append(pref_item)
                else:
                    getattr(preferences, target_field).append(pref_item)

        return preferences, dislikes

    def _get_size_field_for_key(self, key: str, size_key_mapping: dict[str, str]) -> Optional[str]:
        """Check if a key represents a size field and return the corresponding field name."""
        # Direct match first
        if key in size_key_mapping:
            return size_key_mapping[key]

        # Check for size-related suffixes (e.g., "womens_dresses", "mens_tops")
        for size_key, field in size_key_mapping.items():
            if key.endswith(f"_{size_key}") or key.endswith(f"_{size_key}s"):
                return field

        return None

    def _get_preference_field_for_key(self, key: str) -> Optional[str]:
        """Map a preference key to its target field using pattern matching."""
        # Pattern matching rules - order matters for overlapping patterns
        patterns = [
            (["brand"], "brands"),
            (["color", "colour"], "colors"),
            (["fabric", "material"], "fabrics"),
            (["occasion"], "occasions"),
            (["fit", "style", "cut"], "styles"),
            # Category patterns - checked last as they're broader
            (["categor", "clothing", "footwear", "accessor", "lifestyle", "jewellery", "jewelry"], "categories"),
        ]

        for substrings, field in patterns:
            for substr in substrings:
                if substr in key:
                    return field

        return None

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
                    subCategory,
                    collection,
                    color,
                    size,
                    sizeType,
                    price,
                    imageUrl,
                    url,
                    inStock,
                    productDescription,
                    tags
                FROM TWCVARIANT FINAL
                WHERE tenantId = {tenant_id:String}
                  AND variantRef = {product_id:String}
                  AND deleted = 0
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
        limit: int = 1000,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> list[Product]:
        """Fetch products for a retailer with optional filters.

        Args:
            tenant_id: The retailer/tenant ID
            limit: Maximum products to return
            category: Filter by exact category match (case-insensitive)
            subcategory: Filter by exact subcategory match (case-insensitive)
            collection: Filter by collection (substring match in comma-separated list)
        """
        client = _get_client(self.config)

        try:
            # Build dynamic WHERE clause
            where_clauses = [
                "tenantId = {tenant_id:String}",
                "deleted = 0",
            ]
            parameters = {"tenant_id": tenant_id, "limit": limit}

            if category:
                where_clauses.append("lower(category) = {category:String}")
                parameters["category"] = category.lower()

            if subcategory:
                where_clauses.append("lower(subCategory) = {subcategory:String}")
                parameters["subcategory"] = subcategory.lower()

            if collection:
                where_clauses.append("lower(collection) LIKE {collection_pattern:String}")
                parameters["collection_pattern"] = f"%{collection.lower()}%"

            query = f"""
                SELECT
                    productRef,
                    variantRef,
                    productName,
                    variantName,
                    brand,
                    category,
                    subCategory,
                    collection,
                    color,
                    size,
                    sizeType,
                    price,
                    imageUrl,
                    url,
                    inStock,
                    productDescription,
                    tags
                FROM TWCVARIANT FINAL
                WHERE {' AND '.join(where_clauses)}
                ORDER BY updatedAt DESC
                LIMIT {{limit:UInt32}}
            """

            result = client.query(query, parameters=parameters)

            return [self._row_to_product(tenant_id, row) for row in result.result_rows]
        finally:
            client.close()

    def get_categories_for_retailer(self, tenant_id: str) -> list[dict]:
        """Fetch distinct categories and subcategories for a retailer.

        Returns a list of category dicts with structure:
        {
            "name": "Dresses",
            "subcategories": ["Midi Dresses", "Evening Dresses", ...],
            "product_count": 45
        }
        """
        client = _get_client(self.config)

        try:
            query = """
                SELECT
                    category,
                    subCategory,
                    count(*) as product_count
                FROM TWCVARIANT FINAL
                WHERE tenantId = {tenant_id:String}
                  AND deleted = 0
                  AND category IS NOT NULL
                  AND category != ''
                GROUP BY category, subCategory
                ORDER BY category, subCategory
            """

            result = client.query(query, parameters={"tenant_id": tenant_id})

            # Aggregate into category -> subcategories structure
            categories_map: dict[str, dict] = {}

            for row in result.result_rows:
                category, subcategory, count = row

                if category not in categories_map:
                    categories_map[category] = {
                        "name": category,
                        "subcategories": [],
                        "product_count": 0,
                    }

                categories_map[category]["product_count"] += count

                if subcategory and subcategory not in categories_map[category]["subcategories"]:
                    categories_map[category]["subcategories"].append(subcategory)

            # Sort subcategories alphabetically
            for cat_data in categories_map.values():
                cat_data["subcategories"].sort()

            # Return sorted by category name
            return sorted(categories_map.values(), key=lambda x: x["name"])
        finally:
            client.close()

    def _row_to_product(self, tenant_id: str, row: tuple) -> Product:
        """Convert a database row to a Product model."""
        (
            product_ref, variant_ref, product_name, variant_name,
            brand, category, sub_category, collection, color, size, size_type,
            price, image_url, url, in_stock, product_description, tags
        ) = row

        # Map inStock (UInt8) to stock_status string
        # NOTE: inStock not yet populated - will be used for frontend filtering in future
        stock_status = None
        if in_stock == 1:
            stock_status = "in_stock"
        elif in_stock == 0:
            stock_status = "out_of_stock"

        # Parse collection field (comma-separated list)
        collections = []
        if collection:
            collections = [c.strip() for c in collection.split(",") if c.strip()]

        # Parse tags field (comma-separated list or already a list)
        tag_list = []
        if tags:
            if isinstance(tags, str):
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            elif isinstance(tags, list):
                tag_list = [str(t).strip() for t in tags if t]

        return Product(
            product_id=variant_ref,
            product_ref=product_ref,
            retailer_id=tenant_id,
            name=product_name or "",
            description=product_description or None,
            price=float(price or 0),
            image_url=image_url,
            product_url=url,
            attributes=ProductAttributes(
                category=category,
                subcategory=sub_category,
                collections=collections,
                brand=brand,
                color=color,
                colors=[color] if color else [],
                tags=tag_list,
            ),
            sizing=ProductSizing(
                available_sizes=[size] if size else [],
                size_type=size_type,  # May be None if not populated
            ),
            stock_status=stock_status,
        )
