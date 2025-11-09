# moderation_cog.py
# Moderation Cog (discord.py v2)
# Features:
#  - Prefix commands 
#  - Warnings (add/list/remove/clear)
#  - Notes for staff
#  - Safelist (users & roles protected)
#  - Jail role config + jail/unjail (stores/restores roles)
#  - Mute/unmute using Discord's built-in timeout (Member.edit(timeout=...))
#  - Ban/unban/kick
#  - JSON persistence per-guild
# Requirements: discord.py v2.x
# Usage: put in cogs folder and load as an extension

import discord
from discord.ext import commands, tasks
import json
import os
import datetime
import uuid
import asyncio
from typing import Optional
from typing import Optional

UNIT_MULTIPLIERS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days"
    }

MAX_MUTE_DAYS = 28  # Discord maximum timeout




DATA_FILE = "moderation_data.json"  # saved relative to working dir




def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def ensure_guild(data, guild_id):
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {
            "staff_role": None,
            "log_channel": None,
            "jail_role": None,
            "safelist": {"users": [], "roles": []},
            "warnings": {},   # user_id -> list of warns
            "notes": {},      # user_id -> list of notes
            "jailed": {},     # user_id -> {roles: [ids], time, moderator, reason}
        }
    return data[gid]


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
        self.data = load_data()
        self._save_lock = asyncio.Lock()

    # ----------------- helpers -----------------
    async def save(self):
        async with self._save_lock:
            save_data(self.data)

    def guild_conf(self, guild_id):
        return ensure_guild(self.data, guild_id)

    def is_staff(self, member: discord.Member):
        """Basic in-code check for staff: configured staff role OR Manage Messages / Kick Members."""
        g = self.guild_conf(member.guild.id)
        staff_role = g.get("staff_role")
        if staff_role:
            role = discord.utils.get(member.roles, id=int(staff_role))
            if role:
                return True
        # fallback on permissions
        perms = member.guild_permissions
        return perms.manage_messages or perms.kick_members or perms.ban_members

    async def is_protected(self, guild: discord.Guild, target: discord.Member):
        g = self.guild_conf(guild.id)
        safelist = g.get("safelist", {"users": [], "roles": []})
        if str(target.id) in safelist.get("users", []):
            return True
        target_role_ids = {str(r.id) for r in target.roles}
        for rid in safelist.get("roles", []):
            if str(rid) in target_role_ids:
                return True
        return False

    async def log(self, guild: discord.Guild, embed: discord.Embed):
        g = self.guild_conf(guild.id)
        chan_id = g.get("log_channel")
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
        g = self.guild_conf(ctx.guild.id)
        g["staff_role"] = str(role.id)
        await self.save()
        await ctx.send(embed=create_success("Staff Role Set", f"Staff role set to {role.mention}"))
        await self.log(ctx.guild, create_mod_embed("Config", f"Staff role set to {role.name} ({role.id}) by {ctx.author}"))

    @commands.command(name="setlogchannel")
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        g = self.guild_conf(ctx.guild.id)
        g["log_channel"] = str(channel.id)
        await self.save()
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
        g = self.guild_conf(ctx.guild.id)
        g["jail_role"] = str(role.id)
        await self.save()
        await ctx.send(embed=create_success("Jail Role Set", f"Jail role set to {role.mention}"))
        await self.log(ctx.guild, create_mod_embed("Config", f"Jail role set to {role.name} ({role.id}) by {ctx.author}"))

    @commands.command(name="config")
    @staff_only()
    async def show_config(self, ctx):
        g = self.guild_conf(ctx.guild.id)
        staff = f"<not set>" if not g.get("staff_role") else f"<@&{g.get('staff_role')}>"
        logc = f"<not set>" if not g.get("log_channel") else f"<#{g.get('log_channel')}>"
        jail = f"<not set>" if not g.get("jail_role") else f"<@&{g.get('jail_role')}>"
        safelist = g.get("safelist", {"users": [], "roles": []})
        users = safelist.get("users", [])
        roles = safelist.get("roles", [])
        embed = create_mod_embed("Server Config", f"Staff role: {staff}\nLog channel: {logc}\nJail role: {jail}")
        embed.add_field(name="Safelist - Users", value=", ".join(users) if users else "(none)", inline=False)
        embed.add_field(name="Safelist - Roles", value=", ".join(roles) if roles else "(none)", inline=False)
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

    def ensure_safelist(self, guild_id):
        g = self.guild_conf(guild_id)
        if "safelist" not in g:
            g["safelist"] = {"users": [], "roles": []}
        return g

    @safelist_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def safelist_add(self, ctx, *, target: str):
        g = self.ensure_safelist(ctx.guild.id)
        users = g["safelist"]["users"]
        roles = g["safelist"]["roles"]
        added = None

        target = target.strip().replace("<", "").replace(">", "").replace("@", "").replace("!", "").replace("&", "")

        # Try member
        member = ctx.guild.get_member(int(target)) if target.isdigit() else None
        if member and str(member.id) not in users:
            users.append(str(member.id))
            added = f"user {member.mention}"

        # Try role
        elif target.isdigit():
            role = ctx.guild.get_role(int(target))
            if role and str(role.id) not in roles:
                roles.append(str(role.id))
                added = f"role {role.mention}"

        # Try by name
        elif not target.isdigit():
            role = discord.utils.get(ctx.guild.roles, name=target)
            if role and str(role.id) not in roles:
                roles.append(str(role.id))
                added = f"role {role.mention}"

        await self.save()
        if added:
            await ctx.send(embed=create_success("Safelist Updated", f"✅ Added {added} to safelist."))
            await self.log(ctx.guild, create_mod_embed("Safelist", f"{ctx.author} added {added} to safelist."))
        else:
            await ctx.send(embed=create_error("❌ Could not add target to safelist.\nMake sure you mention a valid user or role."))

    @safelist_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def safelist_remove(self, ctx, *, target: str):
        g = self.ensure_safelist(ctx.guild.id)
        users = g["safelist"]["users"]
        roles = g["safelist"]["roles"]
        removed = None

        target = target.strip().replace("<", "").replace(">", "").replace("@", "").replace("!", "").replace("&", "")

        if target in users:
            users.remove(target)
            removed = f"user id {target}"
        elif target in roles:
            roles.remove(target)
            removed = f"role id {target}"
        else:
            role = discord.utils.get(ctx.guild.roles, name=target)
            if role and str(role.id) in roles:
                roles.remove(str(role.id))
                removed = f"role {role.mention}"

        await self.save()
        if removed:
            await ctx.send(embed=create_success("Safelist Updated", f"✅ Removed {removed} from safelist."))
            await self.log(ctx.guild, create_mod_embed("Safelist", f"{ctx.author} removed {removed} from safelist."))
        else:
            await ctx.send(embed=create_error("❌ Could not remove target from safelist.\nMake sure you mention a valid user or role."))

    @safelist_group.command(name="list")
    @commands.has_permissions(administrator=True)
    async def safelist_list(self, ctx):
        g = self.ensure_safelist(ctx.guild.id)
        users = g["safelist"]["users"]
        roles = g["safelist"]["roles"]
        lines = []

        if users:
            for uid in users:
                member = ctx.guild.get_member(int(uid))
                lines.append(f"👤 {member.mention if member else f'User ID: `{uid}`'}")
        if roles:
            for rid in roles:
                role = ctx.guild.get_role(int(rid))
                lines.append(f"🎭 {role.mention if role else f'Role ID: `{rid}`'}")

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
        g = self.guild_conf(ctx.guild.id)
        warns = g.setdefault("warnings", {})
        user_warns = warns.setdefault(str(member.id), [])
        wid = uuid.uuid4().hex[:8]
        entry = {"id": wid, "moderator": str(ctx.author.id), "reason": reason, "time": datetime.datetime.utcnow().isoformat()}
        user_warns.append(entry)
        await self.save()
        await ctx.send(embed=create_success("User Warned", f"{member.mention} was warned.\nID: `{wid}`\nReason: {reason}"))
        await self.log(ctx.guild, create_mod_embed("Warn", f"{ctx.author} warned {member} (ID: {wid}). Reason: {reason}"))

    @commands.command(name="warnlist")
    @staff_only()
    async def warnlist(self, ctx, member: discord.Member):
        g = self.guild_conf(ctx.guild.id)
        warns = g.get("warnings", {}).get(str(member.id), [])
        if not warns:
            await ctx.send(embed=create_mod_embed("Warnings", f"{member.mention} has no warnings."))
            return
        lines = []
        for w in warns:
            mod = ctx.guild.get_member(int(w["moderator"]))
            modname = mod.display_name if mod else w["moderator"]
            lines.append(f"• ID: `{w['id']}` — {w['reason']} (by {modname} at {w['time']})")
        await ctx.send(embed=create_mod_embed(f"Warnings for {member}", "\n".join(lines)))

    @commands.command(name="removewarn")
    @staff_only()
    async def removewarn(self, ctx, member: discord.Member, warn_id: str):
        g = self.guild_conf(ctx.guild.id)
        warns = g.get("warnings", {}).get(str(member.id), [])
        for w in warns:
            if w["id"] == warn_id:
                warns.remove(w)
                await self.save()
                await ctx.send(embed=create_success("Warning Removed", f"Removed warn `{warn_id}` from {member.mention}"))
                await self.log(ctx.guild, create_mod_embed("Warn Removed", f"{ctx.author} removed warn `{warn_id}` from {member}."))
                return
        await ctx.send(embed=create_error("Warn ID not found for that user."))

    @commands.command(name="clearwarns")
    @staff_only()
    async def clearwarns(self, ctx, member: discord.Member):
        g = self.guild_conf(ctx.guild.id)
        if str(member.id) in g.get("warnings", {}):
            g["warnings"].pop(str(member.id), None)
            await self.save()
            await ctx.send(embed=create_success("Warnings Cleared", f"All warnings for {member.mention} have been cleared."))
            await self.log(ctx.guild, create_mod_embed("Warnings Cleared", f"{ctx.author} cleared warnings for {member}."))
        else:
            await ctx.send(embed=create_mod_embed("Warnings", f"{member.mention} has no warnings."))

    # ----------------- notes -----------------
    @commands.command(name="note")
    @staff_only()
    async def note(self, ctx, member: discord.Member, *, note_text: str):
        g = self.guild_conf(ctx.guild.id)
        notes = g.setdefault("notes", {})
        user_notes = notes.setdefault(str(member.id), [])
        nid = uuid.uuid4().hex[:8]
        entry = {"id": nid, "author": str(ctx.author.id), "note": note_text, "time": datetime.datetime.utcnow().isoformat()}
        user_notes.append(entry)
        await self.save()
        await ctx.send(embed=create_success("Note Added", f"Note added to {member.mention} (ID: `{nid}`)."))
        await self.log(ctx.guild, create_mod_embed("Note", f"{ctx.author} added note to {member}: {note_text}"))

    # ----------------- mute/unmute using Discord timeout -----------------
    import datetime

    

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
        g = self.guild_conf(ctx.guild.id)
        jail_role_id = g.get("jail_role")
        if not jail_role_id:
            await ctx.send(embed=create_error("Jail role not set. Use `!jailrole <role_id>` to set it."))
            return
        jail_role = ctx.guild.get_role(int(jail_role_id))
        if not jail_role:
            await ctx.send(embed=create_error("Configured jail role not found on this server. Set it again with `!jailrole`."))
            return
        # Save current roles
        prev_roles = [r.id for r in member.roles if r != ctx.guild.default_role]
        try:
            # remove all roles except @everyone
            roles_to_remove = [r for r in member.roles if r != ctx.guild.default_role]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"Jailed by {ctx.author}: {reason}")
            await member.add_roles(jail_role, reason=f"Jailed by {ctx.author}: {reason}")
        except Exception as e:
            await ctx.send(embed=create_error(f"Failed to jail member: {e}"))
            return
        g.setdefault("jailed", {})[str(member.id)] = {
            "roles": prev_roles,
            "time": datetime.datetime.utcnow().isoformat(),
            "moderator": str(ctx.author.id),
            "reason": reason
        }
        await self.save()
        await ctx.send(embed=create_success("Jailed", f"{member.mention} has been jailed.\nReason: {reason}"))
        await self.log(ctx.guild, create_mod_embed("Jail", f"{ctx.author} jailed {member}. Reason: {reason}"))

    @commands.command(name="unjail")
    @staff_only()
    async def unjail(self, ctx, member: discord.Member):
        g = self.guild_conf(ctx.guild.id)
        jailed = g.get("jailed", {})
        entry = jailed.get(str(member.id))
        if not entry:
            await ctx.send(embed=create_error("This user is not recorded as jailed."))
            return
        prev_role_ids = entry.get("roles", [])
        roles_to_restore = []
        for rid in prev_role_ids:
            r = ctx.guild.get_role(int(rid))
            if r:
                roles_to_restore.append(r)
        try:
            jail_role_id = g.get("jail_role")
            if jail_role_id:
                jail_r = ctx.guild.get_role(int(jail_role_id))
                if jail_r and jail_r in member.roles:
                    await member.remove_roles(jail_r, reason=f"Unjailed by {ctx.author}")
            if roles_to_restore:
                await member.add_roles(*roles_to_restore, reason=f"Unjailed by {ctx.author}")
        except Exception as e:
            await ctx.send(embed=create_error(f"Failed to unjail member: {e}"))
            return
        g["jailed"].pop(str(member.id), None)
        await self.save()
        await ctx.send(embed=create_success("Unjailed", f"{member.mention} has been unjailed and roles restored."))
        await self.log(ctx.guild, create_mod_embed("Unjail", f"{ctx.author} unjailed {member}."))

    # ----------------- whois -----------------
    @commands.command(name="whois")
    @staff_only()
    async def whois(self, ctx, member: discord.Member):
        g = self.guild_conf(ctx.guild.id)
        jailed = g.get("jailed", {}).get(str(member.id))
        notes = g.get("notes", {}).get(str(member.id), [])
        warns = g.get("warnings", {}).get(str(member.id), [])
        embed = create_mod_embed("Whois", f"Information for {member.mention}")
        embed.add_field(name="Name", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Joined At", value=member.joined_at.isoformat() if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Roles", value=", ".join([r.name for r in member.roles if r != ctx.guild.default_role]) or "(none)", inline=False)
        embed.add_field(name="Jailed", value="Yes" if jailed else "No", inline=True)
        embed.add_field(name="Notes", value=str(len(notes)), inline=True)
        embed.add_field(name="Warnings", value=str(len(warns)), inline=True)
        await ctx.send(embed=embed)

    
    # ----------------- cog unload/save on shutdown -----------------
    def cog_unload(self):
        # save data on unload
        try:
            save_data(self.data)
        except Exception:
            pass


# ----------------- setup -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))