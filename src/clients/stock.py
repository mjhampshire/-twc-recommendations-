"""Stock availability client for TWC REST API.

Stock is checked via REST API, not ClickHouse. This client handles:
- Batch stock check for variants
- Filtering recommendations to in-stock items

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
        client = StockClient(base_url="https://api.example.com", token="...")

        # Check multiple variants (batch)
        stock_map = await client.check_stock_batch(["variant1", "variant2"])
        # Returns: {"variant1": True, "variant2": False}

        # Get detailed stock levels
        stock_levels = await client.get_stock_levels(["variant1", "variant2"])
        # Returns full response with location details

        # Filter to only in-stock variants
        in_stock = await client.filter_in_stock(["variant1", "variant2"])
        # Returns: ["variant1"]
    """

    DEFAULT_BASE_URL = "https://wh-fe.au-aws.thewishlist.io/api/v1"
    STOCK_PATH = "/stocklevels/variants"

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 5.0,
    ):
        """
        Initialize stock client.

        Args:
            base_url: Override base URL (for testing)
            token: Bearer token for authentication
            timeout: Request timeout in seconds (stock checks should be fast)
        """
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.token = token
        self.timeout = timeout

    async def get_stock_levels(
        self,
        variant_ids: list[str],
        token: Optional[str] = None,
    ) -> list[dict]:
        """
        Get detailed stock levels for variants.

        Args:
            variant_ids: List of variant IDs to check
            token: Optional bearer token (overrides instance token)

        Returns:
            List of stock level objects:
            [
                {
                    "productVariantId": "VARIANT_12345",
                    "totalStock": "150",
                    "stockLevels": [
                        {"locationId": "LOC_1", "locationName": "Warehouse A", "availableStock": "80"},
                        ...
                    ],
                    "lastItemId": "VARIANT_12345#LOC_2"
                },
                ...
            ]
        """
        if not variant_ids:
            return []

        url = f"{self.base_url}{self.STOCK_PATH}"
        auth_token = token or self.token

        if not auth_token:
            raise StockError("Authentication token required for stock API")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=variant_ids,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        except httpx.TimeoutException:
            logger.warning("Stock API timeout")
            raise StockError("Stock API timeout")
        except httpx.HTTPStatusError as e:
            logger.error(f"Stock API error: {e.response.status_code}")
            raise StockError(
                f"Stock API returned {e.response.status_code}",
                status_code=e.response.status_code,
            )

    async def check_stock_batch(
        self,
        variant_ids: list[str],
        token: Optional[str] = None,
    ) -> dict[str, bool]:
        """
        Check stock for multiple variants in a single request.

        Args:
            variant_ids: List of variant IDs to check
            token: Optional bearer token (overrides instance token)

        Returns:
            Dict mapping variant_id -> in_stock (True if totalStock > 0)
        """
        if not variant_ids:
            return {}

        try:
            stock_data = await self.get_stock_levels(variant_ids, token)

            result = {}
            for item in stock_data:
                variant_id = item.get("productVariantId")
                total_stock = item.get("totalStock", "0")

                # totalStock is returned as string, convert to int
                try:
                    stock_qty = int(total_stock)
                except (ValueError, TypeError):
                    stock_qty = 0

                result[variant_id] = stock_qty > 0

            # For any variants not in response, assume out of stock
            for vid in variant_ids:
                if vid not in result:
                    result[vid] = False

            return result

        except StockError:
            # Re-raise stock errors
            raise
        except Exception as e:
            logger.error(f"Stock API error: {e}")
            # Fail open - assume in stock if API fails unexpectedly
            return {vid: True for vid in variant_ids}

    async def filter_in_stock(
        self,
        variant_ids: list[str],
        token: Optional[str] = None,
    ) -> list[str]:
        """
        Filter a list of variant IDs to only those in stock.

        Args:
            variant_ids: List of variant IDs to filter
            token: Optional bearer token

        Returns:
            List of variant IDs that are in stock (preserves order)
        """
        if not variant_ids:
            return []

        stock_map = await self.check_stock_batch(variant_ids, token)
        return [vid for vid in variant_ids if stock_map.get(vid, False)]

    async def is_in_stock(
        self,
        variant_id: str,
        token: Optional[str] = None,
    ) -> bool:
        """
        Check if a single variant is in stock.

        Args:
            variant_id: Variant ID to check
            token: Optional bearer token

        Returns:
            True if variant is in stock, False otherwise
        """
        stock_map = await self.check_stock_batch([variant_id], token)
        return stock_map.get(variant_id, False)

    async def get_stock_by_location(
        self,
        variant_ids: list[str],
        location_id: str,
        token: Optional[str] = None,
    ) -> dict[str, int]:
        """
        Get stock quantities for variants at a specific location.

        Args:
            variant_ids: List of variant IDs to check
            location_id: Location ID to filter by
            token: Optional bearer token

        Returns:
            Dict mapping variant_id -> available stock at location
        """
        if not variant_ids:
            return {}

        stock_data = await self.get_stock_levels(variant_ids, token)

        result = {}
        for item in stock_data:
            variant_id = item.get("productVariantId")
            stock_levels = item.get("stockLevels", [])

            for level in stock_levels:
                if level.get("locationId") == location_id:
                    try:
                        result[variant_id] = int(level.get("availableStock", "0"))
                    except (ValueError, TypeError):
                        result[variant_id] = 0
                    break
            else:
                # Location not found for this variant
                result[variant_id] = 0

        return result
