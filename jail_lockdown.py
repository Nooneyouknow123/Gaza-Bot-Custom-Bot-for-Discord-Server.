# jail_lockdown_cog.py

import discord

from discord.ext import commands

import sqlite3

import logging

import asyncio

from typing import Optional

logger = logging.getLogger("jail_lockdown_cog")

class JailLockdownCog(commands.Cog):

    def __init__(self, bot: commands.Bot):

        self.bot = bot

        self._db_lock = asyncio.Lock()

    async def _run_db(self, fn, *args, **kwargs):

        """Run DB operations in executor"""

        async with self._db_lock:

            loop = asyncio.get_running_loop()

            return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    def _get_guild_config_sync(self, guild_id: int):

        """Sync function to get guild config from DB"""

        try:

            conn = sqlite3.connect("jail_system.db")

            conn.row_factory = sqlite3.Row

            c = conn.cursor()

            r = c.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()

            conn.close()

            return dict(r) if r else None

        except Exception as e:

            logger.error(f"DB error in _get_guild_config_sync: {e}")

            return None

    async def _log_mod(self, guild: discord.Guild, *, embed: discord.Embed = None, content: str = None):

        """Safe mod logging"""

        try:

            logs_cog = self.bot.get_cog("LogsCog")

            if logs_cog and hasattr(logs_cog, "log") and callable(logs_cog.log):

                coro = logs_cog.log(guild, "mod", embed=embed, content=content)

                if asyncio.iscoroutine(coro):

                    await coro

                else:

                    logger.info(f"Mod log: {content}")

            else:

                logger.info(f"Mod log for guild {guild.id}: {content}")

        except Exception:

            logger.exception("_log_mod failed")

    async def _setup_channel_permissions(self, channel, jail_role, appeals_channel_id=None):

        """Set up permissions for a single channel for jailed users"""

        try:

            # If this is the appeals channel, allow read but not send

            if channel.id == appeals_channel_id:

                await channel.set_permissions(jail_role, 

                                            read_messages=True, 

                                            send_messages=False,

                                            read_message_history=True)

                logger.info(f"Set appeals permissions for {channel.name}")

            

            # Handle text channels

            elif isinstance(channel, discord.TextChannel):

                await channel.set_permissions(jail_role, 

                                            read_messages=False, 

                                            send_messages=False)

                logger.info(f"Set text channel permissions for {channel.name}")

            

            # Handle voice channels

            elif isinstance(channel, discord.VoiceChannel):

                await channel.set_permissions(jail_role, 

                                            connect=False, 

                                            view_channel=False)

                logger.info(f"Set voice channel permissions for {channel.name}")

            

            # Handle categories

            elif isinstance(channel, discord.CategoryChannel):

                await channel.set_permissions(jail_role, 

                                            read_messages=False, 

                                            send_messages=False,

                                            connect=False,

                                            view_channel=False)

                logger.info(f"Set category permissions for {channel.name}")

            

            return True

            

        except Exception as e:

            logger.error(f"Failed to set permissions for {channel.name}: {e}")

            return False

    @commands.Cog.listener()

    async def on_guild_channel_create(self, channel):

        """Automatically set jail permissions when a new channel is created"""

        try:

            guild = channel.guild

            

            # Get guild config

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            if not cfg or not cfg.get("jail_role"):

                return

            

            jail_role = guild.get_role(cfg["jail_role"])

            if not jail_role:

                return

            

            appeals_channel_id = cfg.get("appeals_channel")

            

            # Set permissions for the new channel

            success = await self._setup_channel_permissions(channel, jail_role, appeals_channel_id)

            

            if success:

                logger.info(f"Automatically set jail permissions for new channel: {channel.name}")

                

                # Log the action

                le = discord.Embed(

                    title="🔧 Auto Jail Permissions",

                    description=f"Automatically set jail permissions for new channel: {channel.mention}",

                    color=discord.Color.green()

                )

                await self._log_mod(guild, embed=le)

                

        except Exception as e:

            logger.error(f"Failed to auto-set permissions for new channel {channel.name}: {e}")

    @commands.Cog.listener()

    async def on_guild_channel_update(self, before, after):

        """Reset jail permissions if channel is moved to a different category"""

        try:

            # Only proceed if the channel was moved between categories

            if before.category != after.category:

                guild = after.guild

                

                # Get guild config

                cfg = await self._run_db(self._get_guild_config_sync, guild.id)

                if not cfg or not cfg.get("jail_role"):

                    return

                

                jail_role = guild.get_role(cfg["jail_role"])

                if not jail_role:

                    return

                

                appeals_channel_id = cfg.get("appeals_channel")

                

                # Re-apply permissions

                success = await self._setup_channel_permissions(after, jail_role, appeals_channel_id)

                

                if success:

                    logger.info(f"Reset jail permissions for moved channel: {after.name}")

                    

        except Exception as e:

            logger.error(f"Failed to reset permissions for moved channel {after.name}: {e}")

    @commands.command(name="lockdownjail")

    @commands.has_permissions(administrator=True)

    async def lockdown_jail(self, ctx: commands.Context):

        """Automatically set up channel permissions so jailed users can't see any channels except appeals"""

        try:

            guild = ctx.guild

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            

            if not cfg or not cfg.get("jail_role"):

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jail system not set up. Use `.setupjail` first.",

                    color=discord.Color.red()

                ))

            

            jail_role = guild.get_role(cfg["jail_role"])

            if not jail_role:

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jail role not found.",

                    color=discord.Color.red()

                ))

            

            appeals_channel = guild.get_channel(cfg["appeals_channel"])

            if not appeals_channel:

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Appeals channel not found.",

                    color=discord.Color.red()

                ))

            

            # Counters for tracking

            processed = 0

            failed = 0

            

            embed = discord.Embed(

                title="🔒 Jail Lockdown Setup",

                description="Setting up channel permissions... This may take a while.",

                color=discord.Color.orange()

            )

            msg = await ctx.send(embed=embed)

            

            # Process all channels

            for channel in guild.channels:  # This includes all types: text, voice, category

                try:

                    success = await self._setup_channel_permissions(channel, jail_role, appeals_channel.id)

                    if success:

                        processed += 1

                    else:

                        failed += 1

                        

                except Exception as e:

                    failed += 1

                    logger.error(f"Failed to set permissions for {channel.name}: {e}")

            

            # Update completion embed

            complete_embed = discord.Embed(

                title="✅ Jail Lockdown Complete",

                description=f"Jailed users will now only see the appeals channel.",

                color=discord.Color.green()

            )

            complete_embed.add_field(

                name="📊 Results",

                value=f"✅ Processed: {processed} channels/categories\n❌ Failed: {failed}",

                inline=False

            )

            complete_embed.add_field(

                name="🔓 Appeals Channel",

                value=f"{appeals_channel.mention} - Jailed users can see but not send messages",

                inline=False

            )

            complete_embed.add_field(

                name="🤖 Auto-Setup",

                value="New channels will automatically get jail permissions configured!",

                inline=False

            )

            

            await msg.edit(embed=complete_embed)

            

            # Log the action

            le = discord.Embed(

                title="🔒 Jail Lockdown Applied",

                description=f"Channel permissions set by {ctx.author.mention}",

                color=discord.Color.blurple()

            )

            le.add_field(name="Channels Processed", value=processed)

            le.add_field(name="Failures", value=failed)

            await self._log_mod(guild, embed=le)

            

        except Exception as e:

            logger.exception("lockdown_jail failed")

            await ctx.send(embed=discord.Embed(

                title="Error",

                description=f"Lockdown failed: {e}",

                color=discord.Color.red()

            ))

    @commands.command(name="fixjailperms")

    @commands.has_permissions(administrator=True)

    async def fix_jail_perms(self, ctx: commands.Context):

        """Fix jail permissions for all existing channels"""

        try:

            guild = ctx.guild

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            

            if not cfg or not cfg.get("jail_role"):

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jail system not set up. Use `.setupjail` first.",

                    color=discord.Color.red()

                ))

            

            jail_role = guild.get_role(cfg["jail_role"])

            if not jail_role:

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jail role not found.",

                    color=discord.Color.red()

                ))

            

            appeals_channel_id = cfg.get("appeals_channel")

            

            embed = discord.Embed(

                title="🔧 Fixing Jail Permissions",

                description="Checking and fixing permissions for all channels...",

                color=discord.Color.orange()

            )

            msg = await ctx.send(embed=embed)

            

            processed = 0

            fixed = 0

            failed = 0

            

            for channel in guild.channels:

                try:

                    processed += 1

                    

                    # Check if permissions are already correct

                    perms = channel.permissions_for(jail_role)

                    

                    if channel.id == appeals_channel_id:

                        # Should have read but not send

                        if not perms.read_messages or perms.send_messages:

                            await self._setup_channel_permissions(channel, jail_role, appeals_channel_id)

                            fixed += 1

                    else:

                        # Should not have access

                        if perms.read_messages or perms.view_channel:

                            await self._setup_channel_permissions(channel, jail_role, appeals_channel_id)

                            fixed += 1

                            

                except Exception as e:

                    failed += 1

                    logger.error(f"Failed to fix permissions for {channel.name}: {e}")

            

            complete_embed = discord.Embed(

                title="✅ Permissions Fixed",

                color=discord.Color.green()

            )

            complete_embed.add_field(name="Channels Processed", value=processed, inline=True)

            complete_embed.add_field(name="Permissions Fixed", value=fixed, inline=True)

            complete_embed.add_field(name="Failures", value=failed, inline=True)

            

            await msg.edit(embed=complete_embed)

            

        except Exception as e:

            logger.exception("fixjailperms failed")

            await ctx.send(embed=discord.Embed(

                title="Error",

                description=f"Fix permissions failed: {e}",

                color=discord.Color.red()

            ))

    # [Die bestehenden jailperms und jailstatus Befehle bleiben unverändert]

    @commands.command(name="jailperms")

    @commands.has_permissions(administrator=True)

    async def check_jail_perms(self, ctx: commands.Context):

        """Check which channels jailed users can currently access"""

        # ... (existing code remains unchanged)

    @commands.command(name="jailstatus")

    @commands.has_permissions(administrator=True)

    async def jail_status(self, ctx: commands.Context):

        """Check the overall status of the jail system"""

        # ... (existing code remains unchanged)

async def setup(bot: commands.Bot):

    await bot.add_cog(JailLockdownCog(bot))