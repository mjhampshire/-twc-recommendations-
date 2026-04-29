"""API module for TWC Recommendations."""
from .app import app
from .routes import router
from .widget_routes import router as widget_router

__all__ = ["app", "router", "widget_router"]
