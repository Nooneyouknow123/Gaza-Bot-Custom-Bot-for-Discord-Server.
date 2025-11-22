import discord

from discord.ext import commands

class RoleManagement(commands.Cog):

    def __init__(self, bot):

        self.bot = bot

        self.authorized_user_id = 951863963132506232  # Your user ID

    @commands.command(name='addrole')

    async def addrole_command(self, ctx, user: discord.Member, role_id: str):

        """Add a role to a user (Only authorized user can use this)"""

        

        # Check if the command user is authorized

        if ctx.author.id != self.authorized_user_id:

            await ctx.send("ur not tuff Lil bro")

            return

        

        try:

            # Convert role_id to integer and get the role

            role = ctx.guild.get_role(int(role_id))

            

            if role is None:

                await ctx.send("❌ Role not found. Please check the role ID.")

                return

            

            # Add the role to the user

            await user.add_roles(role)

            await ctx.send(f"✅ Successfully added {role.mention} to {user.mention}")

            

        except ValueError:

            await ctx.send("❌ Invalid role ID. Please provide a valid numeric role ID.")

        except discord.Forbidden:

            await ctx.send("❌ I don't have permission to add that role.")

        except Exception as e:

            await ctx.send(f"❌ An error occurred: {str(e)}")

async def setup(bot):

    await bot.add_cog(RoleManagement(bot))