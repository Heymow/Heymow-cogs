import re
import time
import discord
from redbot.core import commands, Config

ONE_WEEK_SECONDS = 604800  # Number of seconds in one week

def normalize_link(link: str) -> str:
    """
    Normalize a link from suno.com/song/ by removing the prefix and
    discarding any query parameters starting with '?sh'.
    For other links, simply return the lowercased and stripped version.
    """
    prefix = "https://suno.com/song/"
    if link.startswith(prefix):
        # Remove the prefix from the link
        song_id = link[len(prefix):]
        # Remove query parameters if they exist (anything starting with '?sh')
        if "?sh" in song_id:
            song_id = song_id.split("?sh", 1)[0]
        return song_id.lower().strip()
    return link.strip().lower()

class LinkChecker(commands.Cog):
    """
    This cog checks that posted links are not duplicates and ensures that each message
    contains exactly one valid suno track link.
    
    When a duplicate or an invalid message is found:
      - The message is deleted.
      - An explanatory warning message is sent in English.
      
    Additionally, each new link cleans the history by removing links older than one week.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123)
        default_guild = {
            "posted_links": [],      # List of dictionaries: {"link": <normalized_link>, "timestamp": <time>}
            "duplicate_counts": {}   # Dictionary to count duplicates per user: {user_id: count}
        }
        self.config.register_guild(**default_guild)
        self.processed_messages = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages from bots or messages outside a guild
        if message.author.bot or message.guild is None:
            return

        # Extract all links from the message using regex
        all_links = re.findall(r'https?://\S+', message.content)
        # Filter only suno track links
        suno_links = [link for link in all_links if link.startswith("https://suno.com/song/")]

        # Check that exactly one suno link is present
        if len(suno_links) != 1:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                f"{message.author.mention}, please post exactly one valid Suno song link per message."
            )
            return

        # Ensure no additional links are present
        if len(all_links) > 1:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                f"{message.author.mention}, please post only one link, and it must be a valid Suno song link."
            )
            return

        # At this point, we have exactly one suno link.
        normalized_link = normalize_link(suno_links[0])

        # Retrieve the list of posted links for this guild from configuration
        posted_links = await self.config.guild(message.guild).posted_links()
        current_time = time.time()

        # Clean the history: keep only links that are less than or equal to one week old
        cleaned_links = [
            entry for entry in posted_links
            if current_time - entry.get("timestamp", 0) <= ONE_WEEK_SECONDS
        ]
        # Update configuration if any old links were removed
        if len(cleaned_links) != len(posted_links):
            await self.config.guild(message.guild).posted_links.set(cleaned_links)
        posted_links = cleaned_links

        # Check if the normalized link is already in the posted links history
        duplicate_found = any(
            normalized_link == entry.get("link") for entry in posted_links
        )
        
        if duplicate_found:
            try:
                await message.delete()
            except discord.Forbidden:
                pass

            # Mark the message as processed
            self.processed_messages.add(message.id)

            # Increment the duplicate count for this user
            duplicate_counts = await self.config.guild(message.guild).duplicate_counts()
            user_id = str(message.author.id)
            count = duplicate_counts.get(user_id, 0) + 1
            duplicate_counts[user_id] = count
            await self.config.guild(message.guild).duplicate_counts.set(duplicate_counts)

            # Send a warning message in English in the channel
            warning = f"{message.author.mention}, your song has already been posted. Please refrain from posting duplicate links."
            await message.channel.send(warning)
            if count >= 3:
                extra_warning = (
                    f"{message.author.mention}, this is your third duplicate link. "
                    "Please stop posting duplicate links, or you may face further consequences."
                )
                await message.channel.send(extra_warning)

            # Send a notification to the admins in the specified channel
            admin_channel = self.bot.get_channel(1326495268862169122)
            if admin_channel:
                admin_message = (
                    f"Admin Alert: User {message.author} (ID: {message.author.id}) posted a duplicate link in "
                    f"{message.guild.name} (ID: {message.guild.id}), channel {message.channel.mention}. "
                    f"Total duplicate count: {count}."
                )
                try:
                    await admin_channel.send(admin_message)
                except discord.Forbidden:
                    pass
            return

        # If no duplicate is found, add the new normalized link with current timestamp
        posted_links.append({
            "link": normalized_link,
            "timestamp": current_time
        })
        await self.config.guild(message.guild).posted_links.set(posted_links)

async def setup(bot: commands.Bot):
    await bot.add_cog(LinkChecker(bot))
