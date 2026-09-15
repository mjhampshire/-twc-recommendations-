"""TWC Core REST API client with OAuth2 authentication."""

from datetime import datetime, timedelta
from typing import Optional
import logging

import httpx

logger = logging.getLogger(__name__)


class TWCCoreError(Exception):
    """Base exception for TWC Core API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TWCCoreAuthError(TWCCoreError):
    """Authentication failed."""
    pass


class TWCCoreClient:
    """
    Client for TWC Core REST APIs with OAuth2 authentication.

    Handles token caching and automatic refresh.

    Usage:
        client = TWCCoreClient(client_secret="your-tenant-secret")
        wishlist = await client.get_anonymous_wishlist("session123")
    """

    AUTH_URL = "https://auth.au-aws.thewishlist.io/auth/realms/twcMain/protocol/openid-connect/token"
    BASE_URL = "https://api.au-aws.thewishlist.io"

    WISHLIST_PATH = "services/wssservice/api/wishlist"
    CUSTOMER_PATH = "services/customerservice/api/v2/customers"
    # Storefront (guest) appointment endpoints — see AppointmentStorefrontResource in wsservice.
    APPOINTMENT_PATH = "services/wssservice/api/appointments/storefront"

    def __init__(
        self,
        client_secret: str,
        base_url: Optional[str] = None,
        auth_url: Optional[str] = None,
        timeout: float = 10.0,
        tenant_id: Optional[str] = None,
    ):
        """
        Initialize TWC Core client.

        Args:
            client_secret: OAuth2 client secret for the tenant
            base_url: Override base URL (for testing)
            auth_url: Override auth URL (for testing)
            timeout: Request timeout in seconds
            tenant_id: Tenant this client acts for. When set, appointment calls send it as the
                X-TWC-Tenant header (wsservice resolves the tenant from that header). Existing
                wishlist/customer calls are unchanged.
        """
        self.client_secret = client_secret
        self.base_url = base_url or self.BASE_URL
        self.auth_url = auth_url or self.AUTH_URL
        self.timeout = timeout
        self.tenant_id = tenant_id

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def _get_token(self) -> str:
        """
        Get OAuth2 access token (cached until near expiry).

        Returns:
            Valid access token

        Raises:
            TWCCoreAuthError: If authentication fails
        """
        # Return cached token if still valid
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
                return self._access_token

        logger.debug("Fetching new OAuth2 token from TWC Core")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.auth_url,
                    data={
                        "client_id": "twc-api-client",
                        "client_secret": self.client_secret,
                        "grant_type": "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code == 401:
                    raise TWCCoreAuthError("Invalid client credentials", 401)

                response.raise_for_status()
                data = response.json()

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 300)
                # Refresh 30 seconds before actual expiry
                self._token_expires_at = datetime.now() + timedelta(
                    seconds=expires_in - 30
                )

                logger.debug(f"Got new token, expires in {expires_in}s")
                return self._access_token

        except httpx.HTTPStatusError as e:
            raise TWCCoreAuthError(
                f"Auth request failed: {e.response.status_code}", e.response.status_code
            )
        except httpx.RequestError as e:
            raise TWCCoreAuthError(f"Auth request error: {str(e)}")

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Make authenticated request to TWC Core.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: API path (relative to base URL)
            params: Query parameters
            json: JSON body
            headers: Extra request headers merged over the Authorization header (e.g. X-TWC-Tenant
                for appointment calls). The Authorization header always wins.

        Returns:
            Response JSON or None if 404

        Raises:
            TWCCoreError: If request fails
        """
        token = await self._get_token()
        url = f"{self.base_url}/{path}"

        req_headers = dict(headers or {})
        req_headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=req_headers,
                )

                # 404 is not an error - just means resource doesn't exist
                if response.status_code == 404:
                    return None

                response.raise_for_status()

                # Handle empty responses
                if not response.content:
                    return {}

                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"TWC Core request failed: {method} {path} -> {e.response.status_code}")
            raise TWCCoreError(
                f"Request failed: {e.response.status_code}",
                e.response.status_code,
            )
        except httpx.RequestError as e:
            logger.error(f"TWC Core request error: {method} {path} -> {str(e)}")
            raise TWCCoreError(f"Request error: {str(e)}")

    # -------------------------------------------------------------------------
    # Customer endpoints
    # -------------------------------------------------------------------------

    async def get_customer(self, customer_id: str) -> Optional[dict]:
        """
        Fetch customer profile by TWC customer ID.

        GET /services/customerservice/api/v2/customers/{customerId}

        Args:
            customer_id: TWC customer ID

        Returns:
            Customer data or None if not found
        """
        return await self._request("GET", f"{self.CUSTOMER_PATH}/{customer_id}")

    # -------------------------------------------------------------------------
    # Wishlist endpoints
    # -------------------------------------------------------------------------

    async def get_wishlist(self, wishlist_id: str) -> Optional[dict]:
        """
        Fetch wishlist by ID.

        GET /services/wssservice/api/wishlist/wishlists/{wishlistId}

        Args:
            wishlist_id: Wishlist ID

        Returns:
            Wishlist data or None if not found
        """
        return await self._request("GET", f"{self.WISHLIST_PATH}/wishlists/{wishlist_id}")

    async def get_customer_wishlists(self, customer_id: str) -> Optional[list]:
        """
        Fetch all wishlists for a customer.

        GET /services/wssservice/api/wishlist/wishlists?customerId={customerId}

        Args:
            customer_id: TWC customer ID

        Returns:
            List of wishlists or None if customer not found
        """
        result = await self._request(
            "GET",
            f"{self.WISHLIST_PATH}/wishlists",
            params={"customerId": customer_id},
        )
        # API might return a dict with wishlists array or just the array
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("wishlists", [])
        return []

    async def get_wishlist_items(self, wishlist_id: str) -> list:
        """
        Fetch items in a wishlist.

        GET /services/wssservice/api/wishlist/wishlists/{wishlistId}/items

        Args:
            wishlist_id: Wishlist ID

        Returns:
            List of wishlist items
        """
        result = await self._request(
            "GET", f"{self.WISHLIST_PATH}/wishlists/{wishlist_id}/items"
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("items", [])
        return []

    async def add_to_wishlist(
        self,
        wishlist_id: str,
        product_id: str,
        variant_id: Optional[str] = None,
    ) -> dict:
        """
        Add item to wishlist.

        POST /services/wssservice/api/wishlist/wishlists/{wishlistId}/items

        Args:
            wishlist_id: Wishlist ID
            product_id: Product ID to add
            variant_id: Optional variant ID

        Returns:
            Created item data
        """
        payload = {"productId": product_id}
        if variant_id:
            payload["variantId"] = variant_id

        return await self._request(
            "POST",
            f"{self.WISHLIST_PATH}/wishlists/{wishlist_id}/items",
            json=payload,
        )

    async def remove_from_wishlist(self, wishlist_id: str, item_id: str) -> bool:
        """
        Remove item from wishlist.

        DELETE /services/wssservice/api/wishlist/wishlists/{wishlistId}/items/{itemId}

        Args:
            wishlist_id: Wishlist ID
            item_id: Item ID to remove

        Returns:
            True if successful
        """
        await self._request(
            "DELETE",
            f"{self.WISHLIST_PATH}/wishlists/{wishlist_id}/items/{item_id}",
        )
        return True

    # -------------------------------------------------------------------------
    # Anonymous wishlist endpoints
    # -------------------------------------------------------------------------

    async def get_anonymous_wishlist(self, online_session_id: str) -> Optional[dict]:
        """
        Get anonymous wishlist by Shopify session ID.

        GET /services/wssservice/api/wishlist/wishlists/anonymous?onlineSessionID={id}

        Args:
            online_session_id: Shopify session ID

        Returns:
            Anonymous wishlist info or None if doesn't exist
            {"customerId": "...", "wishlistId": "...", "items": [...]}
        """
        return await self._request(
            "GET",
            f"{self.WISHLIST_PATH}/wishlists/anonymous",
            params={"onlineSessionID": online_session_id},
        )

    async def create_anonymous_wishlist(self, online_session_id: str) -> dict:
        """
        Create anonymous wishlist for session.

        POST /services/wssservice/api/wishlist/wishlists/anonymous?onlineSessionID={id}

        Creates:
        - Customer: {sessionId}@anonymousTWCuser.twc (anonymousUser=true)
        - Wishlist: single wishlist with anonymous=true

        Args:
            online_session_id: Shopify session ID

        Returns:
            {"customerId": "...", "wishlistId": "..."}
        """
        return await self._request(
            "POST",
            f"{self.WISHLIST_PATH}/wishlists/anonymous",
            params={"onlineSessionID": online_session_id},
        )

    async def get_or_create_anonymous_wishlist(self, online_session_id: str) -> dict:
        """
        Get existing anonymous wishlist or create new one.

        Convenience method that combines get + create.

        Args:
            online_session_id: Shopify session ID

        Returns:
            {"customerId": "...", "wishlistId": "..."}
        """
        existing = await self.get_anonymous_wishlist(online_session_id)
        if existing:
            return existing
        return await self.create_anonymous_wishlist(online_session_id)

    async def merge_anonymous_wishlist(
        self,
        anonymous_wishlist_id: str,
        customer_email: str,
        online_session_id: Optional[str] = None,
        customer_ref: Optional[str] = None,
        wishlist_ref: Optional[str] = None,
        wishlist_name: Optional[str] = None,
    ) -> dict:
        """
        Merge anonymous wishlist into customer wishlist.

        POST /services/wssservice/api/wishlist/wishlists/merge

        Merge logic:
        - If maxWishlists=1: adds items to existing wishlist (or creates one)
        - If maxWishlists>1: adds to specified wishlistRef (or creates new)
        - Error if maxWishlists exceeded

        Args:
            anonymous_wishlist_id: ID of anonymous wishlist to merge
            customer_email: Customer's email address
            online_session_id: Optional session ID
            customer_ref: Optional Shopify customer reference
            wishlist_ref: Optional target wishlist reference
            wishlist_name: Optional name for new wishlist

        Returns:
            Merge result with customerId and wishlistId
        """
        payload = {
            "anonymousWishlistId": anonymous_wishlist_id,
            "customerEmail": customer_email,
        }
        if online_session_id:
            payload["onlineSessionID"] = online_session_id
        if customer_ref:
            payload["customerRef"] = customer_ref
        if wishlist_ref:
            payload["wishlistRef"] = wishlist_ref
        if wishlist_name:
            payload["wishlistName"] = wishlist_name

        return await self._request(
            "POST",
            f"{self.WISHLIST_PATH}/wishlists/merge",
            json=payload,
        )

    # -------------------------------------------------------------------------
    # Storefront appointment endpoints (guest booking — ST-15)
    #
    # These proxy the public AppointmentStorefrontResource in wsservice. Each sends X-TWC-Tenant so
    # wsservice resolves the right tenant (the shopper never holds a token; this client is the
    # trusted caller, authenticated with the tenant's client-credentials secret).
    # -------------------------------------------------------------------------

    def _tenant_headers(self) -> dict:
        """X-TWC-Tenant header for appointment calls (empty when no tenant is configured)."""
        return {"X-TWC-Tenant": self.tenant_id} if self.tenant_id else {}

    async def get_appointment_types(self) -> list:
        """
        Bookable appointment types for the tenant.

        GET /services/wssservice/api/appointments/storefront/types
        """
        result = await self._request(
            "GET", f"{self.APPOINTMENT_PATH}/types", headers=self._tenant_headers()
        )
        return result if isinstance(result, list) else []

    async def get_appointment_locations(self) -> list:
        """
        Stores a shopper can book at (those with availability configured).

        GET /services/wssservice/api/appointments/storefront/locations
        """
        result = await self._request(
            "GET", f"{self.APPOINTMENT_PATH}/locations", headers=self._tenant_headers()
        )
        return result if isinstance(result, list) else []

    async def get_appointment_slots(
        self,
        location_ref: str,
        appointment_type_id: str,
        from_date: str,
        to_date: str,
    ) -> list:
        """
        Valid start times for a store + type over a date range (store-local dates, yyyy-MM-dd).

        GET /services/wssservice/api/appointments/storefront/slots
        """
        result = await self._request(
            "GET",
            f"{self.APPOINTMENT_PATH}/slots",
            params={
                "locationRef": location_ref,
                "appointmentTypeId": appointment_type_id,
                "from": from_date,
                "to": to_date,
            },
            headers=self._tenant_headers(),
        )
        return result if isinstance(result, list) else []

    async def create_appointment(self, payload: dict) -> dict:
        """
        Create a guest booking. The response carries the one-time accessPin to relay to the shopper.

        POST /services/wssservice/api/appointments/storefront/book
        """
        return await self._request(
            "POST",
            f"{self.APPOINTMENT_PATH}/book",
            json=payload,
            headers=self._tenant_headers(),
        )

    async def access_appointment(self, booking_ref: str, access_pin: str) -> Optional[dict]:
        """
        Retrieve a guest booking by code + PIN (guest-safe projection). Returns None if not found.

        POST /services/wssservice/api/appointments/storefront/access
        """
        return await self._request(
            "POST",
            f"{self.APPOINTMENT_PATH}/access",
            json={"bookingRef": booking_ref, "accessPin": access_pin},
            headers=self._tenant_headers(),
        )
