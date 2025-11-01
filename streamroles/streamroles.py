# Full merged StreamRoles cog with:
# - embedded aiohttp API (/api/...) restricted to local-only via middleware
# - public dashboard at /dashboard
# - public server-side proxy endpoints under /dashboard/proxy/* that use the stored per-guild token from Config
# - streamrole setapitoken command to store per-guild token server-side
# - streamrole setfixedguild command to set/clear a fixed guild id in Config at runtime (no redeploy)
#
# Notes:
# - Requires aiohttp available in the runtime (aiohttp>=3.8).
# - Dashboard remains public; client-side JS calls the proxy endpoints (no client token needed).
# - /api/* endpoints remain accessible only from localhost (internal) via middleware.
# - This file expects streamroles/static/dashboard.html to exist; otherwise an embedded fallback is served.
import asyncio
import contextlib
import csv
import io
import ipaddress
import logging
import os
import time
from typing import List, Optional, Tuple, Union

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils import chat_formatting as chatutils, menus, predicates

# aiohttp imports for the embedded API
try:
    import aiohttp
    from aiohttp import web
except Exception:  # pragma: no cover - runtime dependency
    aiohttp = None
    web = None

from .types import FilterList
from .badges import (
    calculate_member_badges,
    calculate_guild_achievements,
    BADGES,
    ACHIEVEMENTS,
)
from .twitch_watcher import TwitchWatcher

log = logging.getLogger("red.streamroles")

UNIQUE_ID = 0x923476AF

_alerts_channel_sentinel = object()


def _epoch_now() -> int:
    return int(time.time())


# retention helper: convert days to seconds
def _days_to_seconds(days: int) -> int:
    return int(days) * 24 * 60 * 60


