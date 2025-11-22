import discord

from discord.ext import commands

import time

from datetime import datetime, timezone

class Snipe(commands.Cog):

    """

    Snipe cog with snipe and editsnipe commands.

    """

    

    def __init__(self, bot):

        self.bot = bot

        self.deleted_messages = {}

        self.edited_messages = {}

    @commands.Cog.listener()

    async def on_message_delete(self, message):

        """Store deleted messages for snipe command."""

        if message.author.bot:

            return

        

        # Store message data

        self.deleted_messages[message.channel.id] = {

            'content': message.content,

            'author': message.author,

            'timestamp': time.time(),

            'attachments': [att.url for att in message.attachments] if message.attachments else []

        }

    @commands.Cog.listener()

    async def on_message_edit(self, before, after):

        """Store edited messages for editsnipe command."""

        if before.author.bot or before.content == after.content:

            return

        

        self.edited_messages[before.channel.id] = {

            'before': before.content,

            'after': after.content,

            'author': before.author,

            'timestamp': time.time()

        }

    @commands.command(name='snipe')

    async def snipe(self, ctx, channel: discord.TextChannel = None):

        """Show the most recently deleted message in this channel."""

        if channel is None:

            channel = ctx.channel

        

        message_data = self.deleted_messages.get(channel.id)

        

        if not message_data:

            await ctx.send("❌ No recently deleted messages found in this channel.")

            return

        

        embed = discord.Embed(

            title="💬 Sniped Message",

            description=message_data['content'] or "*No text content*",

            color=discord.Color.red(),

            timestamp=datetime.fromtimestamp(message_data['timestamp'], tz=timezone.utc)

        )

        

        embed.set_author(

            name=f"Message by {message_data['author'].display_name}",

            icon_url=message_data['author'].display_avatar.url

        )

        

        # Add attachments info if any

        if message_data['attachments']:

            embed.add_field(

                name="Attachments",

                value=f"{len(message_data['attachments'])} attachment(s)",

                inline=True

            )

        

        embed.set_footer(text=f"Deleted in #{channel.name}")

        

        await ctx.send(embed=embed)

    @commands.command(name='editsnipe')

    async def editsnipe(self, ctx, channel: discord.TextChannel = None):

        """Show the most recently edited message in this channel."""

        if channel is None:

            channel = ctx.channel

        

        message_data = self.edited_messages.get(channel.id)

        

        if not message_data:

            await ctx.send("❌ No recently edited messages found in this channel.")

            return

        

        embed = discord.Embed(

            title="✏️ Edited Message",

            color=discord.Color.orange(),

            timestamp=datetime.fromtimestamp(message_data['timestamp'], tz=timezone.utc)

        )

        

        embed.set_author(

            name=f"Message by {message_data['author'].display_name}",

            icon_url=message_data['author'].display_avatar.url

        )

        

        # Truncate long messages

        before_content = message_data['before']

        after_content = message_data['after']

        

        if len(before_content) > 500:

            before_content = before_content[:500] + "..."

        if len(after_content) > 500:

            after_content = after_content[:500] + "..."

        

        embed.add_field(name="Before", value=before_content or "*No content*", inline=False)

        embed.add_field(name="After", value=after_content or "*No content*", inline=False)

        

        embed.set_footer(text=f"Edited in #{channel.name}")

        

        await ctx.send(embed=embed)

async def setup(bot):

    """Setup function for loading the cog."""

    await bot.add_cog(Snipe(bot))