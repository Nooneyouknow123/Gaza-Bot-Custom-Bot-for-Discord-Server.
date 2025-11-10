# jail_cog.py

# Jail + Appeal Ticket System

import discord

from discord.ext import commands

from discord.ui import View, Button

import asyncio

import sqlite3

import os

import datetime

import json

from typing import Optional

DB_FILE = "jail_system.db"

DEFAULT_CATEGORY_NAME = "🔒 Jail"

APPEALS_CHANNEL_NAME = "appeals"

ADMIN_CHANNEL_NAME = "jail-admins"

JAILED_ROLE_NAME = "Jailed"

TICKET_PREFIX = "appeal-"

APPEAL_PROMPT_TIMEOUT = 600  # seconds

TRANSCRIPT_TEMP_DIR = "transcripts"

BLURPLE = discord.Color.blurple()

def now_iso():

    return datetime.datetime.utcnow().isoformat()

def pretty_ts(dt: Optional[datetime.datetime] = None):

    dt = dt or datetime.datetime.utcnow()

    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

class CreateAppealView(View):

    def __init__(self, cog):

        super().__init__(timeout=None)

        self.cog = cog

        self.add_item(Button(label="📩 Create Appeal", style=discord.ButtonStyle.primary, custom_id="create_appeal"))

class TicketActionView(View):

    def __init__(self, cog):

        super().__init__(timeout=None)

        self.cog = cog

        self.add_item(Button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="ticket_approve"))

        self.add_item(Button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="ticket_deny"))

        self.add_item(Button(label="🔒 Close", style=discord.ButtonStyle.secondary, custom_id="ticket_close"))

