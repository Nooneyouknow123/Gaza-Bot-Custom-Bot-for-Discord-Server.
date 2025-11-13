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
import aiosqlite
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
    
    async def _setup_db(self):
        """Initialize database with required tables"""
        conn = await aiosqlite.connect(self.db_file)
        c = await conn.cursor()
        
        # Guild settings table
        await c.execute('''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT PRIMARY KEY,
                staff_role TEXT,
                log_channel TEXT,
                jail_role TEXT
            )
        ''')
        
        # Safelist table
        await c.execute('''
            CREATE TABLE IF NOT EXISTS safelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                type TEXT, -- 'user' or 'role'
                target_id TEXT,
                UNIQUE(guild_id, type, target_id)
            )
        ''')
        
        # Warnings table
        await c.execute('''
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
        await c.execute('''
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
        await c.execute('''
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

        # Banned users table
        await c.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id TEXT,
                guild_id TEXT,
                moderator_id TEXT,
                reason TEXT,
                timestamp TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')

        # Kicked users table
        await c.execute('''
            CREATE TABLE IF NOT EXISTS kicked_users (
                user_id TEXT,
                guild_id TEXT,
                moderator_id TEXT,
                reason TEXT,
                timestamp TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')

        
        await conn.commit()
        await conn.close()
    
    async def get_connection(self):
        return await aiosqlite.connect(self.db_file)

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

    async def cog_load(self):
        """Initialize database when cog loads"""
        await self.db._setup_db()

    # ----------------- database helpers -----------------
    
    async def execute_db(self, query: str, params: tuple = ()):
        """Execute a database query asynchronously"""
        conn = await self.db.get_connection()
        try:
            c = await conn.cursor()
            await c.execute(query, params)
            await conn.commit()
            # Get the number of rows affected
            changes = conn.total_changes
            return changes
        finally:
            await conn.close()
    
    async def fetchone_db(self, query: str, params: tuple = ()):
        """Fetch one row from database asynchronously"""
        conn = await self.db.get_connection()
        try:
            c = await conn.cursor()
            await c.execute(query, params)
            result = await c.fetchone()
            return result
        finally:
            await conn.close()
    
    async def fetchall_db(self, query: str, params: tuple = ()):
        """Fetch all rows from database asynchronously"""
        conn = await self.db.get_connection()
        try:
            c = await conn.cursor()
            await c.execute(query, params)
            result = await c.fetchall()
            return result
        finally:
            await conn.close()

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

    async def is_staff(self, member: discord.Member):
        """Basic in-code check for staff: configured staff role OR Manage Messages / Kick Members."""
        # Get the staff role asynchronously
        staff_role_id = await self.get_guild_setting(member.guild.id, 'staff_role')
        
        if staff_role_id:
            staff_role = discord.utils.get(member.roles, id=int(staff_role_id))
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
        async def predicate(ctx):
            if ctx.guild is None:
                raise commands.CheckFailure("This command must be used in a server.")
            cog: ModerationCog = ctx.cog
            if await cog.is_staff(ctx.author):
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
#   -------------------- safelist add ---------------------
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
            except Exception:  # Catch aiosqlite IntegrityError
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
                except Exception:  # Catch aiosqlite IntegrityError
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
                except Exception:  # Catch aiosqlite IntegrityError
                    await ctx.send(embed=create_error("Role is already in safelist."))
                    return

        if added:
            await ctx.send(embed=create_success("Safelist Updated", f"✅ Added {added} to safelist."))
            await self.log(ctx.guild, create_mod_embed("Safelist", f"{ctx.author} added {added} to safelist."))
        else:
            await ctx.send(embed=create_error("❌ Could not add target to safelist.\nMake sure you mention a valid user or role."))
# -----------------------------------------safelist remove ----------------------------------------

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
        if result > 0:  # FIX: Check if rows were actually affected
            removed = f"ID {target}"

        # Try by role name
        if not removed:
            role = discord.utils.get(ctx.guild.roles, name=target)
            if role:
                result = await self.execute_db(
                    "DELETE FROM safelist WHERE guild_id = ? AND target_id = ?",
                    (str(ctx.guild.id), str(role.id))
                )
                if result > 0:  # FIX: Check if rows were actually affected
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

#   --------------------------------------- warning list ----------------------------------------

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

#   --------------------------------------Remove Warning ---------------------------------------

    @commands.command(name="removewarn")
    @staff_only()
    async def removewarn(self, ctx, member: discord.Member, warn_id: str):
        # FIX: Check if the warning exists first
        existing_warn = await self.fetchone_db(
            "SELECT id FROM warnings WHERE guild_id = ? AND user_id = ? AND id = ?",
            (str(ctx.guild.id), str(member.id), warn_id)
        )
        
        if not existing_warn:
            await ctx.send(embed=create_error("Warn ID not found for that user."))
            return
        
        # Delete the warning
        await self.execute_db(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ? AND id = ?",
            (str(ctx.guild.id), str(member.id), warn_id)
        )
        
        await ctx.send(embed=create_success("Warning Removed", f"Removed warn `{warn_id}` from {member.mention}"))
        await self.log(ctx.guild, create_mod_embed("Warn Removed", f"{ctx.author} removed warn `{warn_id}` from {member}."))
       
#   --------------------------------------Clear Warning ---------------------------------------

    @commands.command(name="clearwarns")
    @staff_only()
    async def clearwarns(self, ctx, member: discord.Member):
        # Check if there are any warnings first
        existing_warns = await self.fetchone_db(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(ctx.guild.id), str(member.id))
        )
        
        if not existing_warns or existing_warns[0] == 0:
            await ctx.send(embed=create_mod_embed("Warnings", f"{member.mention} has no warnings."))
            return
        
        result = await self.execute_db(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (str(ctx.guild.id), str(member.id))
        )
        
        if result > 0:
            await ctx.send(embed=create_success("Warnings Cleared", f"All warnings for {member.mention} have been cleared."))
            await self.log(ctx.guild, create_mod_embed("Warnings Cleared", f"{ctx.author} cleared warnings for {member}."))

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
    
    # ----------------- note list -----------------
    @commands.command(name="notelist")
    @staff_only()
    async def notelist(self, ctx, member: discord.Member):
        notes = await self.fetchall_db(
            "SELECT id, author_id, note, timestamp FROM notes WHERE guild_id = ? AND user_id = ?",
            (str(ctx.guild.id), str(member.id))
        )
        
        if not notes:
            await ctx.send(embed=create_mod_embed("Notes", f"{member.mention} has no notes."))
            return
        
        lines = []
        for n in notes:
            author = ctx.guild.get_member(int(n[1]))
            author_name = author.display_name if author else n[1]
            lines.append(f"• ID: `{n[0]}` — {n[2]} (by {author_name} at {n[3]})")
        
        await ctx.send(embed=create_mod_embed(f"Notes for {member}", "\n".join(lines)))
    
    # ----------------- Remove note -----------------
    @commands.command(name="removenote")
    @staff_only()
    async def removenote(self, ctx, member: discord.Member, note_id: str):  # command syntax will be .removenote @user note_id 
        # Check if the note exists first
        existing_note = await self.fetchone_db(
            "SELECT id FROM notes WHERE guild_id = ? AND user_id = ? AND id = ?",
            (str(ctx.guild.id), str(member.id), note_id)
        )
        if not existing_note:
            await ctx.send(embed=create_error("Note ID not found for that user."))
            return
        # Delete the note
        await self.execute_db("DELETE from notes WHERE guild_id = ? AND user_id = ? AND id = ?",
            (str(ctx.guild.id), str(member.id), note_id)
        )
        await ctx.send(embed=create_success("Note Removed", f"Removed note `{note_id}` from {member.mention}"))
        await self.log(ctx.guild, create_mod_embed("Note Removed", f"{ctx.author} removed note `{note_id}` from {member}."))


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

#   -------------------------------- unmute -----------------------------

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
            # Record ban in database
            timestamp = datetime.datetime.utcnow().isoformat()
            await self.execute_db(
                "INSERT INTO banned_users (user_id, guild_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
                (str(member.id), str(ctx.guild.id), str(ctx.author.id), reason, timestamp)
            )
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not ban member: {e}"))

# -------------------unban ------------------------------------------------

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

# ------------------------------------------- kick --------------------------------

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
            # Record kick in database
            timestamp = datetime.datetime.utcnow().isoformat()
            await self.execute_db(
                "INSERT INTO kicked_users (user_id, guild_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
                (str(member.id), str(ctx.guild.id), str(ctx.author.id), reason, timestamp)
            )
        except Exception as e:
            await ctx.send(embed=create_error(f"Could not kick member: {e}"))

# ------------------------------------ whois ---------------------------------------

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
        
        # Get ban record with details
        banned_record = await self.fetchone_db(
            "SELECT moderator_id, reason, timestamp FROM banned_users WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        # Get kick record with details
        kicked_record = await self.fetchone_db(
            "SELECT moderator_id, reason, timestamp FROM kicked_users WHERE user_id = ? AND guild_id = ?",
            (str(member.id), str(ctx.guild.id))
        )
        
        # Check if user is currently banned from the guild
        try:
            ban_entry = await ctx.guild.fetch_ban(member)
            currently_banned = True
            ban_reason = ban_entry.reason or "No reason provided"
        except discord.NotFound:
            currently_banned = False
            ban_reason = None
        
        embed = create_mod_embed("Whois", f"Information for {member.mention}")
        embed.add_field(name="Name", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Roles", value=", ".join([r.name for r in member.roles if r != ctx.guild.default_role]) or "(none)", inline=False)
        
        # Moderation history section
        embed.add_field(name="🔒 Moderation History", value="\u200b", inline=False)
        embed.add_field(name="Jailed", value="Yes" if jailed else "No", inline=True)
        embed.add_field(name="Currently Banned", value="Yes" if currently_banned else "No", inline=True)
        embed.add_field(name="Ban Records", value="1" if banned_record else "0", inline=True)
        embed.add_field(name="Kick Records", value="1" if kicked_record else "0", inline=True)
        embed.add_field(name="Notes", value=str(notes_count[0]) if notes_count else "0", inline=True)
        embed.add_field(name="Warnings", value=str(warns_count[0]) if warns_count else "0", inline=True)
        
        # Add detailed ban information if available
        if banned_record:
            mod_id = banned_record[0]
            reason = banned_record[1] or "No reason provided"
            timestamp = banned_record[2]
            embed.add_field(name="Last Ban", value=f"By: <@{mod_id}>\nWhen: {timestamp}\nReason: {reason}", inline=False)
        
        # Add detailed kick information if available
        if kicked_record:
            mod_id = kicked_record[0]
            reason = kicked_record[1] or "No reason provided"
            timestamp = kicked_record[2]
            embed.add_field(name="Last Kick", value=f"By: <@{mod_id}>\nWhen: {timestamp}\nReason: {reason}", inline=False)
        
        # Add current ban reason if applicable
        if currently_banned and ban_reason:
            embed.add_field(name="Current Ban Reason", value=ban_reason, inline=False)
        
        await ctx.send(embed=embed)

# ----------------- setup -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))