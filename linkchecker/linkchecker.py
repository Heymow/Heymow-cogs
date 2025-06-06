import re
import time
import discord
from redbot.core import commands, Config

ONE_WEEK_SECONDS = 604800  # Number of seconds in one week

# Set of allowed channel IDs (replace with your channel IDs)
ALLOWED_CHANNEL_IDS = {1306660377211310091, 1322627330929070212}

def normalize_link(link: str) -> str:
    """
    Normalize a link from suno.com/song/ or suno.com/s/ by removing the prefix and
    discarding any query parameters starting with '?sh'.
    For other links, simply return the lowercased and stripped version.
    """
    song_prefix = "https://suno.com/song/"
    s_prefix = "https://suno.com/s/"
    
    if link.startswith(song_prefix):
        # Remove the prefix from the link
        song_id = link[len(song_prefix):]
        # Remove query parameters if they exist (anything starting with '?sh')
        if "?sh" in song_id:
            song_id = song_id.split("?sh", 1)[0]
        return song_id.lower().strip()
    elif link.startswith(s_prefix):
        # Remove the prefix from the link
        song_id = link[len(s_prefix):]
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
    
    Ce cog ne s'exécute que dans les salons spécifiés dans ALLOWED_CHANNEL_IDS.
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

        # Process only if the message is in one of the allowed channels
        if message.channel.id not in ALLOWED_CHANNEL_IDS:
            return

        # Extract suno links using the improved regex pattern
        pattern = r"https://suno\.com/(?:song/([a-f0-9\-]+)|s/([a-zA-Z0-9]+))"
        suno_matches = re.findall(pattern, message.content)
        
        # Convert matches to actual links
        suno_links = []
        for match in suno_matches:
            if match[0]:  # song/ format
                suno_links.append(f"https://suno.com/song/{match[0]}")
            elif match[1]:  # s/ format
                suno_links.append(f"https://suno.com/s/{match[1]}")

        # Extract all links from the message using regex
        all_links = re.findall(r'https?://\S+', message.content)

        # Check that exactly one suno link is present
        if len(suno_links) != 1:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                f"{message.author.mention}, please post exactly one valid suno track link per message."
            )
            return

        # Ensure no additional links are present
        if len(all_links) > 1:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                f"{message.author.mention}, please post only one link, and it must be a valid suno track link."
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
        if len(cleaned_links) != len(posted_links):
            await self.config.guild(message.guild).posted_links.set(cleaned_links)
        posted_links = cleaned_links

        # Check if the normalized link already exists in the posted links history
        duplicate_found = any(
            normalized_link == entry.get("link") for entry in posted_links
        )
        
        if duplicate_found:
            try:
                await message.delete()
            except discord.Forbidden:
                pass

            self.processed_messages.add(message.id)

            duplicate_counts = await self.config.guild(message.guild).duplicate_counts()
            user_id = str(message.author.id)
            count = duplicate_counts.get(user_id, 0) + 1
            duplicate_counts[user_id] = count
            await self.config.guild(message.guild).duplicate_counts.set(duplicate_counts)

            warning = f"{message.author.mention}, your link is a duplicate. Please refrain from posting duplicate links."
            await message.channel.send(warning)
            if count >= 3:
                extra_warning = (
                    f"{message.author.mention}, this is your third duplicate link. "
                    "Please stop posting duplicate links, or you may face further consequences."
                )
                await message.channel.send(extra_warning)

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

        # If no duplicate is found, add the new normalized link with the current timestamp
        posted_links.append({
            "link": normalized_link,
            "timestamp": current_time
        })
        await self.config.guild(message.guild).posted_links.set(posted_links)

async def setup(bot: commands.Bot):
    await bot.add_cog(LinkChecker(bot))
