"""Module for the StreamRoles cog with streaming statistics support.

- Collect per-member streaming sessions (start, end, duration, game, url).
- Lightweight storage using Red's Config only (no external DB).
- Retention policy (per-guild) to limit stored history.
- Commands to view stats, export CSV and to show top N streamers by time or by count
  for last week, last month, or overall ("all").
- Keeps the Twitch-only and required-role behaviors added earlier.
- Purges old sessions on insert to remain light on server resources.

Notes:
- This implementation aims to be lightweight: it stores only session lists per member,
  prunes old sessions on insertion, and avoids background scanning. For very large
  servers with many streamers you may want a more robust external DB.
- The bot needs presence intents enabled to detect streaming activities.
"""
import asyncio
import contextlib
import csv
import io
import logging
import time
from typing import List, Optional, Tuple, Union

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils import chat_formatting as chatutils, menus, predicates

from .types import FilterList

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

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.conf = Config.get_conf(self, force_registration=True, identifier=UNIQUE_ID)
        # Guild config
        self.conf.register_guild(
            streamer_role=None,
            game_whitelist=[],
            mode=str(FilterList.blacklist),
            alerts__enabled=False,
            alerts__channel=None,
            alerts__autodelete=True,
            required_role=None,  # ID of role required to be eligible for streamrole
            stats__enabled=True,
            stats__retention_days=365,  # keep sessions for 1 year by default
        )
        # Member config
        # - current_stream_start: epoch seconds when we detected stream start (None if not streaming)
        # - stream_stats: list of session dicts {start,end,duration,game,platform,url}
        self.conf.register_member(
            blacklisted=False,
            whitelisted=False,
            alert_messages={},
            current_stream_start=None,
            stream_stats=[],
        )
        self.conf.register_role(blacklisted=False, whitelisted=False)

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
        """Set the user filter mode to blacklist or whitelist."""
        await self.conf.guild(ctx.guild).mode.set(str(mode))
        await self._update_guild(ctx.guild)
        await ctx.tick()

    @streamrole.group(autohelp=True)
    async def whitelist(self, ctx: commands.Context):
        """Manage the whitelist."""
        pass

    @whitelist.command(name="add")
    async def white_add(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        """Add a member or role to the whitelist."""
        await self._update_filter_list_entry(user_or_role, FilterList.whitelist, True)
        await ctx.tick()

    @whitelist.command(name="remove")
    async def white_remove(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        """Remove a member or role from the whitelist."""
        await self._update_filter_list_entry(user_or_role, FilterList.whitelist, False)
        await ctx.tick()

    @checks.bot_has_permissions(embed_links=True)
    @whitelist.command(name="show")
    async def white_show(self, ctx: commands.Context):
        """Show the whitelisted members and roles in this server."""
        members, roles = await self._get_filter_list(ctx.guild, FilterList.whitelist)
        if not (members or roles):
            await ctx.send("The whitelist is empty.")
            return
        embed = discord.Embed(
            title="StreamRoles Whitelist", colour=await ctx.embed_colour()
        )
        if members:
            embed.add_field(name="Members", value="\n".join(map(str, members)))
        if roles:
            embed.add_field(name="Roles", value="\n".join(map(str, roles)))
        await ctx.send(embed=embed)

    @streamrole.group(autohelp=True)
    async def blacklist(self, ctx: commands.Context):
        """Manage the blacklist."""
        pass

    @blacklist.command(name="add")
    async def black_add(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        """Add a member or role to the blacklist."""
        await self._update_filter_list_entry(user_or_role, FilterList.blacklist, True)
        await ctx.tick()

    @blacklist.command(name="remove")
    async def black_remove(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        """Remove a member or role from the blacklist."""
        await self._update_filter_list_entry(user_or_role, FilterList.blacklist, False)
        await ctx.tick()

    @checks.bot_has_permissions(embed_links=True)
    @blacklist.command(name="show")
    async def black_show(self, ctx: commands.Context):
        """Show the blacklisted members and roles in this server."""
        members, roles = await self._get_filter_list(ctx.guild, FilterList.blacklist)
        if not (members or roles):
            await ctx.send("The blacklist is empty.")
            return
        embed = discord.Embed(
            title="StreamRoles Blacklist", colour=await ctx.embed_colour()
        )
        if members:
            embed.add_field(name="Members", value="\n".join(map(str, members)))
        if roles:
            embed.add_field(name="Roles", value="\n".join(map(str, roles)))
        await ctx.send(embed=embed)

    @streamrole.group(autohelp=True)
    async def games(self, ctx: commands.Context):
        """Manage the game whitelist.

        Adding games to the whitelist will make the bot only add the streamrole
        to members streaming those games. If the game whitelist is empty, the
        game being streamed won't be checked before adding the streamrole.
        """
        pass

    @games.command(name="add")
    async def games_add(self, ctx: commands.Context, *, game: str):
        """Add a game to the game whitelist.

        This should *exactly* match the name of the game being played
        by the streamer as shown in Discord or on Twitch.
        """
        async with self.conf.guild(ctx.guild).game_whitelist() as whitelist:
            whitelist.append(game)
        await self._update_guild(ctx.guild)
        await ctx.tick()

    @games.command(name="remove")
    async def games_remove(self, ctx: commands.Context, *, game: str):
        """Remove a game from the game whitelist."""
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
        """Show the game whitelist for this server."""
        whitelist = await self.conf.guild(ctx.guild).game_whitelist()
        if not whitelist:
            await ctx.send("The game whitelist is empty.")
            return
        embed = discord.Embed(
            title="StreamRoles Game Whitelist",
            description="\n".join(whitelist),
            colour=await ctx.embed_colour(),
        )
        await ctx.send(embed=embed)

    @games.command(name="clear")
    async def games_clear(self, ctx: commands.Context):
        """Clear the game whitelist for this server."""
        msg = await ctx.send(
            "This will clear the game whitelist for this server. "
            "Are you sure you want to do this?"
        )
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
        """Enable or disable streamrole alerts."""
        await self.conf.guild(ctx.guild).alerts.enabled.set(true_or_false)
        await ctx.tick()

    @alerts.command(name="setchannel")
    async def alerts_setchannel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the channel for streamrole alerts."""
        await self.conf.guild(ctx.guild).alerts.channel.set(channel.id)
        await ctx.tick()

    @alerts.command(name="autodelete")
    async def alerts_autodelete(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable alert autodeletion.

        This is enabled by default. When enabled, alerts will be deleted
        once the streamer's role is removed.
        """
        await self.conf.guild(ctx.guild).alerts.autodelete.set(true_or_false)
        await ctx.tick()

    @streamrole.command()
    async def setrole(self, ctx: commands.Context, *, role: discord.Role):
        """Set the role which is given to streamers."""
        await self.conf.guild(ctx.guild).streamer_role.set(role.id)
        await ctx.send(
            "Done. Streamers will now be given the {} role when "
            "they go live.".format(role.name)
        )

    @streamrole.command()
    async def setrequiredrole(self, ctx: commands.Context, *, role: str):
        """Set a role required to be eligible for the streamrole.

        Pass a role mention, exact name, or ID to require it. Pass 'none' to disable the requirement.
        """
        if role.lower() == "none":
            await self.conf.guild(ctx.guild).required_role.set(None)
            await ctx.send("Disabled required role. Any eligible member can now receive the streamrole.")
            await self._update_guild(ctx.guild)
            return

        # Try to resolve a mention or ID first
        resolved = None
        if role.isdigit():
            resolved = ctx.guild.get_role(int(role))
        if resolved is None:
            # check mention format <@&id>
            if role.startswith("<@&") and role.endswith(">"):
                try:
                    rid = int(role[3:-1])
                    resolved = ctx.guild.get_role(rid)
                except ValueError:
                    resolved = None
        if resolved is None:
            # fallback to name match (case-sensitive exact), then case-insensitive
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
        """Set how many days to retain stream session stats (admin only)."""
        if days < 1:
            await ctx.send("Retention must be at least 1 day.")
            return
        await self.conf.guild(ctx.guild).stats.retention_days.set(days)
        await ctx.send(f"Stats retention set to {days} days.")
        await self._update_guild(ctx.guild)

    @streamrole.command()
    async def togglestats(self, ctx: commands.Context, enabled: bool):
        """Enable or disable collection of streaming stats for this guild."""
        await self.conf.guild(ctx.guild).stats.enabled.set(enabled)
        await ctx.send(f"Streaming stats collection {'enabled' if enabled else 'disabled'}.")
        await self._update_guild(ctx.guild)

    @streamrole.command()
    async def forceupdate(self, ctx: commands.Context):
        """Force the bot to reassign streamroles to members in this server.

        This command forces the bot to inspect the streaming status of
        all current members of the server, and assign (or remove) the
        streamrole.
        """
        if not await self.get_streamer_role(ctx.guild):
            await ctx.send(
                f"The streamrole has not been set in this server. Please use "
                f"`{ctx.clean_prefix}streamrole setrole` first."
            )
            return

        await self._update_guild(ctx.guild)
        await ctx.tick()

    # -----------------
    # Stats commands
    # -----------------
    @streamrole.group()
    async def stats(self, ctx: commands.Context):
        """Streaming statistics commands (stats, export, top)."""
        pass

    @stats.command(name="show")
    async def stats_show(
        self, ctx: commands.Context, member: Optional[discord.Member] = None, period: str = "30d"
    ):
        """
        Show stats for a member.

        period: "30d" for last 30 days, "7d" for last week, "30d" for 30 days, "all" for everything.
        """
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

        # average per week / per month over the period considered
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

        embed = discord.Embed(
            title=f"Streaming stats for {member.display_name}",
            description=f"Period: {period_label}\n",
            colour=await ctx.embed_colour(),
        )
        embed.add_field(name="Total streams", value=str(total_streams), inline=True)
        embed.add_field(
            name="Total time", value=self._format_seconds(total_time), inline=True
        )
        embed.add_field(
            name="Average duration", value=self._format_seconds(int(avg_duration)), inline=True
        )
        embed.add_field(name="Avg streams / week", value=f"{per_week:.2f}", inline=True)
        embed.add_field(name="Avg streams / month", value=f"{per_month:.2f}", inline=True)

        await ctx.send(embed=embed)

    @stats.command(name="export")
    async def stats_export(
        self, ctx: commands.Context, member: Optional[discord.Member] = None, period: str = "all"
    ):
        """
        Export sessions as CSV.

        member: mention or leave out for command caller.
        period: '7d', '30d', 'all'
        """
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

        # build CSV in-memory
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
    async def stats_top(
        self,
        ctx: commands.Context,
        metric: str = "time",
        period: str = "7d",
        limit: int = 10,
    ):
        """
        Show top N streamers in the guild.

        metric: "time" or "count" (by total time or number of streams)
        period: "7d", "30d", or "all"
        limit: how many entries to display (max 50)
        """
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

        # scan members, collect metric per member
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

        # sort descending
        results.sort(key=lambda x: x[1], reverse=True)
        top = results[:limit]

        if not top:
            await ctx.send("No data for the requested period.")
            return

        embed = discord.Embed(
            title=f"Top {len(top)} streamers by {'time' if metric=='time' else 'streams'} ({period})",
            colour=await ctx.embed_colour(),
        )
        for idx, (member, val) in enumerate(top, start=1):
            if metric == "time":
                value_str = self._format_seconds(val)
            else:
                value_str = str(val)
            embed.add_field(
                name=f"{idx}. {member.display_name}",
                value=value_str,
                inline=False,
            )

        await ctx.send(embed=embed)

    # -----------------
    # Core helpers
    # -----------------
    async def get_streamer_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Get the streamrole for this guild."""
        role_id = await self.conf.guild(guild).streamer_role()
        if not role_id:
            return
        try:
            role = next(r for r in guild.roles if r.id == role_id)
        except StopIteration:
            return
        else:
            return role

    async def get_alerts_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        """Get the alerts channel for this guild."""
        alerts_data = await self.conf.guild(guild).alerts.all()
        if not alerts_data["enabled"]:
            return
        return guild.get_channel(alerts_data["channel"])

    async def get_required_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Return the Role that is required for eligibility, or None."""
        role_id = await self.conf.guild(guild).required_role()
        if not role_id:
            return None
        return guild.get_role(role_id)

    # -----------------
    # Session storage helpers
    # -----------------
    async def _get_member_sessions(self, member: discord.Member, guild: discord.Guild) -> List[dict]:
        """Return the member's stream session list (sorted by start asc)."""
        data = await self.conf.member(member).stream_stats()
        # Ensure list type
        if not isinstance(data, list):
            return []
        # Remove any malformed items
        sessions = [s for s in data if isinstance(s, dict) and "start" in s]
        sessions.sort(key=lambda s: s.get("start", 0))
        return sessions

    async def _add_session_for_member(
        self, member: discord.Member, session: dict, guild: discord.Guild
    ):
        """Append a session and apply retention prune."""
        if not await self.conf.guild(guild).stats.enabled():
            return
        retention_days = await self.conf.guild(guild).stats.retention_days()
        cutoff = _epoch_now() - _days_to_seconds(retention_days)
        async with self.conf.member(member).stream_stats() as lst:
            lst.append(session)
            # prune old sessions (in-place)
            # keep only sessions with start >= cutoff
            pruned = [s for s in lst if s.get("start", 0) >= cutoff]
            # replace list content
            lst.clear()
            lst.extend(pruned)
        log.debug("Added session for %s: start=%s dur=%s", member.id, session.get("start"), session.get("duration"))

    # -----------------
    # Presence / session detection and main logic
    # -----------------
    async def _update_member(
        self,
        member: discord.Member,
        role: Optional[discord.Role] = None,
        alerts_channel: Optional[discord.TextChannel] = _alerts_channel_sentinel,
    ) -> None:
        role = role or await self.get_streamer_role(member.guild)
        if role is None:
            return

        channel = (
            alerts_channel
            if alerts_channel is not _alerts_channel_sentinel
            else await self.get_alerts_channel(member.guild)
        )

        # If a required role is configured, check it here.
        required = await self.get_required_role(member.guild)
        if required is not None and required not in member.roles:
            # member doesn't have required role -> remove streamrole if present and stop tracking
            if role in member.roles:
                log.debug(
                    "Removing streamrole %s from member %s because they lack required role %s",
                    role.id,
                    member.id,
                    required.id,
                )
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            # also, if there's an ongoing streaming "current_stream_start", close it
            current_start = await self.conf.member(member).current_stream_start()
            if current_start:
                # close session without recording (since requirement not met)
                await self.conf.member(member).current_stream_start.set(None)
            return

        # find the first Streaming activity
        activity = next(
            (a for a in member.activities if isinstance(a, discord.Streaming)),
            None,
        )

        # if no activity or no platform -> treat as not streaming
        if activity is None or not activity.platform:
            # if we had a current_stream_start, finalize session
            await self._finalize_current_session_if_any(member, activity, channel)
            # remove role if present (standard behavior)
            if role in member.roles:
                log.debug("Removing streamrole %s from member %s", role.id, member.id)
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            return

        # ensure platform/url indicate Twitch only
        platform = str(activity.platform or "").lower()
        url = str(activity.url or "").lower()
        if "twitch" not in platform and "twitch.tv" not in url:
            # not a Twitch stream -> finalize any open session and remove role
            await self._finalize_current_session_if_any(member, activity, channel)
            if role in member.roles:
                log.debug(
                    "Removing streamrole %s from member %s because stream is not Twitch",
                    role.id,
                    member.id,
                )
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            return

        # At this point: activity is a Twitch stream
        # If stats disabled for guild, we still keep role/alerts logic but won't record sessions.
        was_streaming = bool(await self.conf.member(member).current_stream_start())
        # If not streaming before, start tracking now
        if not was_streaming:
            # record start
            now = _epoch_now()
            await self.conf.member(member).current_stream_start.set(now)
            # optionally also keep metadata for later finalization if desired (game/url/platform)
            # We won't store metadata in a separate key; we'll keep it in the finalized session.
            log.debug("Detected Twitch stream start for %s at %s", member.id, now)
        # add role and post alert if necessary
        if role not in member.roles:
            log.debug("Adding streamrole %s to member %s", role.id, member.id)
            await member.add_roles(role)
            if channel:
                await self._post_alert(member, activity, activity.game, channel)
        # done; do not finalize here

    async def _finalize_current_session_if_any(self, member: discord.Member, activity, channel):
        """If member has current_stream_start, finalize it and store session."""
        start = await self.conf.member(member).current_stream_start()
        if not start:
            return
        end = _epoch_now()
        duration = max(0, end - start)
        # fetch last known activity info if available from 'activity' param; fallback to None
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
        # store session (with retention prune)
        await self._add_session_for_member(member, session, member.guild)
        # clear current_stream_start
        await self.conf.member(member).current_stream_start.set(None)
        log.debug("Finalized session for %s: %s seconds", member.id, duration)
        # remove alert message if needed
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
                    log.debug(
                        "Removing streamrole %s from member %s after role %s was "
                        "blacklisted",
                        streamer_role.id,
                        member.id,
                        role.id,
                    )
                    await member.remove_roles(
                        streamer_role,
                        reason=f"Removing streamrole after {role} role was blacklisted",
                    )
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
    async def _post_alert(
        self,
        member: discord.Member,
        activity: discord.Streaming,
        game: Optional[str],
        channel: discord.TextChannel,
    ) -> discord.Message:
        content = (
            f"{chatutils.bold(member.display_name)} is now live on {activity.platform}"
        )
        if game is not None:
            content += f", playing {chatutils.italics(str(game))}"
        content += (
            f"!\n\nTitle: {chatutils.italics(activity.name)}\nURL: {activity.url}"
        )

        msg = await channel.send(content)
        await self.conf.member(member).alert_messages.set_raw(
            str(channel.id), value=msg.id
        )
        return msg

    async def _remove_alert(
        self, member: discord.Member, channel: discord.TextChannel
    ) -> None:
        conf_group = self.conf.member(member).alert_messages
        msg_id = await conf_group.get_raw(str(channel.id), default=None)
        if msg_id is None:
            return
        await conf_group.clear_raw(str(channel.id))

        msg: Optional[discord.Message] = discord.utils.get(
            getattr(self.bot, "cached_messages", ()), id=msg_id
        )
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
        """Update any members when the bot joins a new guild."""
        await self._update_guild(guild)

    @commands.Cog.listener()
    async def on_presence_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Apply or remove the streamrole when a user's activity changes."""
        if before.activities != after.activities:
            await self._update_member(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Update a new member who joins."""
        await self._update_member(member)

    # -----------------
    # Filter helpers (same as original)
    # -----------------
    async def _get_filter_list(
        self, guild: discord.Guild, mode: FilterList
    ) -> Tuple[List[discord.Member], List[discord.Role]]:
        all_member_data = await self.conf.all_members(guild)
        all_role_data = await self.conf.all_roles()
        mode = mode.as_participle()
        member_ids = (u for u, d in all_member_data.items() if d.get(mode))
        role_ids = (u for u, d in all_role_data.items() if d.get(mode))
        members = list(filter(None, map(guild.get_member, member_ids)))
        roles = list(filter(None, map(guild.get_role, role_ids)))
        return members, roles

    async def _update_filter_list_entry(
        self,
        member_or_role: Union[discord.Member, discord.Role],
        filter_list: FilterList,
        value: bool,
    ) -> None:
        if isinstance(member_or_role, discord.Member):
            await self.conf.member(member_or_role).set_raw(
                filter_list.as_participle(), value=value
            )
            await self._update_member(member_or_role)
        else:
            await self.conf.role(member_or_role).set_raw(
                filter_list.as_participle(), value=value
            )
            await self._update_members_with_role(member_or_role)

    # -----------------
    # Utils
    # -----------------
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