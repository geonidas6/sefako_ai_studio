"""In-memory workflow control flags for running project analyses."""
import asyncio

# One cancel event per running project. This is process-local and intended for
# the current single-container deployment.
WORKFLOW_CANCEL_EVENTS: dict[str, asyncio.Event] = {}
