import discord

from discord.ext import commands

import time

from datetime import timedelta

import platform

import psutil

class Utility(commands.Cog):

    """

    Utility cog with avatar, serverinfo, members, roles, and botinfo commands.

    """

    

    def __init__(self, bot):

        self.bot = bot

        self.start_time = time.time()

    @commands.command(name='avatar', aliases=['av', 'pfp'])

    async def avatar(self, ctx, member: discord.Member = None):

        """Get a user's avatar."""

        if member is None:

            member = ctx.author

        

        embed = discord.Embed(

            title=f"{member.display_name}'s Avatar",

            color=member.color

        )

        embed.set_image(url=member.display_avatar.url)

        embed.add_field(name="Download", value=f"[Click Here]({member.display_avatar.url})")

        

        await ctx.send(embed=embed)

    @commands.command(name='serverinfo', aliases=['si', 'guildinfo'])

    async def server_info(self, ctx):

        """Get information about the server."""

        guild = ctx.guild

        

        embed = discord.Embed(

            title=f"Server Info - {guild.name}",

            color=discord.Color.blue()

        )

        

        if guild.icon:

            embed.set_thumbnail(url=guild.icon.url)

        

        # Basic info

        embed.add_field(name="Server Name", value=guild.name, inline=True)

        embed.add_field(name="Server ID", value=guild.id, inline=True)

        embed.add_field(name="Owner", value=guild.owner.mention, inline=True)

        

        # Member stats

        total_members = guild.member_count

        bots = len([m for m in guild.members if m.bot])

        humans = total_members - bots

        

        embed.add_field(name="Total Members", value=total_members, inline=True)

        embed.add_field(name="Humans", value=humans, inline=True)

        embed.add_field(name="Bots", value=bots, inline=True)

        

        # Channel stats

        text_channels = len(guild.text_channels)

        voice_channels = len(guild.voice_channels)

        categories = len(guild.categories)

        

        embed.add_field(name="Text Channels", value=text_channels, inline=True)

        embed.add_field(name="Voice Channels", value=voice_channels, inline=True)

        embed.add_field(name="Categories", value=categories, inline=True)

        

        # Other info

        embed.add_field(name="Roles", value=len(guild.roles), inline=True)

        embed.add_field(name="Emojis", value=len(guild.emojis), inline=True)

        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)

        embed.add_field(name="Boost Count", value=guild.premium_subscription_count, inline=True)

        embed.add_field(name="Created", value=guild.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)

        

        await ctx.send(embed=embed)

    @commands.command(name='members')

    async def member_count(self, ctx):

        """Show detailed member count."""

        guild = ctx.guild

        total = guild.member_count

        humans = len([m for m in guild.members if not m.bot])

        bots = len([m for m in guild.members if m.bot])

        

        embed = discord.Embed(

            title=f"Member Count - {guild.name}",

            color=discord.Color.green()

        )

        embed.add_field(name="Total Members", value=total, inline=True)

        embed.add_field(name="Humans", value=humans, inline=True)

        embed.add_field(name="Bots", value=bots, inline=True)

        

        # Online status breakdown

        online = len([m for m in guild.members if m.status == discord.Status.online])

        idle = len([m for m in guild.members if m.status == discord.Status.idle])

        dnd = len([m for m in guild.members if m.status == discord.Status.dnd])

        offline = len([m for m in guild.members if m.status == discord.Status.offline])

        

        embed.add_field(name="🟢 Online", value=online, inline=True)

        embed.add_field(name="🟡 Idle", value=idle, inline=True)

        embed.add_field(name="🔴 DND", value=dnd, inline=True)

        embed.add_field(name="⚫ Offline", value=offline, inline=True)

        

        await ctx.send(embed=embed)

    @commands.command(name='roles')

    async def server_roles(self, ctx):

        """List all roles in the server."""

        guild = ctx.guild

        roles = sorted(guild.roles[1:], key=lambda x: x.position, reverse=True)  # Exclude @everyone

        

        if not roles:

            await ctx.send("No roles found in this server.")

            return

        

        role_list = []

        for role in roles:

            role_info = f"{role.mention} - {len(role.members)} members"

            role_list.append(role_info)

        

        # Split into chunks if too long

        chunks = []

        current_chunk = ""

        

        for role in role_list:

            if len(current_chunk) + len(role) < 2000:

                current_chunk += role + "\n"

            else:

                chunks.append(current_chunk)

                current_chunk = role + "\n"

        

        if current_chunk:

            chunks.append(current_chunk)

        

        for i, chunk in enumerate(chunks):

            embed = discord.Embed(

                title=f"Roles in {guild.name} ({len(roles)} total)" if i == 0 else f"Roles (Continued)",

                description=chunk,

                color=discord.Color.blue()

            )

            await ctx.send(embed=embed)

    @commands.command(name='botinfo', aliases=['bi', 'stats'])

    async def bot_info(self, ctx):

        """Get information about the bot."""

        # Calculate uptime

        uptime_seconds = int(time.time() - self.start_time)

        uptime_string = str(timedelta(seconds=uptime_seconds))

        

        # Calculate memory usage

        process = psutil.Process()

        memory_usage = process.memory_info().rss / 1024 ** 2  # Convert to MB

        

        embed = discord.Embed(

            title="Bot Information",

            color=discord.Color.blue()

        )

        

        if self.bot.user.avatar:

            embed.set_thumbnail(url=self.bot.user.avatar.url)

        

        # Bot info

        embed.add_field(name="Bot Name", value=self.bot.user.name, inline=True)

        embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)

        embed.add_field(name="Discord.py Version", value=discord.__version__, inline=True)

        

        # System info

        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)

        embed.add_field(name="Server OS", value=platform.system(), inline=True)

        embed.add_field(name="Memory Usage", value=f"{memory_usage:.2f} MB", inline=True)

        

        # Bot stats

        embed.add_field(name="Uptime", value=uptime_string, inline=True)

        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)

        embed.add_field(name="Latency", value=f"{self.bot.latency * 1000:.2f} ms", inline=True)

        

        await ctx.send(embed=embed)

    # Error handling

    @avatar.error

    async def avatar_error(self, ctx, error):

        if isinstance(error, commands.BadArgument):

            await ctx.send("❌ User not found. Please mention a valid user.")

async def setup(bot):

    """Setup function for loading the cog."""

    await bot.add_cog(Utility(bot))