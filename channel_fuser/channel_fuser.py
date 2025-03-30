import re
import time
import discord
import aiohttp
from redbot.core import commands, Config

class ChannelFusion(commands.Cog):
    """Copy messages from one or more channels into a target channel using webhooks."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fusechannels")
    @commands.admin()
    async def fuse_channels(self, ctx, target: discord.TextChannel, *sources: discord.TextChannel):
        """Fuse multiple channels into a target channel (with webhooks)."""
        if not sources:
            await ctx.send("Please specify at least one source channel.")
            return

        await ctx.send(f"Starting fusion from {len(sources)} channels into {target.mention}...")

        webhook = await self._get_or_create_webhook(target)

        for source in sources:
            await ctx.send(f"Copying messages from {source.mention}...")
            messages = [msg async for msg in source.history(limit=None, oldest_first=True)]

            for msg in messages:
                if msg.type != discord.MessageType.default:
                    continue  # Skip non-standard messages like pins, joins, etc.

                if msg.content.strip() == "" and not msg.attachments:
                    continue  # Skip empty messages

                if msg.author.bot:
                    continue  # Optional: skip bot messages

                content = msg.content
                files = []
                try:
                    for attachment in msg.attachments:
                        file = await attachment.to_file()
                        files.append(file)

                    kwargs = {
                        "content": content,
                        "username": msg.author.display_name,
                        "avatar_url": msg.author.display_avatar.url,
                        "allowed_mentions": discord.AllowedMentions.none(),
                    }

                    if files:
                        kwargs["files"] = files

                    await webhook.send(**kwargs)

                except Exception as e:
                    await ctx.send(f"Error sending a message from {msg.author.display_name}: {e}")

        await ctx.send("✅ Channel fusion complete!")

    async def _get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.user == self.bot.user:
                return wh
        return await channel.create_webhook(name="ChannelFusionWebhook")

async def setup(bot):
    await bot.add_cog(ChannelFusion(bot))