class StreamRoles(commands.Cog):
    """Give current twitch streamers in your server a role and collect stats."""

    DEBUG_MODE = False

    DEFAULT_API_HOST = "0.0.0.0"
    DEFAULT_API_PORT = 8080

    # local-only CIDRs for internal API access (restricts /api/*)
    _INTERNAL_CIDRS = ["127.0.0.1/32", "::1/128"]

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.conf = Config.get_conf(self, force_registration=True, identifier=UNIQUE_ID)
        # Guild config (added api_token and fixed_guild_id)
        self.conf.register_guild(
            streamer_role=None,
            game_whitelist=[],
            mode=str(FilterList.blacklist),
            alerts__enabled=False,
            alerts__channel=None,
            alerts__autodelete=True,
            required_role=None,
            stats__enabled=True,
            stats__retention_days=365,
            api_token=None,        # per-guild API token for embedded API
            fixed_guild_id=None,   # optional fixed guild id for dashboard proxy (stored per-guild)
            watched_channels=[],   # channels being watched for Twitch links
            tracked_twitch_channels=[],  # Twitch channels discovered from links
        )
        # Member config
        self.conf.register_member(
            blacklisted=False,
            whitelisted=False,
            alert_messages={},
            current_stream_start=None,
            stream_stats=[],
        )
        self.conf.register_role(blacklisted=False, whitelisted=False)

        # --- API server attributes ---
        self._api_runner = None  # type: Optional[web.AppRunner]
        self._api_site = None  # type: Optional[web.TCPSite]
        self._api_app = None  # type: Optional[web.Application]
        self._api_host = os.environ.get("HOST", self.DEFAULT_API_HOST)
        try:
            self._api_port = int(os.environ.get("PORT", os.environ.get("PORT", self.DEFAULT_API_PORT)))
        except Exception:
            self._api_port = self.DEFAULT_API_PORT

        # precompute networks
        self._allowed_nets = [ipaddress.ip_network(c) for c in self._INTERNAL_CIDRS]
        
        # Initialize Twitch watcher
        self.twitch_watcher = TwitchWatcher(self.conf)

    # -----------------
    # Initialization
    # -----------------
    async def initialize(self) -> None:
        """Initialize the cog."""
        for guild in self.bot.guilds:
            await self._update_guild(guild)

    # -----------------
    # Commands
    # -----------------
    @checks.admin_or_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.group(autohelp=True, aliases=["streamroles"])
    async def streamrole(self, ctx: commands.Context):
        """Manage settings for StreamRoles."""
        pass

    @streamrole.command()
    async def setmode(self, ctx: commands.Context, *, mode: FilterList):
        await self.conf.guild(ctx.guild).mode.set(str(mode))
        await self._update_guild(ctx.guild)
        await ctx.tick()

    @streamrole.group(autohelp=True)
    async def whitelist(self, ctx: commands.Context):
        pass

    @whitelist.command(name="add")
    async def white_add(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        await self._update_filter_list_entry(user_or_role, FilterList.whitelist, True)
        await ctx.tick()

    @whitelist.command(name="remove")
    async def white_remove(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        await self._update_filter_list_entry(user_or_role, FilterList.whitelist, False)
        await ctx.tick()

    @checks.bot_has_permissions(embed_links=True)
    @whitelist.command(name="show")
    async def white_show(self, ctx: commands.Context):
        members, roles = await self._get_filter_list(ctx.guild, FilterList.whitelist)
        if not (members or roles):
            await ctx.send("The whitelist is empty.")
            return
        embed = discord.Embed(title="StreamRoles Whitelist", colour=await ctx.embed_colour())
        if members:
            embed.add_field(name="Members", value="\n".join(map(str, members)))
        if roles:
            embed.add_field(name="Roles", value="\n".join(map(str, roles)))
        await ctx.send(embed=embed)

    @streamrole.group(autohelp=True)
    async def blacklist(self, ctx: commands.Context):
        pass

    @blacklist.command(name="add")
    async def black_add(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        await self._update_filter_list_entry(user_or_role, FilterList.blacklist, True)
        await ctx.tick()

    @blacklist.command(name="remove")
    async def black_remove(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        await self._update_filter_list_entry(user_or_role, FilterList.blacklist, False)
        await ctx.tick()

    @checks.bot_has_permissions(embed_links=True)
    @blacklist.command(name="show")
    async def black_show(self, ctx: commands.Context):
        members, roles = await self._get_filter_list(ctx.guild, FilterList.blacklist)
        if not (members or roles):
            await ctx.send("The blacklist is empty.")
            return
        embed = discord.Embed(title="StreamRoles Blacklist", colour=await ctx.embed_colour())
        if members:
            embed.add_field(name="Members", value="\n".join(map(str, members)))
        if roles:
            embed.add_field(name="Roles", value="\n".join(map(str, roles)))
        await ctx.send(embed=embed)

    @streamrole.group(autohelp=True)
    async def games(self, ctx: commands.Context):
        pass

    @games.command(name="add")
    async def games_add(self, ctx: commands.Context, *, game: str):
        async with self.conf.guild(ctx.guild).game_whitelist() as whitelist:
            whitelist.append(game)
        await self._update_guild(ctx.guild)
        await ctx.tick()

    @games.command(name="remove")
    async def games_remove(self, ctx: commands.Context, *, game: str):
        async with self.conf.guild(ctx.guild).game_whitelist() as whitelist:
            try:
                whitelist.remove(game)
            except ValueError:
                await ctx.send("That game is not in the whitelist.")
                return
        await self._update_guild(ctx.guild)
        await ctx.tick()

    @checks.bot_has_permissions(embed_links=True)
    @games.command(name="show")
    async def games_show(self, ctx: commands.Context):
        whitelist = await self.conf.guild(ctx.guild).game_whitelist()
        if not whitelist:
            await ctx.send("The game whitelist is empty.")
            return
        embed = discord.Embed(title="StreamRoles Game Whitelist", description="\n".join(whitelist), colour=await ctx.embed_colour())
        await ctx.send(embed=embed)

    @games.command(name="clear")
    async def games_clear(self, ctx: commands.Context):
        msg = await ctx.send("This will clear the game whitelist for this server. Are you sure you want to do this?")
        menus.start_adding_reactions(msg, predicates.ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = predicates.ReactionPredicate.yes_or_no(msg)
        try:
            message = await ctx.bot.wait_for("reaction_add", check=pred)
        except asyncio.TimeoutError:
            message = None
        if message is not None and pred.result is True:
            await self.conf.guild(ctx.guild).game_whitelist.clear()
            await self._update_guild(ctx.guild)
            await ctx.send("Done. The game whitelist has been cleared.")
        else:
            await ctx.send("The action was cancelled.")

    @streamrole.group()
    async def alerts(self, ctx: commands.Context):
        """Manage streamalerts for those who receive the streamrole."""

    @alerts.command(name="setenabled")
    async def alerts_setenabled(self, ctx: commands.Context, true_or_false: bool):
        await self.conf.guild(ctx.guild).alerts.enabled.set(true_or_false)
        await ctx.tick()

    @alerts.command(name="setchannel")
    async def alerts_setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.conf.guild(ctx.guild).alerts.channel.set(channel.id)
        await ctx.tick()

    @alerts.command(name="autodelete")
    async def alerts_autodelete(self, ctx: commands.Context, true_or_false: bool):
        await self.conf.guild(ctx.guild).alerts.autodelete.set(true_or_false)
        await ctx.tick()

    @streamrole.command()
    async def setrole(self, ctx: commands.Context, *, role: discord.Role):
        await self.conf.guild(ctx.guild).streamer_role.set(role.id)
        await ctx.send("Done. Streamers will now be given the {} role when they go live.".format(role.name))

    @streamrole.command()
    async def setrequiredrole(self, ctx: commands.Context, *, role: str):
        if role.lower() == "none":
            await self.conf.guild(ctx.guild).required_role.set(None)
            await ctx.send("Disabled required role. Any eligible member can now receive the streamrole.")
            await self._update_guild(ctx.guild)
            return
        resolved = None
        if role.isdigit():
            resolved = ctx.guild.get_role(int(role))
        if resolved is None:
            if role.startswith("<@&") and role.endswith(">"):
                try:
                    rid = int(role[3:-1])
                    resolved = ctx.guild.get_role(rid)
                except ValueError:
                    resolved = None
        if resolved is None:
            resolved = discord.utils.find(lambda r: r.name == role, ctx.guild.roles)
            if resolved is None:
                resolved = discord.utils.find(lambda r: r.name.lower() == role.lower(), ctx.guild.roles)
        if resolved is None:
            await ctx.send("Rôle introuvable. Utilise une mention, le nom exact, ou l'ID, ou 'none' pour désactiver.")
            return
        await self.conf.guild(ctx.guild).required_role.set(resolved.id)
        await ctx.send(f"Set required role: {resolved.name}. Only members with this role can receive the streamrole.")
        await self._update_guild(ctx.guild)

    @streamrole.command()
    async def setstatsretention(self, ctx: commands.Context, days: int):
        if days < 1:
            await ctx.send("Retention must be at least 1 day.")
            return
        await self.conf.guild(ctx.guild).stats.retention_days.set(days)
        await ctx.send(f"Stats retention set to {days} days.")
        await self._update_guild(ctx.guild)

    @streamrole.command()
    async def togglestats(self, ctx: commands.Context, enabled: bool):
        await self.conf.guild(ctx.guild).stats.enabled.set(enabled)
        await ctx.send(f"Streaming stats collection {'enabled' if enabled else 'disabled'}.")

    @streamrole.command()
    async def forceupdate(self, ctx: commands.Context):
        if not await self.get_streamer_role(ctx.guild):
            await ctx.send(f"The streamrole has not been set in this server. Please use `{ctx.clean_prefix}streamrole setrole` first.")
            return
        await self._update_guild(ctx.guild)
        await ctx.tick()

    # -----------------
    # Stats commands
    # -----------------
    @streamrole.group()
    async def stats(self, ctx: commands.Context):
        pass

    @stats.command(name="show")
    async def stats_show(self, ctx: commands.Context, member: Optional[discord.Member] = None, period: str = "30d"):
        member = member or ctx.author
        guild = ctx.guild
        if not await self.conf.guild(guild).stats.enabled():
            await ctx.send("Stats collection is disabled on this server.")
            return
        sessions = await self._get_member_sessions(member, guild)
        if not sessions:
            await ctx.send(f"No streaming sessions recorded for {member.mention}.")
            return
        now = _epoch_now()
        if period.endswith("d"):
            try:
                days = int(period[:-1])
            except Exception:
                await ctx.send("Period must be like '7d', '30d', or 'all'.")
                return
            cutoff = now - _days_to_seconds(days)
            filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            period_label = f"last {days} days"
        elif period == "all":
            filtered = sessions
            period_label = "all time"
        else:
            await ctx.send("Period must be like '7d', '30d', or 'all'.")
            return
        total_streams = len(filtered)
        total_time = sum(s.get("duration", 0) for s in filtered)
        avg_duration = total_time / total_streams if total_streams else 0
        if period == "all":
            first = min(s["start"] for s in sessions)
            days_span = max(1, (now - first) / 86400)
        else:
            if period.endswith("d"):
                days_span = days
            else:
                days_span = 1
        weeks = max(1, days_span / 7.0)
        months = max(1, days_span / 30.44)
        per_week = total_streams / weeks
        per_month = total_streams / months
        embed = discord.Embed(title=f"Streaming stats for {member.display_name}", description=f"Period: {period_label}\n", colour=await ctx.embed_colour())
        embed.add_field(name="Total streams", value=str(total_streams), inline=True)
        embed.add_field(name="Total time", value=self._format_seconds(total_time), inline=True)
        embed.add_field(name="Average duration", value=self._format_seconds(int(avg_duration)), inline=True)
        embed.add_field(name="Avg streams / week", value=f"{per_week:.2f}", inline=True)
        embed.add_field(name="Avg streams / month", value=f"{per_month:.2f}", inline=True)
        await ctx.send(embed=embed)

    @stats.command(name="export")
    async def stats_export(self, ctx: commands.Context, member: Optional[discord.Member] = None, period: str = "all"):
        member = member or ctx.author
        guild = ctx.guild
        if not await self.conf.guild(guild).stats.enabled():
            await ctx.send("Stats collection is disabled on this server.")
            return
        sessions = await self._get_member_sessions(member, guild)
        if not sessions:
            await ctx.send("No sessions to export.")
            return
        now = _epoch_now()
        if period.endswith("d"):
            try:
                days = int(period[:-1])
            except Exception:
                await ctx.send("Period must be like '7d', '30d', or 'all'.")
                return
            cutoff = now - _days_to_seconds(days)
            filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
        elif period == "all":
            filtered = sessions
        else:
            await ctx.send("Period must be like '7d', '30d', or 'all'.")
            return
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["start_iso", "end_iso", "start_epoch", "end_epoch", "duration_seconds", "game", "platform", "url"])
        for s in filtered:
            start = s.get("start")
            end = s.get("end")
            writer.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)) if start else "",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end)) if end else "",
                start or "",
                end or "",
                s.get("duration", ""),
                s.get("game", "") or "",
                s.get("platform", "") or "",
                s.get("url", "") or "",
            ])
        buf.seek(0)
        data = io.BytesIO(buf.getvalue().encode("utf-8"))
        fname = f"{member.display_name}-stream-stats-{period}.csv"
        await ctx.send(file=discord.File(fp=data, filename=fname))

    @stats.command(name="top")
    async def stats_top(self, ctx: commands.Context, metric: str = "time", period: str = "7d", limit: int = 10):
        guild = ctx.guild
        if limit < 1:
            await ctx.send("Limit must be at least 1.")
            return
        limit = min(limit, 50)
        if metric not in ("time", "count"):
            await ctx.send("Metric must be 'time' or 'count'.")
            return
        if period not in ("7d", "30d", "all", "30d"):
            await ctx.send("Period must be '7d', '30d', or 'all'.")
            return
        if not await self.conf.guild(guild).stats.enabled():
            await ctx.send("Stats collection is disabled on this server.")
            return
        now = _epoch_now()
        if period.endswith("d"):
            days = int(period[:-1])
            cutoff = now - _days_to_seconds(days)
        else:
            cutoff = 0
        results = []
        retention_days = await self.conf.guild(guild).stats.retention_days()
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if not sessions:
                continue
            filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            if not filtered:
                continue
            if metric == "time":
                val = sum(s.get("duration", 0) for s in filtered)
            else:
                val = len(filtered)
            results.append((member, val))
        results.sort(key=lambda x: x[1], reverse=True)
        top = results[:limit]
        if not top:
            await ctx.send("No data for the requested period.")
            return
        embed = discord.Embed(title=f"Top {len(top)} streamers by {'time' if metric=='time' else 'streams'} ({period})", colour=await ctx.embed_colour())
        for idx, (member, val) in enumerate(top, start=1):
            if metric == "time":
                value_str = self._format_seconds(val)
            else:
                value_str = str(val)
            embed.add_field(name=f"{idx}. {member.display_name}", value=value_str, inline=False)
        await ctx.send(embed=embed)

    # -----------------
    # API management command (server-side token)
    # -----------------
    @checks.is_owner()
    @streamrole.command(name="setapitoken")
    async def setapitoken(self, ctx: commands.Context, token: Optional[str]):
        """
        Set or clear the API token for this guild (server-side).
        Usage:
         - streamrole setapitoken <token>   -> sets the token for guild
         - streamrole setapitoken none      -> clears the token
        Note: owner-only by default; change decorator if you want admins to set tokens.
        """
        if token is None or token.lower() == "none":
            await self.conf.guild(ctx.guild).api_token.set(None)
            await ctx.send("Cleared API token for this guild. The dashboard proxy will not serve data for this guild until a token is set.")
            return
        await self.conf.guild(ctx.guild).api_token.set(token)
        await ctx.send("API token stored for this guild on the server. Dashboard proxy will use it. Keep it secret.")

    # -----------------
    # Fixed guild ID management (stored in guild config to avoid redeploy)
    # -----------------
    @checks.is_owner()
    @streamrole.command(name="setfixedguild")
    async def setfixedguild(self, ctx: commands.Context, guild_id: Optional[str]):
        """
        Set or clear the fixed guild id used by the dashboard proxy for this bot instance.
        Usage:
         - streamrole setfixedguild <guild_id>  -> sets fixed guild id (numeric) in this guild's config
         - streamrole setfixedguild none        -> clears the fixed guild id
        Note: storing fixed_guild_id in a guild's config allows the proxy to find it at runtime without env changes.
        """
        if guild_id is None or guild_id.lower() == "none":
            await self.conf.guild(ctx.guild).fixed_guild_id.set(None)
            await ctx.send("Cleared fixed guild id for this guild.")
            return
        if not guild_id.isdigit():
            await ctx.send("guild_id must be numeric.")
            return
        await self.conf.guild(ctx.guild).fixed_guild_id.set(int(guild_id))
        await ctx.send(f"Fixed guild id set to {guild_id} for this guild.")

    # -----------------
    # Twitch channel watching commands
    # -----------------
    @streamrole.group(name="twitch", autohelp=True)
    async def twitch_group(self, ctx: commands.Context):
        """Manage Twitch channel watching and tracking."""
        pass

    @twitch_group.command(name="watch")
    async def twitch_watch(self, ctx: commands.Context, channel: discord.TextChannel):
        """Start watching a channel for Twitch links.
        
        When a message with a Twitch link is posted in a watched channel,
        the Twitch channel will be automatically added to tracking.
        """
        await self.twitch_watcher.add_watched_channel(ctx.guild, channel.id)
        await ctx.send(f"Now watching {channel.mention} for Twitch links. Any Twitch channels posted here will be automatically tracked.")

    @twitch_group.command(name="unwatch")
    async def twitch_unwatch(self, ctx: commands.Context, channel: discord.TextChannel):
        """Stop watching a channel for Twitch links."""
        await self.twitch_watcher.remove_watched_channel(ctx.guild, channel.id)
        await ctx.send(f"Stopped watching {channel.mention} for Twitch links.")

    @twitch_group.command(name="listwatched")
    async def twitch_list_watched(self, ctx: commands.Context):
        """List all channels being watched for Twitch links."""
        watched = await self.twitch_watcher.get_watched_channels(ctx.guild)
        if not watched:
            await ctx.send("No channels are currently being watched for Twitch links.")
            return
        
        channel_mentions = []
        for channel_id in watched:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                channel_mentions.append(channel.mention)
            else:
                channel_mentions.append(f"<deleted channel {channel_id}>")
        
        await ctx.send(f"**Watched channels:**\n" + "\n".join(channel_mentions))

    @twitch_group.command(name="scan")
    async def twitch_scan_history(
        self, 
        ctx: commands.Context, 
        channel: discord.TextChannel, 
        limit: int = 100
    ):
        """Scan a channel's history for Twitch links and add them to tracking.
        
        Args:
            channel: The channel to scan
            limit: Number of recent messages to scan (default: 100, max: 1000)
        """
        if limit < 1 or limit > 1000:
            await ctx.send("Limit must be between 1 and 1000.")
            return
        
        async with ctx.typing():
            messages_scanned, newly_added = await self.twitch_watcher.scan_channel_history(channel, limit)
        
        if newly_added:
            channels_list = "\n".join([f"• twitch.tv/{ch}" for ch in newly_added])
            await ctx.send(
                f"✅ Scanned {messages_scanned} messages in {channel.mention}\n"
                f"**Found {len(newly_added)} new Twitch channels:**\n{channels_list}"
            )
        else:
            await ctx.send(
                f"Scanned {messages_scanned} messages in {channel.mention}\n"
                f"No new Twitch channels found (all were already tracked)."
            )

    @twitch_group.command(name="list")
    async def twitch_list_tracked(self, ctx: commands.Context):
        """List all tracked Twitch channels."""
        tracked = await self.twitch_watcher.get_tracked_twitch_channels(ctx.guild)
        if not tracked:
            await ctx.send("No Twitch channels are currently being tracked.")
            return
        
        # Sort alphabetically
        tracked_sorted = sorted(tracked)
        
        # Format in pages if there are many
        pages = []
        page_size = 20
        for i in range(0, len(tracked_sorted), page_size):
            chunk = tracked_sorted[i:i+page_size]
            channels_list = "\n".join([f"• twitch.tv/{ch}" for ch in chunk])
            pages.append(f"**Tracked Twitch Channels ({len(tracked)} total):**\n{channels_list}")
        
        if len(pages) == 1:
            await ctx.send(pages[0])
        else:
            # Use menu for multiple pages
            await menus.menu(ctx, pages, menus.DEFAULT_CONTROLS)

    @twitch_group.command(name="add")
    async def twitch_add_channel(self, ctx: commands.Context, twitch_username: str):
        """Manually add a Twitch channel to tracking.
        
        Args:
            twitch_username: The Twitch username to track (without twitch.tv/)
        """
        # Clean the username (remove any URL parts)
        username = twitch_username.strip().lower()
        username = username.replace("https://", "").replace("http://", "")
        username = username.replace("www.", "").replace("twitch.tv/", "")
        username = username.split("/")[0]  # Take only the username part
        
        if not username or len(username) < 4 or len(username) > 25:
            await ctx.send("Invalid Twitch username. Usernames must be 4-25 characters.")
            return
        
        if await self.twitch_watcher.is_twitch_channel_tracked(ctx.guild, username):
            await ctx.send(f"Twitch channel `{username}` is already being tracked.")
            return
        
        await self.twitch_watcher.add_twitch_channel(ctx.guild, username)
        await ctx.send(f"✅ Added Twitch channel `{username}` to tracking.")

    @twitch_group.command(name="remove")
    async def twitch_remove_channel(self, ctx: commands.Context, twitch_username: str):
        """Remove a specific Twitch channel from tracking.
        
        Args:
            twitch_username: The Twitch username to remove (without twitch.tv/)
        """
        # Clean the username
        username = twitch_username.strip().lower()
        username = username.replace("https://", "").replace("http://", "")
        username = username.replace("www.", "").replace("twitch.tv/", "")
        username = username.split("/")[0]
        
        if await self.twitch_watcher.remove_twitch_channel(ctx.guild, username):
            await ctx.send(f"✅ Removed Twitch channel `{username}` from tracking.")
        else:
            await ctx.send(f"Twitch channel `{username}` was not found in tracking.")

    @twitch_group.command(name="flush")
    async def twitch_flush_all(self, ctx: commands.Context):
        """Remove all tracked Twitch channels.
        
        ⚠️ This will clear all tracked Twitch channels for this server.
        """
        tracked = await self.twitch_watcher.get_tracked_twitch_channels(ctx.guild)
        if not tracked:
            await ctx.send("No Twitch channels are currently being tracked.")
            return
        
        # Confirmation
        msg = await ctx.send(
            f"⚠️ **Warning:** This will remove all {len(tracked)} tracked Twitch channels from this server.\n"
            f"Are you sure you want to continue?"
        )
        menus.start_adding_reactions(msg, predicates.ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = predicates.ReactionPredicate.yes_or_no(msg, ctx.author)
        
        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=30.0)
        except asyncio.TimeoutError:
            await ctx.send("Action cancelled (timed out).")
            return
        
        if pred.result:
            await self.twitch_watcher.clear_all_twitch_channels(ctx.guild)
            await ctx.send(f"✅ Cleared all {len(tracked)} tracked Twitch channels.")
        else:
            await ctx.send("Action cancelled.")

    # -----------------
    # Core helpers
    # -----------------
    async def get_streamer_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        role_id = await self.conf.guild(guild).streamer_role()
        if not role_id:
            return
        try:
            role = next(r for r in guild.roles if r.id == role_id)
        except StopIteration:
            return
        else:
            return role

    async def get_alerts_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        alerts_data = await self.conf.guild(guild).alerts.all()
        if not alerts_data["enabled"]:
            return
        return guild.get_channel(alerts_data["channel"])

    async def get_required_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        role_id = await self.conf.guild(guild).required_role()
        if not role_id:
            return None
        return guild.get_role(role_id)

    # -----------------
    # Session storage helpers
    # -----------------
    async def _get_member_sessions(self, member: discord.Member, guild: discord.Guild) -> List[dict]:
        data = await self.conf.member(member).stream_stats()
        if not isinstance(data, list):
            return []
        sessions = [s for s in data if isinstance(s, dict) and "start" in s]
        sessions.sort(key=lambda s: s.get("start", 0))
        return sessions

    async def _add_session_for_member(self, member: discord.Member, session: dict, guild: discord.Guild):
        if not await self.conf.guild(guild).stats.enabled():
            return
        retention_days = await self.conf.guild(guild).stats.retention_days()
        cutoff = _epoch_now() - _days_to_seconds(retention_days)
        async with self.conf.member(member).stream_stats() as lst:
            lst.append(session)
            pruned = [s for s in lst if s.get("start", 0) >= cutoff]
            lst.clear()
            lst.extend(pruned)
        log.debug("Added session for %s: start=%s dur=%s", member.id, session.get("start"), session.get("duration"))

    # -----------------
    # Presence / session detection and main logic
    # (unchanged from original)
    # -----------------
    async def _update_member(self, member: discord.Member, role: Optional[discord.Role] = None, alerts_channel: Optional[discord.TextChannel] = _alerts_channel_sentinel) -> None:
        role = role or await self.get_streamer_role(member.guild)
        if role is None:
            return
        channel = alerts_channel if alerts_channel is not _alerts_channel_sentinel else await self.get_alerts_channel(member.guild)
        required = await self.get_required_role(member.guild)
        if required is not None and required not in member.roles:
            if role in member.roles:
                log.debug("Removing streamrole %s from member %s because they lack required role %s", role.id, member.id, required.id)
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            current_start = await self.conf.member(member).current_stream_start()
            if current_start:
                await self.conf.member(member).current_stream_start.set(None)
            return
        activity = next((a for a in member.activities if isinstance(a, discord.Streaming)), None)
        if activity is None or not getattr(activity, "platform", None):
            await self._finalize_current_session_if_any(member, activity, channel)
            if role in member.roles:
                log.debug("Removing streamrole %s from member %s", role.id, member.id)
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            return
        platform = str(getattr(activity, "platform", "") or "").lower()
        url = str(getattr(activity, "url", "") or "").lower()
        if "twitch" not in platform and "twitch.tv" not in url:
            await self._finalize_current_session_if_any(member, activity, channel)
            if role in member.roles:
                log.debug("Removing streamrole %s from member %s because stream is not Twitch", role.id, member.id)
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            return
        was_streaming = bool(await self.conf.member(member).current_stream_start())
        if not was_streaming:
            now = _epoch_now()
            await self.conf.member(member).current_stream_start.set(now)
            log.debug("Detected Twitch stream start for %s at %s", member.id, now)
        if role not in member.roles:
            log.debug("Adding streamrole %s to member %s", role.id, member.id)
            await member.add_roles(role)
            if channel:
                await self._post_alert(member, activity, getattr(activity, "game", None), channel)

    async def _finalize_current_session_if_any(self, member: discord.Member, activity, channel):
        start = await self.conf.member(member).current_stream_start()
        if not start:
            return
        end = _epoch_now()
        duration = max(0, end - start)
        game = getattr(activity, "game", None) or None
        platform = getattr(activity, "platform", None) or "Twitch"
        url = getattr(activity, "url", None) or None
        session = {
            "start": start,
            "end": end,
            "duration": duration,
            "game": str(game) if game else None,
            "platform": str(platform) if platform else None,
            "url": str(url) if url else None,
        }
        await self._add_session_for_member(member, session, member.guild)
        await self.conf.member(member).current_stream_start.set(None)
        log.debug("Finalized session for %s: %s seconds", member.id, duration)
        if channel and await self.conf.guild(member.guild).alerts.autodelete():
            await self._remove_alert(member, channel)

    async def _update_members_with_role(self, role: discord.Role) -> None:
        streamer_role = await self.get_streamer_role(role.guild)
        if streamer_role is None:
            return
        alerts_channel = await self.get_alerts_channel(role.guild)
        if await self.conf.guild(role.guild).mode() == FilterList.blacklist:
            for member in role.members:
                if streamer_role in member.roles:
                    log.debug("Removing streamrole %s from member %s after role %s was blacklisted", streamer_role.id, member.id, role.id)
                    await member.remove_roles(streamer_role, reason=f"Removing streamrole after {role} role was blacklisted")
        else:
            for member in role.members:
                await self._update_member(member, streamer_role, alerts_channel)

    async def _update_guild(self, guild: discord.Guild) -> None:
        streamer_role = await self.get_streamer_role(guild)
        if streamer_role is None:
            return
        alerts_channel = await self.get_alerts_channel(guild)
        for member in guild.members:
            await self._update_member(member, streamer_role, alerts_channel)

    # -----------------
    # Alerts helpers
    # -----------------
    async def _post_alert(self, member: discord.Member, activity: discord.Streaming, game: Optional[str], channel: discord.TextChannel) -> discord.Message:
        content = f"{chatutils.bold(member.display_name)} is now live on {activity.platform}"
        if game is not None:
            content += f", playing {chatutils.italics(str(game))}"
        content += f"!\n\nTitle: {chatutils.italics(activity.name)}\nURL: {activity.url}"
        msg = await channel.send(content)
        await self.conf.member(member).alert_messages.set_raw(str(channel.id), value=msg.id)
        return msg

    async def _remove_alert(self, member: discord.Member, channel: discord.TextChannel) -> None:
        conf_group = self.conf.member(member).alert_messages
        msg_id = await conf_group.get_raw(str(channel.id), default=None)
        if msg_id is None:
            return
        await conf_group.clear_raw(str(channel.id))
        msg: Optional[discord.Message] = discord.utils.get(getattr(self.bot, "cached_messages", ()), id=msg_id)
        if msg is None:
            try:
                msg = await channel.fetch_message(msg_id)
            except discord.NotFound:
                return
        with contextlib.suppress(discord.NotFound):
            await msg.delete()

    # -----------------
    # Events
    # -----------------
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._update_guild(guild)

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.activities != after.activities:
            await self._update_member(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._update_member(member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for messages containing Twitch links in watched channels."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Process message for Twitch links
        newly_added = await self.twitch_watcher.process_message_for_twitch_links(message)
        
        # Optionally notify about newly added channels (can be disabled if too spammy)
        # if newly_added and self.DEBUG_MODE:
        #     log.debug(f"Auto-added {len(newly_added)} Twitch channels from message in {message.guild.id}")

    # -----------------
    # Filter helpers
    # -----------------
    async def _get_filter_list(self, guild: discord.Guild, mode: FilterList) -> Tuple[List[discord.Member], List[discord.Role]]:
        all_member_data = await self.conf.all_members(guild)
        all_role_data = await self.conf.all_roles()
        mode = mode.as_participle()
        member_ids = (u for u, d in all_member_data.items() if d.get(mode))
        role_ids = (u for u, d in all_role_data.items() if d.get(mode))
        members = list(filter(None, map(guild.get_member, member_ids)))
        roles = list(filter(None, map(guild.get_role, role_ids)))
        return members, roles

    async def _update_filter_list_entry(self, member_or_role: Union[discord.Member, discord.Role], filter_list: FilterList, value: bool) -> None:
        if isinstance(member_or_role, discord.Member):
            await self.conf.member(member_or_role).set_raw(filter_list.as_participle(), value=value)
            await self._update_member(member_or_role)
        else:
            await self.conf.role(member_or_role).set_raw(filter_list.as_participle(), value=value)
            await self._update_members_with_role(member_or_role)

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        seconds = int(seconds)
        hours, rem = divmod(seconds, 3600)
        minutes, sec = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {sec}s"
        return f"{sec}s"

    # -----------------
    # Embedded API server implementation
    # -----------------
    async def cog_load(self) -> None:
        """Start aiohttp app when cog is loaded. Also call initialize if present."""
        with contextlib.suppress(Exception):
            init = getattr(self, "initialize", None)
            if init is not None:
                try:
                    await init()
                except Exception:
                    log.exception("Error during StreamRoles.initialize()")
        if aiohttp is None or web is None:
            log.info("aiohttp not available; embedded API disabled.")
            return
        await self._start_api()

    async def cog_unload(self) -> None:
        await self._stop_api()

    def _client_ip_allowed(self, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
        except Exception:
            return False
        return any(ip in net for net in self._allowed_nets)

    def _make_local_only_middleware(self):
        @web.middleware
        async def local_only_middleware(request, handler):
            path = request.rel_url.path
            # restrict only /api/* endpoints
            if path.startswith("/api/"):
                xff = request.headers.get("X-Forwarded-For")
                if xff:
                    client_ip = xff.split(",")[0].strip()
                else:
                    peer = request.transport.get_extra_info("peername")
                    client_ip = peer[0] if peer else None
                if not client_ip or not self._client_ip_allowed(client_ip):
                    return web.Response(status=403, text="Forbidden")
            return await handler(request)
        return local_only_middleware

    async def _start_api(self):
        if self._api_runner:
            return
        app = web.Application(middlewares=[self._make_local_only_middleware()])
        # Public dashboard + proxy routes (public)
        app.add_routes(
            [
                web.get("/", self._handle_index),
                web.get("/dashboard", self._handle_dashboard),
                web.post("/dashboard/proxy/top", self._proxy_handle_top),
                web.post("/dashboard/proxy/member/{guild_id}/{member_id}", self._proxy_handle_member),
                web.post("/dashboard/proxy/export/{guild_id}/{member_id}", self._proxy_handle_export),
                web.post("/dashboard/proxy/heatmap", self._proxy_handle_heatmap),
                web.post("/dashboard/proxy/all_members", self._proxy_handle_all_members),
                web.post("/dashboard/proxy/badges/{guild_id}/{member_id}", self._proxy_handle_badges),
                web.post("/dashboard/proxy/badges_batch", self._proxy_handle_badges_batch),
                web.post("/dashboard/proxy/achievements", self._proxy_handle_achievements),
                web.post("/dashboard/proxy/schedule_predictor", self._proxy_handle_schedule_predictor),
                web.post("/dashboard/proxy/audience_overlap", self._proxy_handle_audience_overlap),
                web.post("/dashboard/proxy/collaboration_matcher", self._proxy_handle_collaboration_matcher),
                web.post("/dashboard/proxy/community_health", self._proxy_handle_community_health),
                # Internal local-only API (blocked by middleware)
                web.get("/api/guild/{guild_id}/member/{member_id}", self._handle_member_stats),
                web.get("/api/guild/{guild_id}/top", self._handle_top),
                web.get("/api/guild/{guild_id}/export/member/{member_id}", self._handle_export_csv),
            ]
        )
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._api_host, self._api_port)
        await site.start()
        self._api_runner = runner
        self._api_site = site
        self._api_app = app
        log.info("StreamRoles API started on http://%s:%s", self._api_host, self._api_port)

    async def _stop_api(self):
        if self._api_runner:
            try:
                await self._api_runner.cleanup()
                log.info("StreamRoles API stopped")
            except Exception:
                log.exception("Error stopping StreamRoles API")
            finally:
                self._api_runner = None
                self._api_site = None
                self._api_app = None

    async def _authorize(self, request: web.Request, guild_id: int) -> bool:
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return False
        token = await self.conf.guild(guild).api_token()
        if not token:
            return False
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            provided = header[len("Bearer ") :].strip()
            return provided == token
        return False

    def _parse_period(self, period: str):
        now = int(time.time())
        if not period or period == "all":
            return 0
        if period.endswith("d"):
            try:
                days = int(period[:-1])
            except Exception:
                return None
            return now - int(days) * 86400
        return None

    # ---------- API handlers (internal, local-only) ----------
    async def _handle_index(self, request: web.Request):
        return web.Response(text="StreamRoles API is running.", content_type="text/plain")

    async def _handle_dashboard(self, request: web.Request):
        # Serve static dashboard file if present in package static/ or the embedded HTML fallback
        try:
            base = os.path.dirname(__file__)
            static_path = os.path.join(base, "static", "dashboard.html")
            if os.path.exists(static_path):
                return web.FileResponse(path=static_path)
        except Exception:
            pass
        # fallback embedded HTML (minimal)
        html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>StreamRoles Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>body{font-family:Arial;margin:20px}input,select{margin:5px}#controls{margin-bottom:10px}</style>
</head>
<body>
  <h2>StreamRoles - Minimal Dashboard</h2>
  <div id="controls">
    <label>Period: <select id="period"><option value="7d">7d</option><option value="30d" selected>30d</option><option value="all">all</option></select></label>
    <button id="fetchTop">Fetch Top by Time</button>
  </div>
  <canvas id="topChart" width="900" height="350"></canvas>
  <script>
    async function fetchTop() {
      const period = document.getElementById('period').value;
      const resp = await fetch('/dashboard/proxy/top', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metric: 'time', period: period, limit: 10 })
      });
      if(!resp.ok){ alert('Error: ' + resp.status); return; }
      const data = await resp.json();
      const labels = data.map(x => x.display_name);
      const values = data.map(x => x.value_hours);
      const ctx = document.getElementById('topChart').getContext('2d');
      if(window._topChart) window._topChart.destroy();
      window._topChart = new Chart(ctx, {
        type: 'bar',
        data: { labels: labels, datasets: [{ label: 'Hours', data: values, backgroundColor: 'rgba(54,162,235,0.6)' }]},
        options: { responsive: true, scales: { y: { beginAtZero: true } } }
      });
    }
    document.getElementById('fetchTop').onclick = fetchTop;
  </script>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    async def _handle_member_stats(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        member_id = request.match_info.get("member_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")
        period = request.query.get("period", "30d")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        sessions = await self._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        total_streams = len(sessions)
        total_time = sum(s.get("duration", 0) for s in sessions)
        avg_duration = total_time / total_streams if total_streams else 0
        response = {
            "member_id": member.id,
            "display_name": member.display_name,
            "period": period,
            "total_streams": total_streams,
            "total_time_seconds": total_time,
            "avg_duration_seconds": avg_duration,
            "sessions": sessions,
        }
        return web.json_response(response)

    async def _handle_top(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        metric = request.query.get("metric", "time")
        period = request.query.get("period", "7d")
        limit = int(request.query.get("limit", "10"))
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        results = []
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            if not filtered:
                continue
            if metric == "time":
                val_sec = sum(s.get("duration", 0) for s in filtered)
            else:
                val_sec = len(filtered)
            results.append({"member_id": member.id, "display_name": member.display_name, "value": val_sec})
        results.sort(key=lambda x: x["value"], reverse=True)
        top = results[:limit]
        for r in top:
            r["value_hours"] = round(r["value"] / 3600, 2) if metric == "time" else r["value"]
        return web.json_response(top)

    async def _handle_export_csv(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        member_id = request.match_info.get("member_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")
        period = request.query.get("period", "all")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        sessions = await self._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["start_iso", "end_iso", "start_epoch", "end_epoch", "duration_seconds", "game", "platform", "url"])
        for s in sessions:
            start = s.get("start")
            end = s.get("end")
            writer.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)) if start else "",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end)) if end else "",
                start or "",
                end or "",
                s.get("duration", ""),
                s.get("game", "") or "",
                s.get("platform", "") or "",
                s.get("url", "") or "",
            ])
        data = buf.getvalue().encode("utf-8")
        return web.Response(body=data, headers={
            "Content-Type": "text/csv",
            "Content-Disposition": f'attachment; filename="{member.display_name}-stream-stats-{period}.csv"'
        })

    # ---------- Dashboard proxy handlers (public) ----------
    async def _proxy_handle_top(self, request: web.Request):
        """
        POST JSON: { metric, period, limit } (guild resolved from stored fixed_guild_id or payload guild_id)
        Uses server-stored token (api_token in Config) and internal helpers.
        """
        # defensive JSON parse + fallback to {}
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/top")
                payload = {}

        # resolve guild: prefer payload.guild_id if present; else find the first guild that has fixed_guild_id set in config
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            # scan guilds for a configured fixed_guild_id (first match)
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    # if numeric and matches, use; otherwise still use the guild where it's set
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        metric = payload.get("metric", "time")
        period = payload.get("period", "7d")
        try:
            limit = int(payload.get("limit", 10))
        except Exception:
            limit = 10

        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")

        results = []
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            if not filtered:
                continue
            if metric == "time":
                val_sec = sum(s.get("duration", 0) for s in filtered)
            else:
                val_sec = len(filtered)
            results.append({"member_id": member.id, "display_name": member.display_name, "value": val_sec})
        results.sort(key=lambda x: x["value"], reverse=True)
        top = results[:limit]
        for r in top:
            r["value_hours"] = round(r["value"] / 3600, 2) if metric == "time" else r["value"]
        return web.json_response(top)

    async def _proxy_handle_member(self, request: web.Request):
        # prefer fixed_guild_id from any configured guild; else use path param guild_id
        member_id = request.match_info.get("member_id")
        guild = None
        # check path param first
        if request.match_info.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(request.match_info.get("guild_id")))
            except Exception:
                guild = None
        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        if not member_id:
            return web.Response(status=400, text="member_id required")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        period = "30d"
        if request.content_length:
            try:
                body = await request.json()
                period = body.get("period", period)
            except Exception:
                pass

        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")

        sessions = await self._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        total_streams = len(sessions)
        total_time = sum(s.get("duration", 0) for s in sessions)
        avg_duration = total_time / total_streams if total_streams else 0
        response = {
            "member_id": member.id,
            "display_name": member.display_name,
            "period": period,
            "total_streams": total_streams,
            "total_time_seconds": total_time,
            "avg_duration_seconds": avg_duration,
            "sessions": sessions,
        }
        return web.json_response(response)

    async def _proxy_handle_export(self, request: web.Request):
        member_id = request.match_info.get("member_id")
        guild = None
        if request.match_info.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(request.match_info.get("guild_id")))
            except Exception:
                guild = None
        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        if not member_id:
            return web.Response(status=400, text="member_id required")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        period = "all"
        if request.content_length:
            try:
                body = await request.json()
                period = body.get("period", period)
            except Exception:
                pass
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        sessions = await self._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["start_iso", "end_iso", "start_epoch", "end_epoch", "duration_seconds", "game", "platform", "url"])
        for s in sessions:
            start = s.get("start")
            end = s.get("end")
            writer.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)) if start else "",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end)) if end else "",
                start or "",
                end or "",
                s.get("duration", ""),
                s.get("game", "") or "",
                s.get("platform", "") or "",
                s.get("url", "") or "",
            ])
        data = buf.getvalue().encode("utf-8")
        return web.Response(body=data, headers={
            "Content-Type": "text/csv",
            "Content-Disposition": f'attachment; filename="{member.display_name}-stream-stats-{period}.csv"'
        })
    async def _proxy_handle_heatmap(self, request: web.Request):
        """
        POST JSON: { period } (guild resolved from stored fixed_guild_id or payload guild_id)
        Returns heatmap data for weekly streaming patterns.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/heatmap")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        period = payload.get("period", "30d")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")

        # Collect all sessions across all members
        heatmap_data = {}
        for day in range(7):
            heatmap_data[day] = {}
            for hour in range(24):
                heatmap_data[day][hour] = 0

        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            
            for session in filtered:
                start = session.get("start")
                if not start:
                    continue
                # Convert to time struct
                dt = time.gmtime(start)
                day_of_week = (dt.tm_wday + 1) % 7  # Convert Monday=0 to Sunday=0 (Monday->1, Sunday->0)
                hour = dt.tm_hour
                heatmap_data[day_of_week][hour] += 1

        # Convert to list format for easier processing in JS
        result = []
        for day in range(7):
            for hour in range(24):
                result.append({
                    "day": day,
                    "hour": hour,
                    "count": heatmap_data[day][hour]
                })

        return web.json_response(result)

    async def _proxy_handle_all_members(self, request: web.Request):
        """
        POST JSON: { period } (guild resolved from stored fixed_guild_id or payload guild_id)
        Returns all members with streaming stats and their roles.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/all_members")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        period = payload.get("period", "30d")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")

        # Role name to category mapping
        role_mapping = {
            "Seed": "seed",
            "Sprout": "sprout",
            "Flower": "flower",
            "Rosegarden": "rosegarden",
            "Eden": "eden",
            "Patrons": "patrons",
            "Sponsor": "sponsor",
            "Garden Guardian": "garden_guardian",
            "Admin": "admin"
        }

        results = []
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            
            if not filtered:
                continue

            # Determine member role
            member_role = None
            for role in member.roles:
                role_name = role.name
                if role_name in role_mapping:
                    member_role = role_mapping[role_name]
                    break

            total_time = sum(s.get("duration", 0) for s in filtered)
            total_streams = len(filtered)
            
            results.append({
                "member_id": member.id,
                "display_name": member.display_name,
                "role": member_role,
                "total_streams": total_streams,
                "total_time_seconds": total_time,
                "total_time_hours": round(total_time / 3600, 2)
            })

        # Sort by total time descending
        results.sort(key=lambda x: x["total_time_seconds"], reverse=True)

        return web.json_response(results)

    async def _proxy_handle_badges(self, request: web.Request):
        """
        POST /dashboard/proxy/badges/{guild_id}/{member_id}
        Returns badges for a specific member.
        """
        member_id = request.match_info.get("member_id")
        guild = None
        if request.match_info.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(request.match_info.get("guild_id")))
            except Exception:
                guild = None
        
        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        if not member_id:
            return web.Response(status=400, text="member_id required")
        
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        sessions = await self._get_member_sessions(member, guild)
        badges = calculate_member_badges(sessions)
        
        return web.json_response(badges)

    async def _proxy_handle_achievements(self, request: web.Request):
        """
        POST /dashboard/proxy/achievements
        Returns guild-wide achievements with current holders.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/achievements")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        # Collect all member data
        all_member_data = {}
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            if sessions:
                all_member_data[member.id] = {
                    "sessions": sessions,
                    "display_name": member.display_name
                }
        
        achievements = calculate_guild_achievements(all_member_data)
        
        return web.json_response(achievements)

    async def _proxy_handle_badges_batch(self, request: web.Request):
        """
        POST /dashboard/proxy/badges_batch
        Returns badges for multiple members in a single request.
        Payload: { member_ids: [id1, id2, ...] }
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/badges_batch")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        member_ids = payload.get("member_ids", [])
        if not member_ids:
            return web.Response(status=400, text="member_ids required")

        # Fetch badges for all members
        result = {}
        for member_id in member_ids:
            try:
                member = guild.get_member(int(member_id))
                if member:
                    sessions = await self._get_member_sessions(member, guild)
                    badges = calculate_member_badges(sessions)
                    
                    # Calculate summary
                    earned = sum(1 for b in badges.values() if b["earned"])
                    total = len(badges)
                    
                    result[str(member_id)] = {
                        "earned": earned,
                        "total": total,
                        "badges": badges
                    }
            except Exception as e:
                log.exception(f"Error fetching badges for member {member_id}: {e}")
                continue

        return web.json_response(result)

    async def _proxy_handle_schedule_predictor(self, request: web.Request):
        """
        POST /dashboard/proxy/schedule_predictor
        Returns optimal streaming schedule predictions based on historical data.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/schedule_predictor")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        member_id = payload.get("member_id")
        if not member_id:
            return web.Response(status=400, text="member_id required")
        
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")

        sessions = await self._get_member_sessions(member, guild)
        
        # Analyze streaming patterns
        day_hour_counts = {}
        for day in range(7):
            day_hour_counts[day] = {}
            for hour in range(24):
                day_hour_counts[day][hour] = 0
        
        for session in sessions:
            start = session.get("start")
            if not start:
                continue
            dt = time.gmtime(start)
            day_of_week = (dt.tm_wday + 1) % 7
            hour = dt.tm_hour
            day_hour_counts[day_of_week][hour] += 1
        
        # Find top 5 time slots
        all_slots = []
        for day in range(7):
            for hour in range(24):
                count = day_hour_counts[day][hour]
                if count > 0:
                    all_slots.append({
                        "day": day,
                        "hour": hour,
                        "count": count,
                        "day_name": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][day]
                    })
        
        all_slots.sort(key=lambda x: x["count"], reverse=True)
        top_slots = all_slots[:5]
        
        # Calculate suggested times (times with low community activity)
        community_activity = {}
        for day in range(7):
            community_activity[day] = {}
            for hour in range(24):
                community_activity[day][hour] = 0
        
        for m in guild.members:
            m_sessions = await self._get_member_sessions(m, guild)
            for session in m_sessions:
                start = session.get("start")
                if not start:
                    continue
                dt = time.gmtime(start)
                day_of_week = (dt.tm_wday + 1) % 7
                hour = dt.tm_hour
                community_activity[day_of_week][hour] += 1
        
        # Find low-activity slots
        low_activity_slots = []
        for day in range(7):
            for hour in range(24):
                # Prefer reasonable streaming hours (8am - 2am, which is 8-23 or 0-2)
                if (8 <= hour <= 23) or (0 <= hour <= 2):
                    low_activity_slots.append({
                        "day": day,
                        "hour": hour,
                        "community_count": community_activity[day][hour],
                        "day_name": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][day]
                    })
        
        low_activity_slots.sort(key=lambda x: x["community_count"])
        suggested_slots = low_activity_slots[:5]
        
        return web.json_response({
            "member_id": member.id,
            "display_name": member.display_name,
            "top_performing_times": top_slots,
            "suggested_low_competition_times": suggested_slots
        })

    async def _proxy_handle_audience_overlap(self, request: web.Request):
        """
        POST /dashboard/proxy/audience_overlap
        Returns audience overlap analysis showing which streamers share similar time slots.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/audience_overlap")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        member_id = payload.get("member_id")
        if not member_id:
            return web.Response(status=400, text="member_id required")
        
        target_member = guild.get_member(int(member_id))
        if not target_member:
            return web.Response(status=404, text="Member not found")

        target_sessions = await self._get_member_sessions(target_member, guild)
        
        # Build target member's streaming time slots
        target_slots = set()
        for session in target_sessions:
            start = session.get("start")
            if not start:
                continue
            dt = time.gmtime(start)
            day_of_week = (dt.tm_wday + 1) % 7
            hour = dt.tm_hour
            target_slots.add((day_of_week, hour))
        
        # Calculate overlap with other members
        overlaps = []
        for member in guild.members:
            if member.id == target_member.id:
                continue
            
            sessions = await self._get_member_sessions(member, guild)
            if not sessions:
                continue
            
            member_slots = set()
            for session in sessions:
                start = session.get("start")
                if not start:
                    continue
                dt = time.gmtime(start)
                day_of_week = (dt.tm_wday + 1) % 7
                hour = dt.tm_hour
                member_slots.add((day_of_week, hour))
            
            # Calculate overlap percentage
            if not member_slots:
                continue
            
            overlap = len(target_slots & member_slots)
            if overlap > 0:
                overlap_pct = (overlap / len(target_slots)) * 100
                overlaps.append({
                    "member_id": member.id,
                    "display_name": member.display_name,
                    "overlap_count": overlap,
                    "overlap_percentage": round(overlap_pct, 1)
                })
        
        overlaps.sort(key=lambda x: x["overlap_percentage"], reverse=True)
        
        return web.json_response({
            "member_id": target_member.id,
            "display_name": target_member.display_name,
            "overlaps": overlaps[:10]  # Top 10
        })

    async def _proxy_handle_collaboration_matcher(self, request: web.Request):
        """
        POST /dashboard/proxy/collaboration_matcher
        Suggests streamers for potential collaborations based on compatible schedules.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/collaboration_matcher")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        member_id = payload.get("member_id")
        if not member_id:
            return web.Response(status=400, text="member_id required")
        
        target_member = guild.get_member(int(member_id))
        if not target_member:
            return web.Response(status=404, text="Member not found")

        target_sessions = await self._get_member_sessions(target_member, guild)
        
        # Build target member's streaming time slots
        target_slots = set()
        for session in target_sessions:
            start = session.get("start")
            if not start:
                continue
            dt = time.gmtime(start)
            day_of_week = (dt.tm_wday + 1) % 7
            hour = dt.tm_hour
            target_slots.add((day_of_week, hour))
        
        # Find members with COMPLEMENTARY schedules (low overlap = good for collabs)
        matches = []
        for member in guild.members:
            if member.id == target_member.id:
                continue
            
            sessions = await self._get_member_sessions(member, guild)
            if not sessions:
                continue
            
            member_slots = set()
            for session in sessions:
                start = session.get("start")
                if not start:
                    continue
                dt = time.gmtime(start)
                day_of_week = (dt.tm_wday + 1) % 7
                hour = dt.tm_hour
                member_slots.add((day_of_week, hour))
            
            if not member_slots:
                continue
            
            # Calculate complementarity (lower overlap = better for collab)
            overlap = len(target_slots & member_slots)
            total_unique = len(target_slots | member_slots)
            
            if total_unique > 0:
                # Complementarity score: 0 = total overlap, 100 = no overlap
                complementarity = ((total_unique - overlap) / total_unique) * 100
                
                # Also consider activity level (prefer active streamers)
                activity_score = min(len(sessions) / 10.0, 1.0) * 100
                
                # Combined score
                combined_score = (complementarity * 0.7) + (activity_score * 0.3)
                
                matches.append({
                    "member_id": member.id,
                    "display_name": member.display_name,
                    "complementarity_score": round(complementarity, 1),
                    "activity_score": round(activity_score, 1),
                    "match_score": round(combined_score, 1),
                    "total_streams": len(sessions)
                })
        
        matches.sort(key=lambda x: x["match_score"], reverse=True)
        
        return web.json_response({
            "member_id": target_member.id,
            "display_name": target_member.display_name,
            "suggested_collaborators": matches[:10]  # Top 10
        })

    async def _proxy_handle_community_health(self, request: web.Request):
        """
        POST /dashboard/proxy/community_health
        Returns overall community health metrics.
        """
        payload = {}
        if request.content_length:
            try:
                payload = await request.json()
            except Exception:
                log.exception("Invalid JSON body for /dashboard/proxy/community_health")
                payload = {}

        # resolve guild
        guild = None
        if payload.get("guild_id"):
            try:
                guild = self.bot.get_guild(int(payload.get("guild_id")))
            except Exception:
                guild = None

        if guild is None:
            for g in self.bot.guilds:
                try:
                    fixed = await self.conf.guild(g).fixed_guild_id()
                except Exception:
                    fixed = None
                if fixed:
                    try:
                        if int(fixed) == g.id:
                            guild = g
                            break
                    except Exception:
                        guild = g
                        break

        if not guild:
            return web.Response(status=400, text="guild_id required or no fixed_guild_id configured")

        token = await self.conf.guild(guild).api_token()
        if not token:
            return web.Response(status=403, text="No API token configured for this guild")

        period = payload.get("period", "30d")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")

        # Collect community-wide metrics
        total_streamers = 0
        total_streams = 0
        total_time = 0
        active_members = []
        member_sessions_cache = {}  # Cache sessions to avoid re-fetching
        
        now = int(time.time())
        recent_cutoff = now - (7 * 86400)  # Last 7 days
        
        for member in guild.members:
            sessions = await self._get_member_sessions(member, guild)
            member_sessions_cache[member.id] = sessions  # Cache for later use
            
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            
            if not filtered:
                continue
            
            total_streamers += 1
            total_streams += len(filtered)
            member_time = sum(s.get("duration", 0) for s in filtered)
            total_time += member_time
            
            # Check if active in last 7 days
            recent_sessions = [s for s in sessions if s.get("start", 0) >= recent_cutoff]
            if recent_sessions:
                active_members.append(member.id)
        
        # Calculate metrics
        avg_streams_per_member = total_streams / total_streamers if total_streamers else 0
        avg_time_per_member = total_time / total_streamers if total_streamers else 0
        active_member_pct = (len(active_members) / total_streamers * 100) if total_streamers else 0
        
        # Calculate growth (compare with previous period) using cached sessions
        prev_streamers = 0
        prev_streams = 0
        
        if period.endswith("d"):
            days = int(period[:-1])
            prev_cutoff = cutoff - (days * 86400)
            
            # Use cached sessions from first loop
            for member_id, sessions in member_sessions_cache.items():
                prev_filtered = [s for s in sessions if prev_cutoff <= s.get("start", 0) < cutoff]
                
                if prev_filtered:
                    prev_streamers += 1
                    prev_streams += len(prev_filtered)
        
        streamer_growth = ((total_streamers - prev_streamers) / prev_streamers * 100) if prev_streamers else 0
        stream_growth = ((total_streams - prev_streams) / prev_streams * 100) if prev_streams else 0
        
        # Calculate health score (0-100)
        # Factors: active member %, avg streams, consistency
        activity_score = min(active_member_pct, 100) * 0.4
        volume_score = min(avg_streams_per_member / 10.0, 1.0) * 100 * 0.3
        growth_score = min(max(streamer_growth, 0) / 50.0, 1.0) * 100 * 0.3
        
        health_score = activity_score + volume_score + growth_score
        
        return web.json_response({
            "period": period,
            "total_streamers": total_streamers,
            "active_last_7_days": len(active_members),
            "active_percentage": round(active_member_pct, 1),
            "total_streams": total_streams,
            "total_hours": round(total_time / 3600, 1),
            "avg_streams_per_member": round(avg_streams_per_member, 1),
            "avg_hours_per_member": round(avg_time_per_member / 3600, 1),
            "streamer_growth_pct": round(streamer_growth, 1),
            "stream_growth_pct": round(stream_growth, 1),
            "health_score": round(health_score, 1),
            "health_grade": self._get_health_grade(health_score)
        })
    
    def _get_health_grade(self, score: float) -> str:
        """Convert health score to letter grade."""
        if score >= 90:
            return "A+"
        elif score >= 85:
            return "A"
        elif score >= 80:
            return "A-"
        elif score >= 75:
            return "B+"
        elif score >= 70:
            return "B"
        elif score >= 65:
            return "B-"
        elif score >= 60:
            return "C+"
        elif score >= 55:
            return "C"
        elif score >= 50:
            return "C-"
        elif score >= 45:
            return "D+"
        elif score >= 40:
            return "D"
        else:
            return "F"
