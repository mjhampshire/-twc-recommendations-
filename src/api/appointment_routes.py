"""Storefront appointment-booking routes (ST-17).

A thin BFF over the public appointment endpoints in wsservice
(``AppointmentStorefrontResource`` @ ``/api/appointments/storefront/**``). The browser widget calls
these; this service holds the tenant's client-credentials secret and forwards ``X-TWC-Tenant`` (via
``TWCCoreClient.tenant_id``), so a logged-out shopper never holds a token — the ST-15 auth model.

"Dumb embed, server-side intelligence": no booking logic lives here. Slot validity, capacity, PIN
issuance and the guest-safe projection are all enforced by wsservice; this layer just shapes the
request/response and maps TWC Core errors to HTTP.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..clients.twc_core import TWCCoreError, TWCCoreAuthError
from .widget_routes import get_twc_client

router = APIRouter(prefix="/api/v1/appointments", tags=["appointments"])


# =============================================================================
# Request models
# =============================================================================
class BookAppointmentRequest(BaseModel):
    """Guest booking request. Contact fields are snapshotted; identity is optional (guest-safe)."""

    appointment_type_id: str = Field(..., alias="appointmentTypeId")
    location_ref: str = Field(..., alias="locationRef")
    # ISO-8601 UTC instant from a prior slots query, e.g. "2026-03-14T23:00:00Z".
    start_at_utc: str = Field(..., alias="startAtUtc")
    contact_name: str = Field(..., alias="contactName")
    contact_email: str = Field(..., alias="contactEmail")
    contact_mobile: Optional[str] = Field(None, alias="contactMobile")
    notes: Optional[str] = None
    event_date: Optional[str] = Field(None, alias="eventDate")
    # Optional identity — resolved/created server-side; a guest may omit both.
    customer_id: Optional[str] = Field(None, alias="customerId")
    customer_ref: Optional[str] = Field(None, alias="customerRef")

    class Config:
        populate_by_name = True


class AccessAppointmentRequest(BaseModel):
    """Retrieve a booking by code + PIN (both required by wsservice)."""

    booking_ref: str = Field(..., alias="bookingRef")
    access_pin: str = Field(..., alias="accessPin")

    class Config:
        populate_by_name = True


# =============================================================================
# Routes
# =============================================================================
@router.get("/types/{retailer_id}")
async def list_types(retailer_id: str):
    """Bookable appointment types for the tenant."""
    client = get_twc_client(retailer_id)
    try:
        return {"types": await client.get_appointment_types()}
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))


@router.get("/locations/{retailer_id}")
async def list_locations(retailer_id: str):
    """Stores the shopper can book at (those with availability configured)."""
    client = get_twc_client(retailer_id)
    try:
        return {"locations": await client.get_appointment_locations()}
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))


@router.get("/slots/{retailer_id}")
async def list_slots(
    retailer_id: str,
    location_ref: str = Query(..., alias="locationRef"),
    appointment_type_id: str = Query(..., alias="appointmentTypeId"),
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    """Valid start times for a store + type over a date range (store-local dates, yyyy-MM-dd)."""
    client = get_twc_client(retailer_id)
    try:
        slots = await client.get_appointment_slots(
            location_ref, appointment_type_id, from_date, to_date
        )
        return {"slots": slots}
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))


@router.post("/book/{retailer_id}")
async def book(retailer_id: str, request: BookAppointmentRequest):
    """Create a guest booking. Returns the booking incl. the one-time accessPin for the shopper."""
    client = get_twc_client(retailer_id)
    payload = request.model_dump(by_alias=True, exclude_none=True)
    try:
        appointment = await client.create_appointment(payload)
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        # Surface wsservice's own 400/409 (e.g. SLOT_FULL) rather than masking as 500.
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))
    if not appointment:
        raise HTTPException(status_code=502, detail="No response from booking service")
    return appointment


@router.post("/access/{retailer_id}")
async def access(retailer_id: str, request: AccessAppointmentRequest):
    """Retrieve a booking by code + PIN. 404 on a bad ref or PIN (uniform, no enumeration)."""
    client = get_twc_client(retailer_id)
    try:
        appointment = await client.access_appointment(
            request.booking_ref, request.access_pin
        )
    except TWCCoreAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TWCCoreError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e))
    if not appointment:
        raise HTTPException(status_code=404, detail="Booking not found")
    return appointment
