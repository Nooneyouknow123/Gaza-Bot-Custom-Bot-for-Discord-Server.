import discord
from discord.ext import commands

BOOST_CHANNEL_ID = 1388646310206373989 # channel id

class BoosterThanker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Detect boost event
        if before.premium_since is None and after.premium_since is not None:
            channel = after.guild.get_channel(BOOST_CHANNEL_ID)
            if channel is None:
                return

            embed = discord.Embed(
                title="🌙 **A Blessed Boost!**",
                description=(
                    f"Alhamdulillah! 🤍\n\n"
                    f"**{after.mention}** has just supported our community by boosting this server! ✨\n\n"
                    f"Your contribution strengthens this home for everyone — may it bring happiness and unity to our members. 🤲🏼\n\n"
                    f"**JazakAllah khair!** 🌸"
                ),
                color=discord.Color.purple()
            )

            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text="May Allah reward your generosity 💫")

            await channel.send(content=f"{after.mention}", embed=embed)

async def setup(bot):
    await bot.add_cog(BoosterThanker(bot))


