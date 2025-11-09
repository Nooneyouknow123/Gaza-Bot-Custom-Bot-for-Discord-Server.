import discord
from discord.ext import commands
import datetime

class PingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        """Check bot latency and responsiveness"""
        try:
            latency = round(self.bot.latency * 1000)
            embed = discord.Embed(
                title="System Status",
                description=f"Bot operational and responsive.\n**Latency:** {latency}ms",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            
            msg = await ctx.send(embed=embed)
            await msg.delete(delay=20)
            
        except Exception as e:
            await ctx.send("Error processing command")
            print(f"Ping command error: {e}")

async def setup(bot):
    await bot.add_cog(PingCog(bot))