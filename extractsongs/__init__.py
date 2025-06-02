from .extractsongs import Extractsongs

async def setup(bot):
    await bot.add_cog(Extractsongs(bot))
