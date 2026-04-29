"""FastAPI application setup."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .widget_routes import router as widget_router

app = FastAPI(
    title="TWC Recommendations API",
    description="Product recommendation engine for The Wishlist Company",
    version="0.1.0",
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)
app.include_router(widget_router)


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "TWC Recommendations",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
