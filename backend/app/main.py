"""
FastAPI application entry point for IRTBoss.

This is the main application file that configures and runs the API server.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    logger.info("Starting IRTBoss API server...")

    # TODO: Initialize database connection
    # TODO: Initialize Redis/task queue connection

    yield

    # Shutdown
    logger.info("Shutting down IRTBoss API server...")
    # TODO: Close database connections
    # TODO: Close task queue connections


# Create FastAPI application
app = FastAPI(
    title="IRTBoss",
    description=(
        "An opinionated IRT assessment platform. "
        "Go from raw response data to validated IRT model to interpretable report."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
# In production, restrict origins appropriately
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "IRTBoss",
        "version": "0.1.0",
        "description": "Item Response Theory Assessment Platform",
        "docs": "/docs",
        "api": "/api/v1",
    }


# For running with uvicorn directly
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