class JailCog(commands.Cog):

    def __init__(self, bot: commands.Bot):

        self.bot = bot

        os.makedirs(TRANSCRIPT_TEMP_DIR, exist_ok=True)

        self._ensure_db()

        self.ticket_channel_cache = set()

        self._load_open_tickets()

    # DB helpers

    def _ensure_db(self):

        self.conn = sqlite3.connect(DB_FILE)

        self.conn.row_factory = sqlite3.Row

        c = self.conn.cursor()

        c.execute("""

        CREATE TABLE IF NOT EXISTS guild_config (

            guild_id INTEGER PRIMARY KEY,

            jail_role INTEGER,

            jail_category INTEGER,

            appeals_channel INTEGER,

            admin_channel INTEGER,

            admin_role INTEGER

        )

        """)

        c.execute("""

        CREATE TABLE IF NOT EXISTS jailed_users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER,

            user_id INTEGER,

            reason TEXT,

            previous_roles TEXT,

            jailed_at TEXT

        )

        """)

        c.execute("""

        CREATE TABLE IF NOT EXISTS appeals (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER,

            ticket_channel_id INTEGER,

            user_id INTEGER,

            reason TEXT,

            status TEXT,

            created_at TEXT,

            closed_at TEXT,

            transcript TEXT

        )

        """)

        self.conn.commit()

    def _load_open_tickets(self):

        c = self.conn.cursor()

        c.execute("SELECT ticket_channel_id FROM appeals WHERE status = 'open'")

        rows = c.fetchall()

        for r in rows:

            if r["ticket_channel_id"]:

                self.ticket_channel_cache.add(r["ticket_channel_id"])

    def _save_guild_config(self, guild_id, **kwargs):

        c = self.conn.cursor()

        existing = c.execute("SELECT 1 FROM guild_config WHERE guild_id = ?", (guild_id,)).fetchone()

        if existing:

            fields = ", ".join(f"{k} = ?" for k in kwargs.keys())

            values = list(kwargs.values()) + [guild_id]

            c.execute(f"UPDATE guild_config SET {fields} WHERE guild_id = ?", values)

        else:

            keys = ["jail_role", "jail_category", "appeals_channel", "admin_channel", "admin_role"]

            vals = [kwargs.get(k) for k in keys]

            c.execute("INSERT INTO guild_config (guild_id, jail_role, jail_category, appeals_channel, admin_channel, admin_role) VALUES (?,?,?,?,?,?)", [guild_id] + vals)

        self.conn.commit()

    def _get_guild_config(self, guild_id):

        c = self.conn.cursor()

        r = c.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)).fetchone()

        return dict(r) if r else None

    def _add_jailed_user(self, guild_id, user_id, reason, previous_roles):

        c = self.conn.cursor()

        c.execute("INSERT INTO jailed_users (guild_id, user_id, reason, previous_roles, jailed_at) VALUES (?,?,?,?,?)", (guild_id, user_id, reason, json.dumps(previous_roles), now_iso()))

        self.conn.commit()

    def _remove_jailed_user(self, guild_id, user_id):

        c = self.conn.cursor()

        c.execute("DELETE FROM jailed_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

        self.conn.commit()

    def _get_jailed_user(self, guild_id, user_id):

        c = self.conn.cursor()

        r = c.execute("SELECT * FROM jailed_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()

        return dict(r) if r else None

    def _create_appeal(self, guild_id, ticket_channel_id, user_id, reason):

        c = self.conn.cursor()

        c.execute("INSERT INTO appeals (guild_id, ticket_channel_id, user_id, reason, status, created_at) VALUES (?,?,?,?,?,?)", (guild_id, ticket_channel_id, user_id, reason, "open", now_iso()))

        self.conn.commit()

        aid = c.lastrowid

        self.ticket_channel_cache.add(ticket_channel_id)

        return aid

    def _close_appeal(self, ticket_channel_id, status, transcript_text):

        c = self.conn.cursor()

        c.execute("UPDATE appeals SET status = ?, transcript = ?, closed_at = ? WHERE ticket_channel_id = ?", (status, transcript_text, now_iso(), ticket_channel_id))

        self.conn.commit()

        try:

            self.ticket_channel_cache.discard(ticket_channel_id)

        except Exception:

            pass

    def _get_appeals_for_user(self, guild_id, user_id, limit=10):

        c = self.conn.cursor()

        rows = c.execute("SELECT * FROM appeals WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?", (guild_id, user_id, limit)).fetchall()

        return [dict(r) for r in rows]

    # Logging helper (calls LogsCog)

    async def _log_mod(self, guild: discord.Guild, *, embed: discord.Embed = None, file: discord.File = None, content: str = None):

        logs_cog = self.bot.get_cog("LogsCog")

        if logs_cog:

            try:

                await logs_cog.log(guild, "mod", embed=embed, file=file, content=content)

            except Exception:

                pass

    async def _make_transcript_file(self, channel: discord.TextChannel, member_id: int, appeal_id: int) -> str:

        safe_member = str(member_id)

        filename = os.path.join(TRANSCRIPT_TEMP_DIR, f"transcript_{safe_member}_{appeal_id}.txt")

        lines = []

        async for m in channel.history(limit=1000, oldest_first=True):

            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

            content = m.content or ""

            lines.append(f"[{ts}] {m.author} ({m.author.id}): {content}")

        with open(filename, "w", encoding="utf-8") as f:

            f.write("\n".join(lines))

        return filename

    # ---------- commands ----------

    @commands.command(name="setupjail")

    @commands.has_permissions(administrator=True)

    async def setup_jail(self, ctx):

        guild = ctx.guild

        # create or get jailed role

        jail_role = discord.utils.get(guild.roles, name=JAILED_ROLE_NAME)

        if not jail_role:

            try:

                jail_role = await guild.create_role(name=JAILED_ROLE_NAME, reason="Jail setup by bot")

            except Exception as e:

                await ctx.send(embed=discord.Embed(title="Error", description=f"Could not create role: {e}", color=discord.Color.red()))

                return

        # create category

        category = discord.utils.get(guild.categories, name=DEFAULT_CATEGORY_NAME)

        if not category:

            try:

                category = await guild.create_category(DEFAULT_CATEGORY_NAME, reason="Jail setup by bot")

            except Exception as e:

                await ctx.send(embed=discord.Embed(title="Error", description=f"Could not create category: {e}", color=discord.Color.red()))

                return

        # appeals/admin channel

        appeals_chan = discord.utils.get(guild.text_channels, name=APPEALS_CHANNEL_NAME)

        if not appeals_chan:

            overwrites = {

                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),

                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)

            }

            try:

                appeals_chan = await guild.create_text_channel(APPEALS_CHANNEL_NAME, category=category, overwrites=overwrites, reason="Jail setup appeals channel")

            except Exception as e:

                await ctx.send(embed=discord.Embed(title="Error", description=f"Could not create appeals channel: {e}", color=discord.Color.red()))

                return

        admin_chan = discord.utils.get(guild.text_channels, name=ADMIN_CHANNEL_NAME)

        if not admin_chan:

            overwrites = {

                guild.default_role: discord.PermissionOverwrite(read_messages=False),

                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)

            }

            try:

                admin_chan = await guild.create_text_channel(ADMIN_CHANNEL_NAME, category=category, overwrites=overwrites, reason="Jail setup admin channel")

            except Exception as e:

                await ctx.send(embed=discord.Embed(title="Error", description=f"Could not create admin channel: {e}", color=discord.Color.red()))

                return

        # save config

        self._save_guild_config(guild.id, jail_role=jail_role.id, jail_category=category.id, appeals_channel=appeals_chan.id, admin_channel=admin_chan.id)

        # post switch/button

        embed = discord.Embed(title="📩 Appeals", description="If you are jailed and want to appeal, click **Create Appeal** below and follow the instructions.", color=BLURPLE, timestamp=datetime.datetime.utcnow())

        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)

        embed.set_footer(text="Appeal system • Click the button to start")

        view = CreateAppealView(self)

        try:

            async for m in appeals_chan.history(limit=50):

                if m.author == guild.me and m.embeds:

                    try:

                        await m.delete()

                    except Exception:

                        pass

            await appeals_chan.send(embed=embed, view=view)

        except Exception:

            pass

        # log via LogsCog

        le = discord.Embed(title="🛠️ Jail System Setup", description=f"Jail system created by {ctx.author.mention}", color=BLURPLE, timestamp=datetime.datetime.utcnow())

        le.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)

        le.add_field(name="Jail Role", value=jail_role.mention)

        le.add_field(name="Appeals Channel", value=appeals_chan.mention)

        le.add_field(name="Admin Channel", value=admin_chan.mention)

        le.set_footer(text=f"Setup at {pretty_ts()}")

        await self._log_mod(guild, embed=le)

        await ctx.send(embed=discord.Embed(title="Jail system", description="Setup complete. Appeals button posted.", color=discord.Color.green()))

    @commands.command(name="setjailadmins")

    @commands.has_permissions(administrator=True)

    async def set_jail_admins(self, ctx, role: discord.Role):

        guild = ctx.guild

        cfg = self._get_guild_config(guild.id) or {}

        self._save_guild_config(guild.id, jail_role=cfg.get("jail_role"), jail_category=cfg.get("jail_category"), appeals_channel=cfg.get("appeals_channel"), admin_channel=cfg.get("admin_channel"), admin_role=role.id)

        await ctx.send(embed=discord.Embed(title="Jail Admins Set", description=f"Role {role.mention} set as jail admins.", color=discord.Color.green()))

        le = discord.Embed(title="👮 Jail Admin Role Updated", description=f"{role.mention} set as jail admins by {ctx.author.mention}", color=BLURPLE, timestamp=datetime.datetime.utcnow())

        le.set_footer(text=pretty_ts())

        await self._log_mod(guild, embed=le)

    @commands.command(name="jail")

    @commands.has_permissions(manage_roles=True)

    async def cmd_jail(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided"):

        guild = ctx.guild

        cfg = self._get_guild_config(guild.id)

        if not cfg or not cfg.get("jail_role"):

            await ctx.send(embed=discord.Embed(title="Not configured", description="Use .setupjail first.", color=discord.Color.red()))

            return

        jail_role = guild.get_role(int(cfg["jail_role"]))

        if not jail_role:

            await ctx.send(embed=discord.Embed(title="Missing role", description="Configured jail role not found. Re-run setup.", color=discord.Color.red()))

            return

        if jail_role in member.roles:

            await ctx.send(embed=discord.Embed(title="Already jailed", description=f"{member.mention} is already jailed.", color=discord.Color.orange()))

            return

        previous_roles = [r.id for r in member.roles if r != guild.default_role and r != jail_role]

        self._add_jailed_user(guild.id, member.id, reason, previous_roles)

        roles_to_remove = [r for r in member.roles if r != guild.default_role and r != jail_role]

        try:

            if roles_to_remove:

                await member.remove_roles(*roles_to_remove, reason=f"Jailed by {ctx.author}: {reason}")

            await member.add_roles(jail_role, reason=f"Jailed by {ctx.author}: {reason}")

        except Exception as e:

            await ctx.send(embed=discord.Embed(title="Action failed", description=f"Could not modify roles: {e}", color=discord.Color.red()))

            return

        await ctx.send(embed=discord.Embed(title="User jailed", description=f"{member.mention} was jailed.\nReason: {reason}", color=discord.Color.green()))

        embed = discord.Embed(title="🔒 User Jailed", description=f"{member.mention} (`{member.id}`)\nBy: {ctx.author.mention}\nReason: {reason}", color=BLURPLE, timestamp=datetime.datetime.utcnow())

        embed.set_footer(text=f"Action at {pretty_ts()}")

        await self._log_mod(guild, embed=embed)

        try:

            await member.send(f"You were jailed in {guild.name} by {ctx.author}. Reason: {reason}")

        except Exception:

            pass

    @commands.command(name="unjail")

    @commands.has_permissions(manage_roles=True)

    async def cmd_unjail(self, ctx, member: discord.Member):

        guild = ctx.guild

        cfg = self._get_guild_config(guild.id)

        if not cfg or not cfg.get("jail_role"):

            await ctx.send(embed=discord.Embed(title="Not configured", description="Use .setupjail first.", color=discord.Color.red()))

            return

        jail_role = guild.get_role(int(cfg["jail_role"]))

        jailed = self._get_jailed_user(guild.id, member.id)

        if not jailed:

            await ctx.send(embed=discord.Embed(title="Not jailed", description="This user is not recorded as jailed.", color=discord.Color.orange()))

            return

        prev_roles = json.loads(jailed["previous_roles"]) if jailed["previous_roles"] else []

        roles_objs = []

        for rid in prev_roles:

            try:

                r = guild.get_role(int(rid))

                if r:

                    roles_objs.append(r)

            except Exception:

                pass

        try:

            if jail_role and jail_role in member.roles:

                await member.remove_roles(jail_role, reason=f"Unjailed by {ctx.author}")

            if roles_objs:

                await member.add_roles(*roles_objs, reason=f"Unjailed by {ctx.author}")

        except Exception as e:

            await ctx.send(embed=discord.Embed(title="Action failed", description=f"Could not restore roles: {e}", color=discord.Color.red()))

            return

        self._remove_jailed_user(guild.id, member.id)

        await ctx.send(embed=discord.Embed(title="User unjailed", description=f"{member.mention} was unjailed and roles restored.", color=discord.Color.green()))

        embed = discord.Embed(title="🔓 User Unjailed", description=f"{member.mention} (`{member.id}`)\nBy: {ctx.author.mention}", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())

        embed.set_footer(text=f"Action at {pretty_ts()}")

        await self._log_mod(guild, embed=embed)

        try:

            await member.send(f"You were unjailed in {guild.name} by {ctx.author}.")

        except Exception:

            pass

    # Interaction listeners (create ticket & handle buttons)

    @commands.Cog.listener()

    async def on_interaction(self, interaction: discord.Interaction):

        try:

            if not interaction.data:

                return

            custom_id = interaction.data.get("custom_id") or interaction.data.get("customId")

            if not custom_id:

                return

            if custom_id == "create_appeal":

                await interaction.response.defer(ephemeral=True)

                guild = interaction.guild

                user = interaction.user

                cfg = self._get_guild_config(guild.id)

                if not cfg or not cfg.get("appeals_channel"):

                    await interaction.followup.send("Appeals not configured.", ephemeral=True)

                    return

                jailed = self._get_jailed_user(guild.id, user.id)

                if not jailed:

                    await interaction.followup.send("You are not jailed and cannot open an appeal.", ephemeral=True)

                    return

                # create channel

                category_id = cfg.get("jail_category")

                category = guild.get_channel(int(category_id)) if category_id else None

                base_name = f"{TICKET_PREFIX}{user.name}".lower().replace(" ", "-")

                final_name = base_name

                suffix = 1

                while discord.utils.get(guild.text_channels, name=final_name):

                    final_name = f"{base_name}-{suffix}"

                    suffix += 1

                overwrites = {

                    guild.default_role: discord.PermissionOverwrite(read_messages=False),

                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),

                    user: discord.PermissionOverwrite(read_messages=True, send_messages=True)

                }

                admin_role_id = cfg.get("admin_role")

                if admin_role_id:

                    ar = guild.get_role(int(admin_role_id))

                    if ar:

                        overwrites[ar] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                try:

                    ticket_chan = await guild.create_text_channel(final_name, category=category, overwrites=overwrites, reason=f"Appeal ticket by {user}")

                except Exception as e:

                    await interaction.followup.send(f"Could not create ticket channel: {e}", ephemeral=True)

                    return

                # prompt for reason

                try:

                    await ticket_chan.send(f"{user.mention}, bitte schreibe hier deinen Appeal-Grund. Du hast {APPEAL_PROMPT_TIMEOUT//60} Minuten.")

                    def check(m): return m.author.id == user.id and m.channel.id == ticket_chan.id

                    msg = await self.bot.wait_for("message", timeout=APPEAL_PROMPT_TIMEOUT, check=check)

                    reason = msg.content.strip() or "No reason provided"

                except asyncio.TimeoutError:

                    try:

                        await ticket_chan.send("Zeit abgelaufen — kein Appeal-Grund erhalten. Ticket wird geschlossen.")

                        await asyncio.sleep(2)

                        await ticket_chan.delete(reason="Appeal prompt timeout")

                    except Exception:

                        pass

                    await interaction.followup.send("Du hast nicht rechtzeitig geantwortet. Ticket geschlossen.", ephemeral=True)

                    return

                appeal_id = self._create_appeal(guild.id, ticket_chan.id, user.id, reason)

                tembed = discord.Embed(title="📝 Appeal Ticket", description=f"**User:** {user.mention}\n**Reason:** {reason}", color=BLURPLE, timestamp=datetime.datetime.utcnow())

                tembed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)

                tembed.add_field(name="Next steps", value="Staff can use ✅ Approve or ❌ Deny. Use the buttons or `.approve` / `.deny <reason>` commands in this channel.", inline=False)

                tembed.set_footer(text=f"Ticket #{appeal_id} • Created at {pretty_ts()}")

                view = TicketActionView(self)

                try:

                    await ticket_chan.send(embed=tembed, view=view)

                except Exception:

                    await ticket_chan.send("Ticket created. Staff will review it shortly.")

                if admin_role_id:

                    ar = guild.get_role(int(admin_role_id))

                    if ar:

                        await ticket_chan.send(f"{ar.mention} New appeal opened by {user.mention}.")

                await interaction.followup.send(f"Dein Appeal wurde erstellt: {ticket_chan.mention}", ephemeral=True)

                le = discord.Embed(title="📬 Appeal Created", description=f"User: {user.mention} (`{user.id}`)\nTicket: {ticket_chan.mention}\nReason: {reason}", color=BLURPLE, timestamp=datetime.datetime.utcnow())

                le.set_footer(text=f"Appeal #{appeal_id} • {pretty_ts()}")

                await self._log_mod(guild, embed=le)

                return

            if custom_id in ("ticket_approve", "ticket_deny", "ticket_close"):

                await interaction.response.defer(ephemeral=True)

                if custom_id == "ticket_approve":

                    await self._handle_button_approve(interaction)

                elif custom_id == "ticket_deny":

                    await self._handle_button_deny(interaction)

                elif custom_id == "ticket_close":

                    await self._handle_button_close(interaction)

                return

        except Exception:

            try:

                await interaction.followup.send("Ein Fehler ist aufgetreten.", ephemeral=True)

            except Exception:

                pass

    # --- button handlers (approve/deny/close) ---

    async def _handle_button_approve(self, interaction: discord.Interaction):

        channel = interaction.channel

        author = interaction.user

        if not self._is_ticket_channel(channel):

            await interaction.followup.send("This is not an appeal ticket.", ephemeral=True)

            return

        if not self._is_jail_admin(author) and not author.guild_permissions.administrator:

            await interaction.followup.send("You don't have permission to approve appeals.", ephemeral=True)

            return

        c = self.conn.cursor()

        rec = c.execute("SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'", (channel.id,)).fetchone()

        if not rec:

            await interaction.followup.send("No open appeal found.", ephemeral=True)

            return

        user_id = rec["user_id"]

        appeal_id = rec["id"]

        guild = interaction.guild

        member = guild.get_member(int(user_id))

        filename = await self._make_transcript_file(channel, user_id, appeal_id)

        jailed = self._get_jailed_user(guild.id, int(user_id))

        if jailed:

            prev = json.loads(jailed["previous_roles"]) if jailed["previous_roles"] else []

            roles_objs = [guild.get_role(rid) for rid in prev if guild.get_role(rid)]

            jail_role_id = self._get_guild_config(guild.id).get("jail_role")

            jail_role = guild.get_role(int(jail_role_id)) if jail_role_id else None

            try:

                if jail_role and member and jail_role in member.roles:

                    await member.remove_roles(jail_role, reason=f"Appeal approved by {author}")

                if member and roles_objs:

                    await member.add_roles(*roles_objs, reason=f"Appeal approved by {author}")

            except Exception:

                pass

            self._remove_jailed_user(guild.id, int(user_id))

        try:

            with open(filename, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "[Could not read transcript file]"

        self._close_appeal(channel.id, "approved", transcript_text)

        embed = discord.Embed(title="✅ Appeal Approved", description=f"By: {author.mention}\nUser: <@{user_id}>", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())

        embed.add_field(name="Appeal ID", value=str(appeal_id), inline=True)

        embed.add_field(name="Channel", value=channel.mention, inline=True)

        embed.set_footer(text=f"Approved at {pretty_ts()}")

        try:

            dfile = discord.File(filename, filename=os.path.basename(filename))

            await self._log_mod(guild, embed=embed, file=dfile)

        except Exception:

            await self._log_mod(guild, embed=embed)

        try:

            os.remove(filename)

        except Exception:

            pass

        try:

            if member:

                await member.send(f"Your appeal in {guild.name} was APPROVED by {author}.")

        except Exception:

            pass

        try:

            await channel.send(embed=discord.Embed(title="Appeal approved — closing ticket...", color=discord.Color.green()))

            await asyncio.sleep(2)

            await channel.delete(reason=f"Appeal approved by {author}")

        except Exception:

            pass

        try:

            await interaction.followup.send("Appeal approved.", ephemeral=True)

        except Exception:

            pass

    async def _handle_button_deny(self, interaction: discord.Interaction):

        channel = interaction.channel

        author = interaction.user

        if not self._is_ticket_channel(channel):

            await interaction.followup.send("This is not an appeal ticket.", ephemeral=True)

            return

        if not self._is_jail_admin(author) and not author.guild_permissions.administrator:

            await interaction.followup.send("You don't have permission to deny appeals.", ephemeral=True)

            return

        c = self.conn.cursor()

        rec = c.execute("SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'", (channel.id,)).fetchone()

        if not rec:

            await interaction.followup.send("No open appeal found.", ephemeral=True)

            return

        user_id = rec["user_id"]

        appeal_id = rec["id"]

        guild = interaction.guild

        member = guild.get_member(int(user_id))

        await interaction.followup.send("Bitte gib einen Grund für die Ablehnung ein (ephemeral). Antworte mit dem Grund in diesem Ephemeral-Dialog.", ephemeral=True)

        deny_reason = "Denied by staff"

        filename = await self._make_transcript_file(channel, user_id, appeal_id)

        try:

            with open(filename, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "[Could not read transcript file]"

        self._close_appeal(channel.id, "denied", transcript_text)

        embed = discord.Embed(title="❌ Appeal Denied", description=f"By: {author.mention}\nUser: <@{user_id}>\nReason: {deny_reason}", color=discord.Color.red(), timestamp=datetime.datetime.utcnow())

        embed.add_field(name="Appeal ID", value=str(appeal_id), inline=True)

        embed.add_field(name="Channel", value=channel.mention, inline=True)

        embed.set_footer(text=f"Denied at {pretty_ts()}")

        try:

            dfile = discord.File(filename, filename=os.path.basename(filename))

            await self._log_mod(guild, embed=embed, file=dfile)

        except Exception:

            await self._log_mod(guild, embed=embed)

        try:

            os.remove(filename)

        except Exception:

            pass

        try:

            if member:

                await member.send(f"Your appeal in {guild.name} was DENIED by {author}. Reason: {deny_reason}")

        except Exception:

            pass

        try:

            await channel.send(embed=discord.Embed(title="Appeal denied — closing ticket...", color=discord.Color.red()))

            await asyncio.sleep(2)

            await channel.delete(reason=f"Appeal denied by {author}")

        except Exception:

            pass

        try:

            await interaction.followup.send("Appeal denied.", ephemeral=True)

        except Exception:

            pass

    async def _handle_button_close(self, interaction: discord.Interaction):

        channel = interaction.channel

        author = interaction.user

        if not self._is_ticket_channel(channel):

            await interaction.followup.send("This is not an appeal ticket.", ephemeral=True)

            return

        if not (self._is_jail_admin(author) or author.guild_permissions.administrator):

            await interaction.followup.send("You don't have permission to close tickets.", ephemeral=True)

            return

        c = self.conn.cursor()

        rec = c.execute("SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'", (channel.id,)).fetchone()

        if rec:

            user_id = rec["user_id"]

            appeal_id = rec["id"]

            filename = await self._make_transcript_file(channel, user_id, appeal_id)

            try:

                with open(filename, "r", encoding="utf-8") as f:

                    transcript_text = f.read()

            except Exception:

                transcript_text = "[Could not read transcript file]"

            self._close_appeal(channel.id, "closed", transcript_text)

            embed = discord.Embed(title="🔒 Ticket Closed", description=f"Closed by: {author.mention}\nUser: <@{user_id}>", color=discord.Color.light_grey(), timestamp=datetime.datetime.utcnow())

            embed.set_footer(text=f"Closed at {pretty_ts()}")

            try:

                dfile = discord.File(filename, filename=os.path.basename(filename))

                await self._log_mod(channel.guild, embed=embed, file=dfile)

            except Exception:

                await self._log_mod(channel.guild, embed=embed)

            try:

                os.remove(filename)

            except Exception:

                pass

        try:

            await channel.send("Ticket will be closed...", delete_after=2)

            await asyncio.sleep(2)

            await channel.delete(reason=f"Closed by {author}")

        except Exception:

            pass

        try:

            await interaction.followup.send("Ticket closed.", ephemeral=True)

        except Exception:

            pass

    # ticket commands

    def _is_ticket_channel(self, channel: discord.TextChannel) -> bool:

        return channel.id in self.ticket_channel_cache

    def _is_jail_admin(self, member: discord.Member) -> bool:

        cfg = self._get_guild_config(member.guild.id) or {}

        role_id = cfg.get("admin_role")

        if not role_id:

            return False

        role = member.guild.get_role(int(role_id))

        return role in member.roles if role else False

    @commands.command(name="approve")

    async def cmd_approve(self, ctx, *, message: Optional[str] = "Approved"):

        if not self._is_ticket_channel(ctx.channel):

            await ctx.send(embed=discord.Embed(title="Not a ticket", description="This command must be used inside an appeal ticket.", color=discord.Color.orange()))

            return

        if not self._is_jail_admin(ctx.author) and not ctx.author.guild_permissions.administrator:

            await ctx.send(embed=discord.Embed(title="Not allowed", description="You do not have permission to approve appeals.", color=discord.Color.red()))

            return

        c = self.conn.cursor()

        rec = c.execute("SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'", (ctx.channel.id,)).fetchone()

        if not rec:

            await ctx.send(embed=discord.Embed(title="No open appeal", description="Cannot find an open appeal for this channel.", color=discord.Color.orange()))

            return

        user_id = rec["user_id"]

        appeal_id = rec["id"]

        guild = ctx.guild

        member = guild.get_member(int(user_id))

        filename = await self._make_transcript_file(ctx.channel, user_id, appeal_id)

        jailed = self._get_jailed_user(guild.id, int(user_id))

        if jailed:

            prev = json.loads(jailed["previous_roles"]) if jailed["previous_roles"] else []

            roles_objs = [guild.get_role(rid) for rid in prev if guild.get_role(rid)]

            jail_role_id = self._get_guild_config(guild.id).get("jail_role")

            jail_role = guild.get_role(int(jail_role_id)) if jail_role_id else None

            try:

                if jail_role and member and jail_role in member.roles:

                    await member.remove_roles(jail_role, reason=f"Appeal approved by {ctx.author}")

                if member and roles_objs:

                    await member.add_roles(*roles_objs, reason=f"Appeal approved by {ctx.author}")

            except Exception:

                pass

            self._remove_jailed_user(guild.id, int(user_id))

        try:

            with open(filename, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "[Could not read transcript file]"

        self._close_appeal(ctx.channel.id, "approved", transcript_text)

        embed = discord.Embed(title="✅ Appeal Approved", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())

        embed.add_field(name="By", value=ctx.author.mention, inline=True)

        embed.add_field(name="User", value=f"<@{user_id}>", inline=True)

        embed.add_field(name="Message", value=message, inline=False)

        embed.set_footer(text=f"Approved at {pretty_ts()}")

        try:

            dfile = discord.File(filename, filename=os.path.basename(filename))

            await self._log_mod(guild, embed=embed, file=dfile)

        except Exception:

            await self._log_mod(guild, embed=embed)

        try:

            os.remove(filename)

        except Exception:

            pass

        try:

            if member:

                await member.send(f"Your appeal in {guild.name} was APPROVED by {ctx.author}. Message: {message}")

        except Exception:

            pass

        await ctx.send(embed=discord.Embed(title="Appeal approved — Ticket closing...", color=discord.Color.green()))

        await asyncio.sleep(3)

        try:

            await ctx.channel.delete(reason=f"Appeal approved by {ctx.author}")

        except Exception:

            pass

    @commands.command(name="deny")

    async def cmd_deny(self, ctx, *, reason: Optional[str] = "Denied"):

        if not self._is_ticket_channel(ctx.channel):

            await ctx.send(embed=discord.Embed(title="Not a ticket", description="This command must be used inside an appeal ticket.", color=discord.Color.orange()))

            return

        if not self._is_jail_admin(ctx.author) and not ctx.author.guild_permissions.administrator:

            await ctx.send(embed=discord.Embed(title="Not allowed", description="You do not have permission to deny appeals.", color=discord.Color.red()))

            return

        c = self.conn.cursor()

        rec = c.execute("SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'", (ctx.channel.id,)).fetchone()

        if not rec:

            await ctx.send(embed=discord.Embed(title="No open appeal", description="Cannot find an open appeal for this channel.", color=discord.Color.orange()))

            return

        user_id = rec["user_id"]

        appeal_id = rec["id"]

        guild = ctx.guild

        member = guild.get_member(int(user_id))

        filename = await self._make_transcript_file(ctx.channel, user_id, appeal_id)

        try:

            with open(filename, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "[Could not read transcript file]"

        self._close_appeal(ctx.channel.id, "denied", transcript_text)

        embed = discord.Embed(title="❌ Appeal Denied", color=discord.Color.red(), timestamp=datetime.datetime.utcnow())

        embed.add_field(name="By", value=ctx.author.mention, inline=True)

        embed.add_field(name="User", value=f"<@{user_id}>", inline=True)

        embed.add_field(name="Reason", value=reason, inline=False)

        embed.set_footer(text=f"Denied at {pretty_ts()}")

        try:

            dfile = discord.File(filename, filename=os.path.basename(filename))

            await self._log_mod(guild, embed=embed, file=dfile)

        except Exception:

            await self._log_mod(guild, embed=embed)

        try:

            os.remove(filename)

        except Exception:

            pass

        try:

            if member:

                await member.send(f"Your appeal in {guild.name} was DENIED by {ctx.author}. Reason: {reason}")

        except Exception:

            pass

        await ctx.send(embed=discord.Embed(title="Appeal denied — Ticket closing...", color=discord.Color.red()))

        await asyncio.sleep(3)

        try:

            await ctx.channel.delete(reason=f"Appeal denied by {ctx.author}")

        except Exception:

            pass

    @commands.command(name="appeallog")

    @commands.has_permissions(manage_guild=True)

    async def cmd_appeallog(self, ctx, member: discord.Member, limit: int = 5):

        guild = ctx.guild

        rows = self._get_appeals_for_user(guild.id, member.id, limit=limit)

        if not rows:

            await ctx.send(embed=discord.Embed(title="No appeals", description="No appeals found for this user.", color=discord.Color.orange()))

            return

        lines = []

        for r in rows:

            created = r["created_at"]

            status = r["status"]

            lid = r["id"]

            lines.append(f"• ID: {lid} — {status} — created at {created}")

        embed = discord.Embed(title=f"Appeals for {member}", description="\n".join(lines), color=BLURPLE)

        embed.set_footer(text=f"Requested by {ctx.author} • {pretty_ts()}")

        await ctx.send(embed=embed)

    def cog_unload(self):

        try:

            self.conn.close()

        except Exception:

            pass

async def setup(bot: commands.Bot):

    await bot.add_cog(JailCog(bot))

