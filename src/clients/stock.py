"""Stock availability client for TWC REST API.

Stock is checked via REST API, not ClickHouse. This client handles:
- Aggregate stock check (default) - is product available anywhere?
- Store-specific stock check - is product available at a specific store?

Note: Store-level filtering is typically done by frontend as a final filter.
This client is used for pre-filtering recommendations at aggregate level.
"""

from typing import Optional
import logging

import httpx

logger = logging.getLogger(__name__)


class StockError(Exception):
    """Base exception for stock API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class StockClient:
    """
    Client for TWC Stock REST API.

    Usage:
        client = StockClient(base_url="https://api.example.com", api_key="...")

        # Check single product
        in_stock = await client.is_in_stock("product123")

        # Check multiple products (batch)
        stock_map = await client.check_stock_batch(["product1", "product2", "product3"])
        # Returns: {"product1": True, "product2": False, "product3": True}
    """

    # TODO: Update these once endpoint details are provided
    BASE_URL = "https://api.au-aws.thewishlist.io"
    STOCK_PATH = "services/stockservice/api/v1/stock"  # Placeholder

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
    ):
        """
        Initialize stock client.

        Args:
            base_url: Override base URL (for testing)
            api_key: API key for authentication
            timeout: Request timeout in seconds (stock checks should be fast)
        """
        self.base_url = base_url or self.BASE_URL
        self.api_key = api_key
        self.timeout = timeout

    async def is_in_stock(
        self,
        product_id: str,
        tenant_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> bool:
        """
        Check if a single product is in stock.

        Args:
            product_id: Product/variant ID to check
            tenant_id: Retailer/tenant ID
            store_id: Optional store ID for store-specific check

        Returns:
            True if product is in stock, False otherwise
        """
        # TODO: Implement once endpoint details are provided
        logger.warning("Stock API not yet configured - returning True for all products")
        return True

    async def check_stock_batch(
        self,
        product_ids: list[str],
        tenant_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> dict[str, bool]:
        """
        Check stock for multiple products in a single request.

        Args:
            product_ids: List of product/variant IDs to check
            tenant_id: Retailer/tenant ID
            store_id: Optional store ID for store-specific check

        Returns:
            Dict mapping product_id -> in_stock (True/False)
        """
        # TODO: Implement once endpoint details are provided
        logger.warning("Stock API not yet configured - returning True for all products")
        return {pid: True for pid in product_ids}

    async def filter_in_stock(
        self,
        product_ids: list[str],
        tenant_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> list[str]:
        """
        Filter a list of product IDs to only those in stock.

        Convenience method that calls check_stock_batch and filters.

        Args:
            product_ids: List of product/variant IDs to filter
            tenant_id: Retailer/tenant ID
            store_id: Optional store ID for store-specific check

        Returns:
            List of product IDs that are in stock
        """
        stock_map = await self.check_stock_batch(product_ids, tenant_id, store_id)
        return [pid for pid, in_stock in stock_map.items() if in_stock]


# Example implementation once endpoint is known:
#
# async def check_stock_batch(self, product_ids: list[str], tenant_id: str, ...) -> dict[str, bool]:
#     """Batch stock check via REST API."""
#     url = f"{self.base_url}/{self.STOCK_PATH}/batch"
#
#     async with httpx.AsyncClient(timeout=self.timeout) as client:
#         response = await client.post(
#             url,
#             json={"productIds": product_ids, "tenantId": tenant_id},
#             headers={"Authorization": f"Bearer {self.api_key}"},
#         )
#         response.raise_for_status()
#         data = response.json()
#
#         # Expected response format:
#         # {"stock": [{"productId": "123", "inStock": true}, ...]}
#         return {item["productId"]: item["inStock"] for item in data.get("stock", [])}
