"""Module for the StreamRoles cog."""
import asyncio
import contextlib
import logging
from typing import List, Optional, Tuple, Union

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils import chat_formatting as chatutils, menus, predicates

from .types import FilterList

log = logging.getLogger("red.streamroles")

UNIQUE_ID = 0x923476AF

_alerts_channel_sentinel = object()


class StreamRoles(commands.Cog):
    """Give current twitch streamers in your server a role."""

    # Set using [p]eval or something rather and the streamrole will be assigned simply
    # whenever someone is streaming, regardless of whether or not they have a linked
    # Twitch account. Makes for easier black-box testing.
    DEBUG_MODE = False

    def __init__(self, bot: Red):
        super().__init__()
        self.bot: Red = bot
        self.conf = Config.get_conf(self, force_registration=True, identifier=UNIQUE_ID)
        self.conf.register_guild(
            streamer_role=None,
            game_whitelist=[],
            mode=str(FilterList.blacklist),
            alerts__enabled=False,
            alerts__channel=None,
            alerts__autodelete=True,
            required_role=None,  # ID of role required to be eligible for streamrole
        )
        self.conf.register_member(
            blacklisted=False, whitelisted=False, alert_messages={}
        )
        self.conf.register_role(blacklisted=False, whitelisted=False)

    async def initialize(self) -> None:
        """Initialize the cog."""
        for guild in self.bot.guilds:
            await self._update_guild(guild)

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

    async def get_streamer_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Get the streamrole for this guild.

        Arguments
        ---------
        guild : discord.Guild
            The guild to retrieve the streamer role for.

        Returns
        -------
        Optional[discord.Role]
            The role given to streaming users in this guild. ``None``
            if not set.
        """
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
        """Get the alerts channel for this guild.

        Arguments
        ---------
        guild : discord.Guild
            The guild to retrieve the alerts channel for.

        Returns
        -------
        Optional[discord.TextChannel]
            The channel where alerts are posted in this guild. ``None``
            if not set or enabled.
        """
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

        # If a required role is configured, check it here. If the member doesn't have it,
        # ensure the streamrole is removed (if present) and do nothing else.
        required = await self.get_required_role(member.guild)
        if required is not None and required not in member.roles:
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
            return

        # find the first Streaming activity
        activity = next(
            (a for a in member.activities if isinstance(a, discord.Streaming)),
            None,
        )
        if activity is None:
            has_role = role in member.roles
            if has_role:
                log.debug("Removing streamrole %s from member %s", role.id, member.id)
                await member.remove_roles(role)
                if channel and await self.conf.guild(member.guild).alerts.autodelete():
                    await self._remove_alert(member, channel)
            return

        # ensure platform/url indicate Twitch only
        platform = str(activity.platform or "").lower()
        url = str(activity.url or "").lower()
        if "twitch" not in platform and "twitch.tv" not in url:
            # not a Twitch stream -> remove role if present and do nothing
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

        # final checks: filter lists and game whitelist
        has_role = role in member.roles
        if await self._is_allowed(member):
            game = activity.game
            games = await self.conf.guild(member.guild).game_whitelist()
            if not games or game in games:
                if not has_role:
                    log.debug("Adding streamrole %s to member %s", role.id, member.id)
                    await member.add_roles(role)
                    if channel:
                        await self._post_alert(member, activity, game, channel)
                return

        # if we reach here, they shouldn't have the role
        if has_role:
            log.debug("Removing streamrole %s from member %s", role.id, member.id)
            await member.remove_roles(role)
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

    async def _is_allowed(self, member: discord.Member) -> bool:
        if await self.conf.guild(member.guild).mode() == FilterList.blacklist:
            return not await self._is_blacklisted(member)
        else:
            return await self._is_whitelisted(member)

    async def _is_whitelisted(self, member: discord.Member) -> bool:
        if await self.conf.member(member).whitelisted():
            return True
        for role in member.roles:
            if await self.conf.role(role).whitelisted():
                return True
        return False

    async def _is_blacklisted(self, member: discord.Member) -> bool:
        if await self.conf.member(member).blacklisted():
            return True
        for role in member.roles:
            if await self.conf.role(role).blacklisted():
                return True
        return False