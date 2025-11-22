import discord

from discord.ext import commands

class Purge(commands.Cog):

    """

    Purge cog for bulk message deletion.

    """

    

    def __init__(self, bot):

        self.bot = bot

    @commands.command(name='purge', aliases=['clear'])

    @commands.has_permissions(manage_messages=True)

    @commands.bot_has_permissions(manage_messages=True)

    async def purge(self, ctx, amount: int):

        """

        Delete a specified number of messages.

        

        Example:

        !purge 10 - Deletes 10 most recent messages

        """

        if amount <= 0:

            await ctx.send("❌ Please specify a positive number of messages to delete.")

            return

        

        if amount > 1000:

            await ctx.send("❌ Cannot delete more than 1000 messages at once.")

            return

        

        # Delete the command message first

        await ctx.message.delete()

        

        # Purge messages

        deleted = await ctx.channel.purge(limit=amount)

        

        # Send confirmation (will auto-delete after 5 seconds)

        confirm_msg = await ctx.send(f"✅ Purged {len(deleted)} messages.", delete_after=5)

    @commands.command(name='purgeuser', aliases=['clearuser'])

    @commands.has_permissions(manage_messages=True)

    @commands.bot_has_permissions(manage_messages=True)

    async def purge_user(self, ctx, member: discord.Member, amount: int = 100):

        """

        Delete messages from a specific user.

        

        Example:

        !purgeuser @User 50 - Deletes 50 most recent messages from @User

        """

        if amount <= 0:

            await ctx.send("❌ Please specify a positive number of messages to delete.")

            return

        

        if amount > 1000:

            amount = 1000

        

        # Delete the command message first

        await ctx.message.delete()

        

        # Check if messages were deleted

        def is_target_user(m):

            return m.author == member

        

        deleted = await ctx.channel.purge(limit=amount, check=is_target_user)

        

        if deleted:

            confirm_msg = await ctx.send(f"✅ Purged {len(deleted)} messages from {member.mention}.", delete_after=5)

        else:

            confirm_msg = await ctx.send(f"❌ No messages found from {member.mention} in the last {amount} messages.", delete_after=5)

    # Error handling

    @purge.error

    async def purge_error(self, ctx, error):

        if isinstance(error, commands.MissingPermissions):

            await ctx.send("❌ You need the 'Manage Messages' permission to use this command.")

        elif isinstance(error, commands.BotMissingPermissions):

            await ctx.send("❌ I need the 'Manage Messages' permission to execute this command.")

    @purge_user.error

    async def purge_user_error(self, ctx, error):

        if isinstance(error, commands.BadArgument):

            await ctx.send("❌ Please mention a valid user.")

async def setup(bot):

    """Setup function for loading the cog."""

    await bot.add_cog(Purge(bot))