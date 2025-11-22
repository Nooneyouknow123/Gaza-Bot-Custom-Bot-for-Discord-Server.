import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
from datetime import datetime, timedelta
import asyncio

DB_FILE = "staff_strikes.db"
STAFF_STRIKE_ROLE_ID = 1107840548263436389  # Staff strike role ID
STAFF_ROLE_ID = 1374348131918938162 # Staff role that can issue strikes

# Roles to remove when terminated (all your specified role IDs)
TERMINATION_ROLES = [
    1372888247901880420, 1421550108566360324, 1412794584370774170, 1411401300570017873, 
    1412015173337612360, 1370146430710452245, 1370146429682843801, 1383043648622559313, 
    1414671323036258335, 1387864367491711086, 1382812189756227755, 1383330830385938442, 
    1382812280663576637, 1373223730079203368, 1382811975142342748, 1387015051734683669, 
    1387014496513691708, 1429700623174995969, 1388981878005956628, 1387700220565131295, 
    1383046145399324713, 1383045894131421215, 1383044585961426954, 1404737986502987786, 
    1396957807919501442
]

class Staff_Strikecog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_channel_id = None  # Will be set by command
        
        # Init DB
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS strikes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            duration TEXT,
            strike_count INTEGER,
            expires_at TEXT,
            timestamp TEXT
        )
        """)
        
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER
        )
        """)
        self.conn.commit()
        
        # Start background task to check expired strikes
        self.check_expired_strikes.start()

    def cog_unload(self):
        self.check_expired_strikes.cancel()

    async def load_config(self, guild_id):
        """Load configuration for the guild"""
        self.cursor.execute(
            "SELECT log_channel_id FROM config WHERE guild_id = ?",
            (guild_id,)
        )
        result = self.cursor.fetchone()
        self.log_channel_id = result[0] if result else None

    # ------------------------------
    # Background task to remove expired strikes
    # ------------------------------
    @tasks.loop(hours=24)
    async def check_expired_strikes(self):
        try:
            current_time = datetime.now().isoformat()
            self.cursor.execute(
                "SELECT id, user_id, guild_id FROM strikes WHERE expires_at <= ? AND expires_at IS NOT NULL",
                (current_time,)
            )
            expired_strikes = self.cursor.fetchall()
            
            for strike_id, user_id, guild_id in expired_strikes:
                # Remove from database
                self.cursor.execute("DELETE FROM strikes WHERE id = ?", (strike_id,))
                self.conn.commit()
                
                # Remove staff strike role if user has no more active strikes
                self.cursor.execute(
                    "SELECT COUNT(*) FROM strikes WHERE user_id = ? AND (expires_at > ? OR expires_at IS NULL)",
                    (user_id, current_time)
                )
                active_strikes = self.cursor.fetchone()[0]
                
                if active_strikes == 0:
                    for guild in self.bot.guilds:
                        if guild.id == guild_id:
                            member = guild.get_member(user_id)
                            if member:
                                strike_role = guild.get_role(STAFF_STRIKE_ROLE_ID)
                                if strike_role and strike_role in member.roles:
                                    await member.remove_roles(strike_role, reason="Strike expired")
                            break
                
                print(f"Removed expired strike {strike_id} for user {user_id}")
                
        except Exception as e:
            print(f"Error checking expired strikes: {e}")

    @check_expired_strikes.before_loop
    async def before_check_expired_strikes(self):
        await self.bot.wait_until_ready()

    # ------------------------------
    # Autocomplete for duration
    # ------------------------------
    async def duration_autocomplete(self, interaction: discord.Interaction, current: str):
        durations = ["1 Week", "2 Weeks", "1 Month", "3 Months", "6 Months", "1 Year", "Permanent", "Terminated"]
        return [
            app_commands.Choice(name=d, value=d)
            for d in durations if current.lower() in d.lower()
        ][:25]

    # ------------------------------
    # Helper function to calculate expiry date
    # ------------------------------
    def calculate_expiry_date(self, duration_str: str):
        if duration_str == "Permanent" or duration_str == "Terminated":
            return None  # Never expires
        
        duration_map = {
            "1 Week": timedelta(weeks=1),
            "2 Weeks": timedelta(weeks=2),
            "1 Month": timedelta(days=30),
            "3 Months": timedelta(days=90),
            "6 Months": timedelta(days=180),
            "1 Year": timedelta(days=365)
        }
        
        duration_delta = duration_map.get(duration_str, timedelta(days=30))
        expiry_date = datetime.now() + duration_delta
        return expiry_date.isoformat()

    # ------------------------------
    # /infract_channel command
    # ------------------------------
    @app_commands.command(name="infract_channel", description="Set the channel for strike logs")
    @app_commands.describe(channel="The channel where strike embeds will be sent")
    async def infract_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            # Permission check - only staff can set channel
            if not any(role.id == STAFF_ROLE_ID or role.position > interaction.guild.get_role(STAFF_ROLE_ID).position for role in interaction.user.roles):
                return await interaction.response.send_message("❌ You are not authorized to set the infraction channel.", ephemeral=True)

            guild_id = interaction.guild.id
            
            # Save to database
            self.cursor.execute("""
                INSERT OR REPLACE INTO config (guild_id, log_channel_id)
                VALUES (?, ?)
            """, (guild_id, channel.id))
            self.conn.commit()
            
            self.log_channel_id = channel.id
            
            await interaction.response.send_message(
                f"✅ Infraction log channel set to {channel.mention}", 
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message("❌ Failed to set infraction channel.", ephemeral=True)
            print("Infract channel error:", e)

    # ------------------------------
    # /infract command
    # ------------------------------
    @app_commands.command(name="infract", description="Issue a staff strike to a member")
    @app_commands.describe(
        user="Select the user to strike",
        duration="Duration of the strike in weeks",
        reason="Reason for the strike"
    )
    @app_commands.autocomplete(duration=duration_autocomplete)
    async def infract(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str
    ):
        try:
            moderator = interaction.user
            guild = interaction.guild

            # Load config
            await self.load_config(guild.id)

            # Self-check
            if user.id == moderator.id:
                return await interaction.response.send_message("❌ You cannot strike yourself.", ephemeral=True)

            # Permission check - user must have staff role or higher
            if not any(role.id == STAFF_ROLE_ID or role.position > guild.get_role(STAFF_ROLE_ID).position for role in moderator.roles):
                return await interaction.response.send_message(
                    "❌ You are not authorized to issue staff strikes.", ephemeral=True
                )

            # Hierarchy check
            if user.top_role >= moderator.top_role:
                return await interaction.response.send_message(
                    "❌ You cannot strike someone with equal or higher role than you.", ephemeral=True
                )

            # Calculate strike count
            self.cursor.execute(
                "SELECT COUNT(*) FROM strikes WHERE user_id = ?",
                (user.id,)
            )
            current_strike_count = self.cursor.fetchone()[0]
            new_strike_count = current_strike_count + 1

            # Calculate expiry date
            expires_at = self.calculate_expiry_date(duration)

            # Save to DB
            timestamp = datetime.now().isoformat()
            self.cursor.execute("""
                INSERT INTO strikes (user_id, moderator_id, reason, duration, strike_count, expires_at, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user.id, moderator.id, reason, duration, new_strike_count, expires_at, timestamp))
            self.conn.commit()

            # Role management
            if duration == "Terminated":
                # Remove all specified roles for termination
                roles_to_remove = [
                    guild.get_role(rid) for rid in TERMINATION_ROLES
                    if guild.get_role(rid) is not None and guild.get_role(rid) in user.roles
                ]
                if roles_to_remove:
                    await user.remove_roles(*roles_to_remove, reason="Termination strike issued")
                
                # Also remove strike role if present
                strike_role = guild.get_role(STAFF_STRIKE_ROLE_ID)
                if strike_role and strike_role in user.roles:
                    await user.remove_roles(strike_role, reason="Termination strike issued")
                    
            else:
                # Add staff strike role for non-termination strikes
                strike_role = guild.get_role(STAFF_STRIKE_ROLE_ID)
                if strike_role and strike_role not in user.roles:
                    await user.add_roles(strike_role, reason="Staff strike issued")

            # Create embed
            embed = discord.Embed(
                title="🚨 Staff Strike Issued",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Staff Member", value=user.mention, inline=True)
            embed.add_field(name="Issued By", value=moderator.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Strike Counter", value=f"{new_strike_count}/5", inline=True)
            embed.add_field(name="Duration", value=duration, inline=True)
            
            if expires_at and duration != "Permanent" and duration != "Terminated":
                expiry_date = datetime.fromisoformat(expires_at).strftime("%Y-%m-%d at %H:%M UTC")
                embed.add_field(name="Expires On", value=expiry_date, inline=True)
            
            if new_strike_count >= 5:
                embed.add_field(name="⚠️ Warning", value="User has reached 5 strikes!", inline=False)
            
            embed.set_footer(text="Staff Strike System")
            
            # Send to log channel if set
            if self.log_channel_id:
                log_channel = guild.get_channel(self.log_channel_id)
                if log_channel:
                    await log_channel.send(embed=embed)
            else:
                # Fallback to current channel if no log channel set
                await interaction.channel.send(embed=embed)

            await interaction.response.send_message(
                f"✅ Staff strike logged for {user.mention}. Strike count: {new_strike_count}/5", 
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message("❌ Failed to issue staff strike.", ephemeral=True)
            print("Infract error:", e)

    # ------------------------------
    # /strike_history command
    # ------------------------------
    @app_commands.command(name="strike_history", description="View a user's staff strike history")
    @app_commands.describe(user="Select the user")
    async def strike_history(self, interaction: discord.Interaction, user: discord.Member):
        try:
            self.cursor.execute(
                "SELECT reason, duration, strike_count, moderator_id, timestamp, expires_at FROM strikes WHERE user_id = ? ORDER BY timestamp DESC",
                (user.id,)
            )
            rows = self.cursor.fetchall()

            if not rows:
                return await interaction.response.send_message("✅ No staff strikes found for this user.", ephemeral=True)

            embeds = []
            for i, (reason, duration, strike_count, moderator_id, timestamp, expires_at) in enumerate(rows, 1):
                moderator = interaction.guild.get_member(moderator_id)
                
                embed = discord.Embed(
                    title=f"Staff Strike #{i} - {user.display_name}",
                    color=discord.Color.orange(),
                    timestamp=datetime.fromisoformat(timestamp)
                )
                embed.add_field(name="Staff Member", value=user.mention, inline=True)
                embed.add_field(name="Strike Count", value=f"{strike_count}/5", inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Duration", value=duration, inline=True)
                
                if expires_at:
                    expiry_date = datetime.fromisoformat(expires_at).strftime("%Y-%m-%d at %H:%M UTC")
                    embed.add_field(name="Expires On", value=expiry_date, inline=True)
                elif duration in ["Permanent", "Terminated"]:
                    embed.add_field(name="Expires On", value="Never", inline=True)
                
                embed.add_field(
                    name="Issued By",
                    value=moderator.mention if moderator else f"<@{moderator_id}>",
                    inline=True
                )
                
                embed.set_footer(text=f"Strike #{i} • Issued on")
                embeds.append(embed)

            # Send first embed as response, others as followups if needed
            if len(embeds) == 1:
                await interaction.response.send_message(embed=embeds[0], ephemeral=True)
            else:
                await interaction.response.send_message(embed=embeds[0], ephemeral=True)
                for embed in embeds[1:]:
                    await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message("❌ Failed to fetch staff strikes.", ephemeral=True)
            print("Strike history error:", e)

    # ------------------------------
    # /remove_strike command
    # ------------------------------
    @app_commands.command(name="remove_strike", description="Remove a staff strike from a user")
    @app_commands.describe(user="Select the user to remove strike from")
    async def remove_strike(self, interaction: discord.Interaction, user: discord.Member):
        try:
            moderator = interaction.user

            # Permission check
            if not any(role.id == STAFF_ROLE_ID or role.position > interaction.guild.get_role(STAFF_ROLE_ID).position for role in moderator.roles):
                return await interaction.response.send_message(
                    "❌ You are not authorized to remove staff strikes.", ephemeral=True
                )

            # Get latest strike
            self.cursor.execute(
                "SELECT id FROM strikes WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
                (user.id,)
            )
            strike = self.cursor.fetchone()

            if not strike:
                return await interaction.response.send_message("❌ No strikes found for this user.", ephemeral=True)

            # Remove from database
            strike_id = strike[0]
            self.cursor.execute("DELETE FROM strikes WHERE id = ?", (strike_id,))
            self.conn.commit()

            # Check if user has any remaining active strikes
            current_time = datetime.now().isoformat()
            self.cursor.execute(
                "SELECT COUNT(*) FROM strikes WHERE user_id = ? AND (expires_at > ? OR expires_at IS NULL)",
                (user.id, current_time)
            )
            active_strikes = self.cursor.fetchone()[0]

            # Remove strike role if no active strikes remain
            if active_strikes == 0:
                strike_role = interaction.guild.get_role(STAFF_STRIKE_ROLE_ID)
                if strike_role and strike_role in user.roles:
                    await user.remove_roles(strike_role, reason="Last strike removed")

            await interaction.response.send_message(
                f"✅ Latest staff strike removed from {user.mention}. Remaining active strikes: {active_strikes}/5", 
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message("❌ Failed to remove staff strike.", ephemeral=True)
            print("Remove strike error:", e)

    # ------------------------------
    # /strike_info command - View current strike status
    # ------------------------------
    @app_commands.command(name="strike_info", description="View your current strike status")
    async def strike_info(self, interaction: discord.Interaction):
        try:
            user = interaction.user
            
            # Get active strikes
            current_time = datetime.now().isoformat()
            self.cursor.execute(
                "SELECT reason, duration, timestamp, expires_at FROM strikes WHERE user_id = ? AND (expires_at > ? OR expires_at IS NULL) ORDER BY timestamp DESC",
                (user.id, current_time)
            )
            active_strikes = self.cursor.fetchall()
            
            # Get total strike count
            self.cursor.execute(
                "SELECT COUNT(*) FROM strikes WHERE user_id = ?",
                (user.id,)
            )
            total_strikes = self.cursor.fetchone()[0]

            embed = discord.Embed(
                title=f"Strike Information - {user.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.add_field(name="Total Strikes", value=total_strikes, inline=True)
            embed.add_field(name="Active Strikes", value=len(active_strikes), inline=True)
            embed.add_field(name="Strike Limit", value="5/5", inline=True)
            
            if active_strikes:
                strike_list = ""
                for i, (reason, duration, timestamp, expires_at) in enumerate(active_strikes, 1):
                    strike_list += f"**{i}. {reason}**\n"
                    strike_list += f"   Duration: {duration}\n"
                    if expires_at:
                        expiry = datetime.fromisoformat(expires_at).strftime("%Y-%m-%d")
                        strike_list += f"   Expires: {expiry}\n"
                    strike_list += "\n"
                
                embed.add_field(name="Active Strike Details", value=strike_list, inline=False)
            else:
                embed.add_field(name="Status", value="✅ No active strikes", inline=False)
            
            if total_strikes >= 5:
                embed.add_field(name="⚠️ Warning", value="You have reached the maximum strike limit!", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message("❌ Failed to fetch strike information.", ephemeral=True)
            print("Strike info error:", e)

async def setup(bot: commands.Bot):
    await bot.add_cog(Staff_Strikecog(bot))