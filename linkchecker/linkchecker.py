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
    This cog checks that posted links are not duplicates.
    
    When a duplicate is found:
      - The message is deleted.
      - A warning message is sent in English to notify the user.
      - If the user posts a duplicate 3 times, an additional warning is sent.
      - A notification is sent to admins in a specific channel.
      
    Additionally, each new link cleans the history by removing links older than one week.
    
    Ce cog vérifie que les liens postés ne sont pas des doublons.
    En cas de doublon, le message est supprimé, un avertissement est envoyé à l'utilisateur,
    et une notification est envoyée aux admins. De plus, l'historique est nettoyé des liens
    postés il y a plus d'une semaine.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Initialize the configuration for the cog with a unique identifier
        self.config = Config.get_conf(self, identifier=1234567890123)
        default_guild = {
            "posted_links": [],      # List of dictionaries: {"link": <normalized_link>, "timestamp": <time>}
            "duplicate_counts": {}   # Dictionary to count duplicates per user: {user_id: count}
        }
        self.config.register_guild(**default_guild)
        # Set to store message IDs that have been processed as duplicates
        self.processed_messages = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages from bots or messages outside a guild (e.g., DMs)
        if message.author.bot or message.guild is None:
            return

        # Extract all links from the message using regex
        links = re.findall(r'https?://\S+', message.content)
        if not links:
            return

        # Normalize links: for suno.com/song/ links, extract only the song ID
        normalized_links = [normalize_link(link) for link in links]

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

        # Check if any normalized link already exists in the posted links history
        duplicate_found = any(
            any(link == entry.get("link") for entry in posted_links)
            for link in normalized_links
        )
        
        if duplicate_found:
            # Attempt to delete the message (requires Manage Messages permission)
            try:
                await message.delete()
            except discord.Forbidden:
                pass

            # Mark the message as processed to prevent it from being handled by another cog
            self.processed_messages.add(message.id)

            # Increment the duplicate count for this user
            duplicate_counts = await self.config.guild(message.guild).duplicate_counts()
            user_id = str(message.author.id)
            count = duplicate_counts.get(user_id, 0) + 1
            duplicate_counts[user_id] = count
            await self.config.guild(message.guild).duplicate_counts.set(duplicate_counts)

            # Send a warning message in English in the channel
            warning = f"{message.author.mention}, your link is a duplicate. Please refrain from posting duplicate links."
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

        # If no duplicate is found, add each new normalized link with the current timestamp
        for link in normalized_links:
            posted_links.append({
                "link": link,
                "timestamp": current_time
            })
        await self.config.guild(message.guild).posted_links.set(posted_links)

async def setup(bot: commands.Bot):
    await bot.add_cog(LinkChecker(bot))
