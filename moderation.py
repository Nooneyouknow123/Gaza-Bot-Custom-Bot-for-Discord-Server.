# moderation_cog.py
# Moderation Cog (discord.py v2) with SQLite database
# Features:
#  - Prefix commands 
#  - Warnings (add/list/remove/clear)
#  - Notes for staff
#  - Safelist (users & roles protected)
#  - Jail role config + jail/unjail (stores/restores roles)
#  - Mute/unmute using Discord's built-in timeout (Member.edit(timeout=...))
#  - Ban/unban/kick
#  - SQLite database persistence
# Requirements: discord.py v2.x, sqlite3
# Usage: put in cogs folder and load as an extension

import discord
from discord.ext import commands, tasks
import sqlite3
import os
import datetime
import uuid
import asyncio
from typing import Optional

UNIT_MULTIPLIERS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days"
}

MAX_MUTE_DAYS = 28  # Discord maximum timeout

DB_FILE = "moderation_database.db"

class Database:
    def __init__(self):
        self.db_file = DB_FILE
        self._setup_db()
    
    def _setup_db(self):
        """Initialize database with required tables"""
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        
        # Guild settings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT PRIMARY KEY,
                staff_role TEXT,
                log_channel TEXT,
                jail_role TEXT
            )
        ''')
        
        # Safelist table
        c.execute('''
            CREATE TABLE IF NOT EXISTS safelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                type TEXT, -- 'user' or 'role'
                target_id TEXT,
                UNIQUE(guild_id, type, target_id)
            )
        ''')
        
        # Warnings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                id TEXT PRIMARY KEY,
                guild_id TEXT,
                user_id TEXT,
                moderator_id TEXT,
                reason TEXT,
                timestamp TEXT
            )
        ''')
        
        # Notes table
        c.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                guild_id TEXT,
                user_id TEXT,
                author_id TEXT,
                note TEXT,
                timestamp TEXT
            )
        ''')
        
        # Jailed users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS jailed_users (
                user_id TEXT,
                guild_id TEXT,
                roles_json TEXT, -- JSON array of role IDs
                timestamp TEXT,
                moderator_id TEXT,
                reason TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        return sqlite3.connect(self.db_file)

def create_mod_embed(title: str, description: str, color: discord.Color = discord.Color.blurple()):
    e = discord.Embed(
        title=f"🛠️ {title}",
        description=description,
        color=color,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_footer(text="Moderation System • v2")
    return e

def create_error(msg: str):
    return create_mod_embed("Action Denied", msg, color=discord.Color.dark_red())

def create_success(title: str, msg: str):
    return create_mod_embed(title, msg, color=discord.Color.green())

class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self._save_lock = asyncio.Lock()

    # ----------------- database helpers -----------------
    async def execute_db(self, query: str, params: tuple = ()):
        """Execute a database query asynchronously"""
        def _execute():
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute(query, params)
            conn.commit()
            result = c.lastrowid
            conn.close()
            return result
        return await asyncio.get_event_loop().run_in_executor(None, _execute)
    
    async def fetchone_db(self, query: str, params: tuple = ()):
        """Fetch one row from database asynchronously"""
        def _fetch():
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute(query, params)
            result = c.fetchone()
            conn.close()
            return result
        return await asyncio.get_event_loop().run_in_executor(None, _fetch)
    
    async def fetchall_db(self, query: str, params: tuple = ()):
        """Fetch all rows from database asynchronously"""
        def _fetch():
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute(query, params)
            result = c.fetchall()
            conn.close()
            return result
        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    # ----------------- guild config helpers -----------------
    async def get_guild_setting(self, guild_id: int, setting: str):
        result = await self.fetchone_db(
            "SELECT * FROM guild_settings WHERE guild_id = ?", 
            (str(guild_id),)
        )
        if result:
            # result: (guild_id, staff_role, log_channel, jail_role)
            settings = {
                'staff_role': result[1],
                'log_channel': result[2],
                'jail_role': result[3]
            }
            return settings.get(setting)
        return None

    async def set_guild_setting(self, guild_id: int, setting: str, value: str):
        # Check if guild exists
        existing = await self.fetchone_db(
            "SELECT * FROM guild_settings WHERE guild_id = ?", 
            (str(guild_id),)
        )
        
        if existing:
            # Update existing
            if setting == 'staff_role':
                await self.execute_db(
                    "UPDATE guild_settings SET staff_role = ? WHERE guild_id = ?",
                    (value, str(guild_id))
                )
            elif setting == 'log_channel':
                await self.execute_db(
                    "UPDATE guild_settings SET log_channel = ? WHERE guild_id = ?",
                    (value, str(guild_id))
                )
            elif setting == 'jail_role':
                await self.execute_db(
                    "UPDATE guild_settings SET jail_role = ? WHERE guild_id = ?",
                    (value, str(guild_id))
                )
        else:
            # Insert new
            staff = value if setting == 'staff_role' else None
            log = value if setting == 'log_channel' else None
            jail = value if setting == 'jail_role' else None
            
            await self.execute_db(
                "INSERT INTO guild_settings (guild_id, staff_role, log_channel, jail_role) VALUES (?, ?, ?, ?)",
                (str(guild_id), staff, log, jail)
            )

    # ----------------- staff check -----------------
    def is_staff(self, member: discord.Member):
        """Basic in-code check for staff: configured staff role OR Manage Messages / Kick Members."""
        # We'll get the staff role synchronously for this check
        # For async operations, we'd need to adjust this
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT staff_role FROM guild_settings WHERE guild_id = ?", (str(member.guild.id),))
        result = c.fetchone()
        conn.close()
        
        if result and result[0]:
            staff_role = discord.utils.get(member.roles, id=int(result[0]))
            if staff_role:
                return True
        
        # fallback on permissions
        perms = member.guild_permissions
        return perms.manage_messages or perms.kick_members or perms.ban_members

    async def is_protected(self, guild: discord.Guild, target: discord.Member):
        # Check user safelist
        user_result = await self.fetchone_db(
            "SELECT * FROM safelist WHERE guild_id = ? AND type = 'user' AND target_id = ?",
            (str(guild.id), str(target.id))
        )
        if user_result:
            return True
        
        # Check role safelist
        target_role_ids = {str(r.id) for r in target.roles}
        role_results = await self.fetchall_db(
            "SELECT target_id FROM safelist WHERE guild_id = ? AND type = 'role'",
            (str(guild.id),)
        )
        for result in role_results:
            if result[0] in target_role_ids:
                return True
        
        return False

    async def log(self, guild: discord.Guild, embed: discord.Embed):
        chan_id = await self.get_guild_setting(guild.id, 'log_channel')
        if not chan_id:
            return
        channel = guild.get_channel(int(chan_id))
        if not channel:
            return
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    # ----------------- checks -----------------
    def staff_only():
        def predicate(ctx):
            if ctx.guild is None:
                raise commands.CheckFailure("This command must be used in a server.")
            cog: ModerationCog = ctx.cog
            if cog.is_staff(ctx.author):
                return True
            raise commands.CheckFailure("You need the staff role or Manage Messages / Kick Members permission.")
        return commands.check(predicate)

    # ----------------- commands: setup -----------------
    @commands.command(name="setstaffrole")
    @commands.has_permissions(administrator=True)
    async def set_staff_role(self, ctx, role: discord.Role):
        await self.set_guild_setting(ctx.guild.id, 'staff_role', str(role.id))
        await ctx.send(embed=create_success("Staff Role Set", f"Staff role set to {role.mention}"))
        await self.log(ctx.guild, create_mod_embed("Config", f"Staff role set to {role.name} ({role.id}) by {ctx.author}"))

    @commands.command(name="setlogchannel")
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        await self.set_guild_setting(ctx.guild.id, 'log_channel', str(channel.id))
        await ctx.send(embed=create_success("Log Channel Set", f"Log channel set to {channel.mention}"))
        await self.log(ctx.guild, create_mod_embed("Config", f"Log channel set to {channel.mention} by {ctx.author}"))

    @commands.command(name="jailrole")
    @commands.has_permissions(administrator=True)
    async def set_jail_role(self, ctx, role_input: str):
        """
        Set the jail role by id, mention (<@&id>) or role name.
        Usage: !jailrole 123456789012345678  OR !jailrole @Jailed  OR !jailrole Jailed
        """
        role = None
        if role_input.isdigit():
            role = ctx.guild.get_role(int(role_input))
        else:
            if role_input.startswith("<@&") and role_input.endswith(">"):
                try:
                    rid = int(role_input[3:-1])
                    role = ctx.guild.get_role(rid)
                except Exception:
                    role = None
            else:
                role = discord.utils.get(ctx.guild.roles, name=role_input)
        if not role:
            await ctx.send(embed=create_error("Role not found. Use role ID, mention, or exact name."))
            return
        
        await self.set_guild_setting(ctx.guild.id, 'jail_role', str(role.id))
        await ctx.send(embed=create_success("Jail Role Set", f"Jail role set to {role.mention}"))
        await self.log(ctx.guild, create_mod_embed("Config", f"Jail role set to {role.name} ({role.id}) by {ctx.author}"))

    @commands.command(name="config")
    @staff_only()
    async def show_config(self, ctx):
        staff = await self.get_guild_setting(ctx.guild.id, 'staff_role')
        logc = await self.get_guild_setting(ctx.guild.id, 'log_channel')
        jail = await self.get_guild_setting(ctx.guild.id, 'jail_role')
        
        staff_display = f"<not set>" if not staff else f"<@&{staff}>"
        logc_display = f"<not set>" if not logc else f"<#{logc}>"
        jail_display = f"<not set>" if not jail else f"<@&{jail}>"
        
        # Get safelist
        users = await self.fetchall_db(
            "SELECT target_id FROM safelist WHERE guild_id = ? AND type = 'user'",
            (str(ctx.guild.id),)
        )
        roles = await self.fetchall_db(
            "SELECT target_id FROM safelist WHERE guild_id = ? AND type = 'role'",
            (str(ctx.guild.id),)
        )
        
        embed = create_mod_embed("Server Config", f"Staff role: {staff_display}\nLog channel: {logc_display}\nJail role: {jail_display}")
        embed.add_field(name="Safelist - Users", value=", ".join([u[0] for u in users]) if users else "(none)", inline=False)
        embed.add_field(name="Safelist - Roles", value=", ".join([r[0] for r in roles]) if roles else "(none)", inline=False)
        await ctx.send(embed=embed)

    # ---------------- SAFELIST COMMANDS ----------------
    @commands.group(name="safelist", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def safelist_group(self, ctx):
        """Safelist management for users/roles"""
        await ctx.send(embed=create_mod_embed(
            "Safelist",
            "Usage:\n"
            "`!safelist add <@user/@role or id>`\n"
            "`!safelist remove <@user/@role or id>`\n"
            "`!safelist list`"
        ))

    @safelist_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def safelist_add(self, ctx, *, target: str):
        target = target.strip().replace("<", "").replace(">", "").replace("@", "").replace("!", "").replace("&", "")
        added = None

        # Try member
        member = ctx.guild.get_member(int(target)) if target.isdigit() else None
        if member:
            try:
                await self.execute_db(
                    "INSERT INTO safelist (guild_id, type, target_id) VALUES (?, 'user', ?)",
                    (str(ctx.guild.id), str(member.id))
                )
                added = f"user {member.mention}"
            except sqlite3.IntegrityError:
                await ctx.send(embed=create_error("User is already in safelist."))
                return

        # Try role
        elif target.isdigit():
            role = ctx.guild.get_role(int(target))
            if role:
                try:
                    await self.execute_db(
                        "INSERT INTO safelist (guild_id, type, target_id) VALUES (?, 'role', ?)",
                        (str(ctx.guild.id), str(role.id))
                    )
                    added = f"role {role.mention}"
                except sqlite3.IntegrityError:
                    await ctx.send(embed=create_error("Role is already in safelist."))
                    return

        # Try by name
        elif not target.isdigit():
            role = discord.utils.get(ctx.guild.roles, name=target)
            if role:
                try:
                    await self.execute_db(
                        "INSERT INTO safelist (guild_id, type, target_id) VALUES (?, 'role', ?)",
                        (str(ctx.guild.id), str(role.id))
                    )
                    added = f"role {role.mention}"
                except sqlite3.IntegrityError:
                    await ctx.send(embed=create_error("Role is already in safelist."))
                    return

        if added:
            await ctx.send(embed=create_success("Safelist Updated", f"✅ Added {added} to safelist."))
            await self.log(ctx.guild, create_mod_embed("Safelist", f"{ctx.author} added {added} to safelist."))
        else:
            await ctx.send(embed=create_error("❌ Could not add target to safelist.\nMake sure you mention a valid user or role."))

    @safelist_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def safelist_remove(self, ctx, *, target: str):
        target = target.strip().replace("<", "").replace(">", "").replace("@", "").replace("!", "").replace("&", "")
        removed = None

        # Try to remove by ID (user or role)
        result = await self.execute_db(
            "DELETE FROM safelist WHERE guild_id = ? AND target_id = ?",
            (str(ctx.guild.id), target)
        )
        if result:
            removed = f"ID {target}"

        # Try by role name
        if not removed:
            role = discord.utils.get(ctx.guild.roles, name=target)
            if role:
                result = await self.execute_db(
                    "DELETE FROM safelist WHERE guild_id = ? AND target_id = ?",
                    (str(ctx.guild.id), str(role.id))
                )
                if result:
                    removed = f"role {role.mention}"

        if removed:
            await ctx.send(embed=create_success("Safelist Updated", f"✅ Removed {removed} from safelist."))
            await self.log(ctx.guild, create_mod_embed("Safelist", f"{ctx.author} removed {removed} from safelist."))
        else:
            await ctx.send(embed=create_error("❌ Could not remove target from safelist.\nMake sure you mention a valid user or role."))

    @safelist_group.command(name="list")
    @commands.has_permissions(administrator=True)
    async def safelist_list(self, ctx):
        users = await self.fetchall_db(
            "SELECT target_id FROM safelist WHERE guild_id = ? AND type = 'user'",
            (str(ctx.guild.id),)
        )
        roles = await self.fetchall_db(
            "SELECT target_id FROM safelist WHERE guild_id = ? AND type = 'role'",
            (str(ctx.guild.id),)
        )
        
        lines = []
        for uid in users:
            member = ctx.guild.get_member(int(uid[0]))
            lines.append(f"👤 {member.mention if member else f'User ID: `{uid[0]}`'}")
        for rid in roles:
            role = ctx.guild.get_role(int(rid[0]))
            lines.append(f"🎭 {role.mention if role else f'Role ID: `{rid[0]}`'}")

        if not lines:
            lines = ["(none)"]

        embed = create_mod_embed("Safelist", "\n".join(lines))
        await ctx.send(embed=embed)

    # ----------------- warnings -----------------
    @commands.command(name="warn")
    @staff_only()
    async def warn(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided"):
        if await self.is_protected(ctx.guild, member):
            await ctx.send(embed=create_error("Target is protected by safelist — action denied."))
            return
        
        wid = uuid.uuid4().hex[:8]
        timestamp = datetime.datetime.utcnow().isoformat()
        
        await self.execute_db(
            "INSERT INTO warnings (id, guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (wid, str(ctx.guild.id), str(member.id), str(ctx.author.id), reason, timestamp)
        )
        
        await ctx.send(embed=create_success("User Warned", f"{member.mention} was warned.\nID: `{wid}`\nReason: {reason}"))
        await self.log(ctx.guild, create_mod_embed("Warn", f"{ctx.author} warned {member} (ID: {wid}). Reason: {reason}"))

    @commands.command(name="warnlist")
    @staff_only()
    async def warnlist(self, ctx, member: discord.Member):
        warns = await self.fetchall_db(
            "SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(ctx.guild.id), str(member.id))
        )
        
        if not warns:
            await ctx.send(embed=create_mod_embed("Warnings", f"{member.mention} has no warnings."))
            return
        
        lines = []
        for w in warns:
            mod = ctx.guild.get_member(int(w[1]))
            modname = mod.display_name if mod else w[1]
            lines.append(f"• ID: `{w[0]}` — {w[2]} (by {modname} at {w[3]})")
        
        await ctx.send(embed=create_mod_embed(f"Warnings for {member}", "\n".join(lines)))

    @commands.command(name="removewarn")
    @staff_only()
    async def removewarn(self, ctx, member: discord.Member, warn_id: str):
        result = await self.execute_db(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ? AND id = ?",
            (str(ctx.guild.id), str(member.id), warn_id)
        )
        
        if result:
            await ctx.send(embed=create_success("Warning Removed", f"Removed warn `{warn_id}` from {member.mention}"))
            await self.log(ctx.guild, create_mod_embed("Warn Removed", f"{ctx.author} removed warn `{warn_id}` from {member}."))
        else:
            await ctx.send(embed=create_error("Warn ID not found for that user."))

    @commands.command(name="clearwarns")
    @staff_only()
    async def clearwarns(self, ctx, member: discord.Member):
        result = await self.execute_db(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(ctx.guild.id), str(member.id))
        )
        
        if result:
            await ctx.send(embed=create_success("Warnings Cleared", f"All warnings for {member.mention} have been cleared."))
            await self.log(ctx.guild, create_mod_embed("Warnings Cleared", f"{ctx.author} cleared warnings for {member}."))
        else:
            await ctx.send(embed=create_mod_embed("Warnings", f"{member.mention} has no warnings."))

    # ----------------- notes -----------------
    @commands.command(name="note")
    @staff_only()
    async def note(self, ctx, member: discord.Member, *, note_text: str):
        nid = uuid.uuid4().hex[:8]
        timestamp = datetime.datetime.utcnow().isoformat()
        
        await self.execute_db(
            "INSERT INTO notes (id, guild_id, user_id, author_id, note, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, str(ctx.guild.id), str(member.id), str(ctx.author.id), note_text, timestamp)
        )
        
        await ctx.send(embed=create_success("Note Added", f"Note added to {member.mention} (ID: `{nid}`)."))
        await self.log(ctx.guild, create_mod_embed("Note", f"{ctx.author} added note to {member}: {note_text}"))

    # ----------------- mute/unmute using Discord timeout -----------------
    @commands.command(name="mute")
    @staff_only()
    async def mute(self, ctx, member: discord.Member, duration: Optional[str] = None, *, reason: Optional[str] = "No reason provided"):
        if await self.is_protected(ctx.guild, member):
            await ctx.send(embed=create_error("Target is protected by safelist — action denied."))
            return

        try:
            if duration:
                unit = duration[-1].lower()
                if unit not in UNIT_MULTIPLIERS:
                    await ctx.send(embed=create_error("Invalid duration unit. Use s, m, h, or d."))
                    return
                
                try:
                    amount = int(duration[:-1])
                except ValueError:
                    await ctx.send(embed=create_error("Invalid duration number. Use something like 2h, 30m, 1d."))
                    return
                
                kwargs = {UNIT_MULTIPLIERS[unit]: amount}
                until = discord.utils.utcnow() + datetime.timedelta(**kwargs)
                
                # Cap to Discord max timeout (28 days)
                max_until = discord.utils.utcnow() + datetime.timedelta(days=MAX_MUTE_DAYS)
                if until > max_until:
                    until = max_until
                
                duration_str = f"{amount}{unit}"
            else:
                # Indefinite -> max 28 days
                until = discord.utils.utcnow() + datetime.timedelta(days=MAX_MUTE_DAYS)
                duration_str = "indefinite (max 28 days)"
            
            await member.timeout(until, reason=f"{reason} (by {ctx.author})")
            await ctx.send(embed=create_success(
                "Muted", 
                f"{member.mention} has been timed out.\nReason: {reason}\nDuration: {duration_str}"
            ))
            await self.log(ctx.guild, create_mod_embed(
                "Muted", 
                f"{ctx.author} muted {member} until {until.isoformat()} — Reason: {reason}"
            ))
        
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not mute user: {e}"))

    @commands.command(name="unmute")
    @staff_only()
    async def unmute(self, ctx, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Unmuted by {ctx.author}")
            await ctx.send(embed=create_success("Unmuted", f"{member.mention} has been unmuted."))
            await self.log(ctx.guild, create_mod_embed("Unmuted", f"{ctx.author} removed timeout for {member}."))
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not unmute user: {e}"))

    # ----------------- ban/unban/kick -----------------
    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided"):
        if await self.is_protected(ctx.guild, member):
            await ctx.send(embed=create_error("Target is protected by safelist — action denied."))
            return
        try:
            await member.ban(reason=f"{reason} (by {ctx.author})")
            await ctx.send(embed=create_success("Banned", f"{member} has been banned."))
            await self.log(ctx.guild, create_mod_embed("Ban", f"{ctx.author} banned {member}. Reason: {reason}"))
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not ban member: {e}"))

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str):
        try:
            uid = int(user_id)
        except ValueError:
            await ctx.send(embed=create_error("Invalid user ID."))
            return
        try:
            bans = await ctx.guild.bans()
            for ban_entry in bans:
                if ban_entry.user.id == uid:
                    await ctx.guild.unban(ban_entry.user, reason=f"Unbanned by {ctx.author}")
                    await ctx.send(embed=create_success("Unbanned", f"User {ban_entry.user} has been unbanned."))
                    await self.log(ctx.guild, create_mod_embed("Unban", f"{ctx.author} unbanned {ban_entry.user}."))
                    return
            await ctx.send(embed=create_error("User ID not found in ban list."))
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not unban user: {e}"))

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided"):
        if await self.is_protected(ctx.guild, member):
            await ctx.send(embed=create_error("Target is protected by safelist — action denied."))
            return
        try:
            await member.kick(reason=f"{reason} (by {ctx.author})")
            await ctx.send(embed=create_success("Kicked", f"{member} has been kicked."))
            await self.log(ctx.guild, create_mod_embed("Kick", f"{ctx.author} kicked {member}. Reason: {reason}"))
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not kick member: {e}"))

    # ----------------- jail / unjail -----------------
    @commands.command(name="jail")
    @staff_only()
    async def jail(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided"):
        if await self.is_protected(ctx.guild, member):
            await ctx.send(embed=create_error("Target is protected by safelist — action denied."))
            return
        
        jail_role_id = await self.get_guild_setting(ctx.guild.id, 'jail_role')
        if not jail_role_id:
            await ctx.send(embed=create_error("Jail role not set. Use `!jailrole <role_id>` to set it."))
            return
        
        jail_role = ctx.guild.get_role(int(jail_role_id))
        if not jail_role:
            await ctx.send(embed=create_error("Configured jail role not found on this server. Set it again with `!jailrole`."))
            return
        
        # Save current roles
        prev_roles = [r.id for r in member.roles if r != ctx.guild.default_role]
        import json
        roles_json = json.dumps(prev_roles)
        
        try:
            # remove all roles except @everyone
            roles_to_remove = [r for r in member.roles if r != ctx.guild.default_role]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"Jailed by {ctx.author}: {reason}")
            await member.add_roles(jail_role, reason=f"Jailed by {ctx.author}: {reason}")
        except Exception as e:
            await ctx.send(embed=create_error(f"Failed to jail member: {e}"))
            return
        
        timestamp = datetime.datetime.utcnow().isoformat()
        await self.execute_db(
            "INSERT OR REPLACE INTO jailed_users (user_id, guild_id, roles_json, timestamp, moderator_id, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (str(member.id), str(ctx.guild.id), roles_json, timestamp, str(ctx.author.id), reason)
        )
        
        await ctx.send(embed=create_success("Jailed", f"{member.mention} has been jailed.\nReason: {reason}"))
        await self.log(ctx.guild, create_mod_embed("Jail", f"{ctx.author} jailed {member}. Reason: {reason}"))

    @commands.command(name="unjail")
    @staff_only()
    async def unjail(self, ctx, member: discord.Member):
        result = await self.fetchone_db(
            "SELECT roles_json FROM jailed_users WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        if not result:
            await ctx.send(embed=create_error("This user is not recorded as jailed."))
            return
        
        import json
        prev_role_ids = json.loads(result[0])
        roles_to_restore = []
        for rid in prev_role_ids:
            r = ctx.guild.get_role(int(rid))
            if r:
                roles_to_restore.append(r)
        
        try:
            jail_role_id = await self.get_guild_setting(ctx.guild.id, 'jail_role')
            if jail_role_id:
                jail_r = ctx.guild.get_role(int(jail_role_id))
                if jail_r and jail_r in member.roles:
                    await member.remove_roles(jail_r, reason=f"Unjailed by {ctx.author}")
            if roles_to_restore:
                await member.add_roles(*roles_to_restore, reason=f"Unjailed by {ctx.author}")
        except Exception as e:
            await ctx.send(embed=create_error(f"Failed to unjail member: {e}"))
            return
        
        await self.execute_db(
            "DELETE FROM jailed_users WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        await ctx.send(embed=create_success("Unjailed", f"{member.mention} has been unjailed and roles restored."))
        await self.log(ctx.guild, create_mod_embed("Unjail", f"{ctx.author} unjailed {member}."))

    # ----------------- whois -----------------
    @commands.command(name="whois")
    @staff_only()
    async def whois(self, ctx, member: discord.Member):
        # Check if jailed
        jailed = await self.fetchone_db(
            "SELECT * FROM jailed_users WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        # Count notes and warnings
        notes_count = await self.fetchone_db(
            "SELECT COUNT(*) FROM notes WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        warns_count = await self.fetchone_db(
            "SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        embed = create_mod_embed("Whois", f"Information for {member.mention}")
        embed.add_field(name="Name", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Joined At", value=member.joined_at.isoformat() if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Roles", value=", ".join([r.name for r in member.roles if r != ctx.guild.default_role]) or "(none)", inline=False)
        embed.add_field(name="Jailed", value="Yes" if jailed else "No", inline=True)
        embed.add_field(name="Notes", value=str(notes_count[0]) if notes_count else "0", inline=True)
        embed.add_field(name="Warnings", value=str(warns_count[0]) if warns_count else "0", inline=True)
        await ctx.send(embed=embed)

# ----------------- setup -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))