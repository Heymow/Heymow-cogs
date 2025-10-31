"""
StreamRoles API cog package initializer.

This file exposes the StreamRolesAPI cog to Red by providing the async setup function.
It expects the main cog implementation to be in streamroles_api_cog.py
within the same package (cogs/streamroles_api/streamroles_api_cog.py).
"""
from .streamroles_api_cog import StreamRolesAPI  # noqa: E402,F401

async def setup(bot):
    """Red cog loader entrypoint."""
    await bot.add_cog(StreamRolesAPI(bot))