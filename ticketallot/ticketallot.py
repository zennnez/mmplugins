# ticketallot.py — Ticket Allotment Plugin for Modmail
# Dynamically assigns new tickets to staff by role-based ratio distribution.
#
# ── Command reference ──────────────────────────────────────────────────────────
#  ticketallot / ta                                  — Help overview
#  ta status                                         — Plugin status
#  ta toggle                                         — Enable / disable
#  ta alertchannel #ch                               — Set escalation alert channel
#  ta reset                                          — Wipe all assignment records
#
#  ta role add @R ratio [deadline] [escalation] [transfer]
#  ta role remove @R
#  ta role view
#  ta role deadline @R <time>
#  ta role escalation @R <time> [transfer]
#
#  ta category [#category]      — Set / clear your personal ticket category
#
#  ta reminder [repeat] [ping]  — View / set your personal reminder intervals
#  ta reminder stop [#ch]       — Stop spam phase, reset repeat cycle
#  ta reminder auto [repeat] [ping]   — View / set global default intervals
#  ta reminder auto toggle             — Enable / disable auto-reminders
#
#  ta assign #ch @member        — Manually assign a ticket
#  ta complete [#ch]            — Mark ticket complete
#  ta dashboard [mod]           — Paginated pending/completed view
#  ta rolecheck                 — Live distribution vs targets
#

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import discord
from discord.ext import commands, tasks

from core import checks
from core.models import PermissionLevel, getLogger
from core.paginator import EmbedPaginatorSession
from core.time import Time, human_timedelta

logger = getLogger(__name__)


# ─── Local helpers ────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    """Return the current UTC-aware datetime."""
    return discord.utils.utcnow()


def ensure_utc(dt: datetime) -> datetime:
    """Guarantee a datetime is UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def chunks(lst: list, n: int):
    """Split list into chunks of size n."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _fix_footers(pages: List[discord.Embed]) -> None:
    n = len(pages)
    for i, p in enumerate(pages):
        existing = p.footer.text or ""
        base = existing.split(" • Page ")[0].rstrip(" •")
        p.set_footer(text=f"{base} • Page {i + 1}/{n}".lstrip(" •"))


# ─── Main Cog ─────────────────────────────────────────────────────────────────

class TicketAllot(commands.Cog):
    """
    Dynamically allot modmail tickets to staff members by role-ratio distribution.

    **Distribution** — each role has a target % of open tickets.  When a ticket
    arrives the plugin picks the role whose share would be *least* over-represented
    and the member inside that role with the fewest open tickets.

    **Category routing** — each staff member can register a Discord category;
    tickets assigned to them are moved there automatically.

    **Reminders** — a two-phase ping schedule:
      • WAIT phase: after ``repeat_m`` minutes the first ping is sent.
      • SPAM phase: pings repeat every ``ping_m`` minutes until ``ta reminder stop``.
      ``ta reminder stop`` exits spam and restarts the repeat countdown from *now*.

    Default schedule (set at startup and overridable per-member):
      • Repeat  = 2 hours  → first ping 2 hours after assignment.
      • Ping    = 1 minute → then every minute until stopped.

    **Escalation** — after a role-specific window all configured roles are tagged
    in the alert channel.  Optional auto-transfer to a higher-authority role.
    """

    # ── Assignment record schema ───────────────────────────────────────────────
    # str(channel_id) → {
    #   "member_id":        int,
    #   "role_id":          int,
    #   "assigned_at":      ISO str,
    #   "channel_name":     str,
    #   "completed":        bool,
    #   "completed_at":     ISO str | None,
    #   "notified":         bool,         ← deadline in-channel tag sent
    #   "escalated":        bool,         ← escalation alert sent
    #   "last_reminder_at": ISO str | None,
    #   "in_ping_mode":     bool,         ← True = currently in spam phase
    # }

    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)

        self.config: Optional[dict] = None
        self.enabled: bool = True

        # str(role_id) → {ratio, deadline_hours, escalation_hours, transfer}
        self.roles: Dict[str, dict] = {}
        self.alert_channel: Optional[int] = None

        # str(member_id) → discord category channel id (int)
        self.member_categories: Dict[str, int] = {}

        # str(member_id) → {repeat: int (minutes), ping: int (minutes)}
        self.member_reminders: Dict[str, dict] = {}

        # Global reminder defaults — 2 h repeat, 1 m ping (per user's spec)
        self.auto_reminder_enabled: bool = True
        self.default_repeat: int = 120   # minutes — 2 hours
        self.default_ping: int = 1       # minute

        self.assignments: Dict[str, dict] = {}

        self._reminder_msg_cache: Dict[str, discord.Message] = {}

    # ─── Reminder cache helper ────────────────────────────────────────────────

    async def _delete_cached_reminder(self, cid: str, *, reason: str = "") -> None:
        """
        Delete the cached reminder message for *cid* (if any) and remove it
        from the cache. Safe to call even if nothing is cached.
        """
        old_msg = self._reminder_msg_cache.pop(cid, None)
        if old_msg is None:
            logger.debug("ticketallot: no cached reminder message for %s (%s)", cid, reason)
            return
        try:
            await old_msg.delete()
            logger.info(
                "ticketallot: deleted reminder message %s in channel %s (%s)",
                old_msg.id, cid, reason,
            )
        except discord.NotFound:
            logger.debug(
                "ticketallot: reminder message %s in channel %s already deleted (%s)",
                old_msg.id, cid, reason,
            )
        except discord.Forbidden:
            logger.warning(
                "ticketallot: missing permission to delete reminder message %s in channel %s (%s)",
                old_msg.id, cid, reason,
            )
        except discord.HTTPException as e:
            logger.warning(
                "ticketallot: failed to delete reminder message %s in channel %s (%s): %s",
                old_msg.id, cid, reason, e,
            )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def cog_load(self) -> None:
        _default = {
            "enabled":              True,
            "roles":                {},
            "alert_channel":        None,
            "member_categories":    {},
            "member_reminders":     {},
            "assignments":          {},
            "auto_reminder_enabled": True,
            "default_repeat":       120,
            "default_ping":         1,
        }
        self.config = await self.db.find_one({"_id": "config"})
        if self.config is None:
            await self.db.find_one_and_update(
                {"_id": "config"}, {"$set": _default}, upsert=True
            )
            self.config = await self.db.find_one({"_id": "config"})

        for k, v in _default.items():
            if k not in self.config:
                self.config[k] = v

        self.enabled               = self.config.get("enabled", True)
        self.roles                 = self.config.get("roles", {})
        self.alert_channel         = self.config.get("alert_channel")
        self.member_categories     = self.config.get("member_categories", {})
        self.member_reminders      = self.config.get("member_reminders", {})
        self.assignments           = self.config.get("assignments", {})
        self.auto_reminder_enabled = self.config.get("auto_reminder_enabled", True)
        self.default_repeat        = self.config.get("default_repeat", 120)
        self.default_ping          = self.config.get("default_ping", 1)

        self.deadline_check_loop.start()
        self.reminder_loop.start()

        logger.info(
            "ticketallot: loaded — enabled=%s roles=%d assignments=%d "
            "auto_reminder=%s default_repeat=%dm default_ping=%dm",
            self.enabled, len(self.roles), len(self.assignments),
            self.auto_reminder_enabled, self.default_repeat, self.default_ping,
        )

    def cog_unload(self) -> None:
        self.deadline_check_loop.cancel()
        self.reminder_loop.cancel()
        cached = len(self._reminder_msg_cache)
        self._reminder_msg_cache.clear()
        logger.info("ticketallot: unloaded — cleared %d cached reminder message(s)", cached)

    async def _save(self) -> None:
        await self.db.find_one_and_update(
            {"_id": "config"},
            {
                "$set": {
                    "enabled":               self.enabled,
                    "roles":                 self.roles,
                    "alert_channel":         self.alert_channel,
                    "member_categories":     self.member_categories,
                    "member_reminders":      self.member_reminders,
                    "assignments":           self.assignments,
                    "auto_reminder_enabled": self.auto_reminder_enabled,
                    "default_repeat":        self.default_repeat,
                    "default_ping":          self.default_ping,
                }
            },
            upsert=True,
        )

    # ─── Distribution helpers ─────────────────────────────────────────────────

    def _open_assignments(self) -> List[dict]:
        return [a for a in self.assignments.values() if not a.get("completed")]

    def _role_open_counts(self) -> Dict[str, int]:
        counts = {rid: 0 for rid in self.roles}
        for a in self._open_assignments():
            rid = str(a.get("role_id", 0))
            if rid in counts:
                counts[rid] += 1
        return counts

    def _member_open_count(self, member_id: int) -> int:
        return sum(1 for a in self._open_assignments() if a["member_id"] == member_id)

    def _member_total_count(self, member_id: int) -> int:
        return sum(1 for a in self.assignments.values() if a["member_id"] == member_id)

    def _pick_role(self) -> Optional[str]:
        """
        Select which role receives the next ticket.

        For every role R compute:
            overshoot_R = (current_open_R + 1) / (total_open + 1) − target_ratio_R

        The role with the *minimum* overshoot is chosen (least over-represented).
        Ties break by the highest target ratio.  Roles with no real members are skipped.
        """
        if not self.roles:
            return None

        total_after = len(self._open_assignments()) + 1
        role_counts = self._role_open_counts()
        best_role: Optional[str] = None
        best_shoot = float("inf")

        for rid, cfg in self.roles.items():
            role = self.bot.modmail_guild.get_role(int(rid))
            if role is None or not any(not m.bot for m in role.members):
                continue

            target    = cfg.get("ratio", 0) / 100.0
            current   = role_counts.get(rid, 0)
            overshoot = (current + 1) / total_after - target

            if overshoot < best_shoot or (
                overshoot == best_shoot
                and best_role is not None
                and cfg.get("ratio", 0) > self.roles[best_role].get("ratio", 0)
            ):
                best_shoot = overshoot
                best_role  = rid

        return best_role

    def _pick_new_ticket_member(self) -> Optional[Tuple[discord.Member, int]]:
        """
        Pick the member with the fewest total tickets assigned to them; ties broken by fewest currently open tickets.
        """

        total_after = len(self.assignments) + 1
        candidates = []

        for rid, cfg in self.roles.items():
            role = self.bot.modmail_guild.get_role(int(rid))
            if not role:
                continue

            members = [m for m in role.members if not m.bot]
            if not members:
                continue

            role_ratio = cfg.get("ratio", 0)
            member_share = role_ratio / len(members)

            for member in members:
                total_count = self._member_total_count(member.id)
                open_count = self._member_open_count(member.id)

                expected_total = (
                    total_after * (member_share / 100)
                )

                deficit = expected_total - total_count

                candidates.append((
                    -deficit,
                    open_count,
                    total_count,
                    member.id,
                    member,
                    int(rid),
                ))

        if not candidates:
            return None

        candidates.sort()

        _, _, _, _, member, role_id = candidates[0]

        return member, role_id

    def _pick_role_member(self, role_id: str) -> Optional[discord.Member]:
        """
        Pick the member in *role_id* with the fewest total tickets assigned to
        them; ties broken by fewest currently open tickets.
        """
        role = self.bot.modmail_guild.get_role(int(role_id))
        if not role:
            return None
        members = [m for m in role.members if not m.bot]
        if not members:
            return None
        return min(
            members,
            key=lambda m: (self._member_total_count(m.id), self._member_open_count(m.id)),
        )

    def _pick_higher_role(self, current_role_id: str) -> Optional[str]:
        """
        Return the role id with the next lower ratio (higher authority) below
        the given role, or None if already at the top.

        Convention used here: lower ratio % = fewer tickets = senior/authority role.
        """
        current_ratio = self.roles.get(current_role_id, {}).get("ratio", 0)
        candidates = {
            rid: cfg
            for rid, cfg in self.roles.items()
            if rid != current_role_id and cfg.get("ratio", 0) < current_ratio
        }
        if not candidates:
            return None
        return max(candidates, key=lambda rid: candidates[rid].get("ratio", 0))

    # ─── Assignment record factory ────────────────────────────────────────────

    @staticmethod
    def _new_record(member_id: int, role_id: int, channel_name: str) -> dict:
        now = utcnow().isoformat()
        return {
            "member_id":        member_id,
            "role_id":          role_id,
            "assigned_at":      now,
            "channel_name":     channel_name,
            "completed":        False,
            "completed_at":     None,
            "notified":         False,
            "escalated":        False,
            "last_reminder_at": None,
            "in_ping_mode":     False,
        }

    # ─── Shared assignment + channel-move logic ───────────────────────────────

    async def _do_assign(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
        role_id: int,
        *,
        assigned_by: Optional[discord.Member] = None,  # None = automatic
    ) -> None:
        """
        Save assignment record, move channel to member's category (if set),
        and post the assignment embed inside the ticket channel.
        """
        now      = utcnow()
        cid      = str(channel.id)
        role_cfg = self.roles.get(str(role_id), {})
        role     = self.bot.modmail_guild.get_role(role_id)

        await self._delete_cached_reminder(cid, reason="new assignment")

        self.assignments[cid] = self._new_record(member.id, role_id, channel.name)
        await self._save()

        logger.info(
            "ticketallot: assigned channel %s (%s) to member %s via role %s%s",
            cid, channel.name, member.id, role_id,
            f" by {assigned_by.id}" if assigned_by else " (auto)",
        )

        # ── Optional category move ────────────────────────────────────────────
        moved_category: Optional[discord.CategoryChannel] = None
        cat_id = self.member_categories.get(str(member.id))
        if cat_id:
            cat = self.bot.modmail_guild.get_channel(cat_id)
            if isinstance(cat, discord.CategoryChannel):
                try:
                    await channel.edit(
                        category=cat,
                        reason="TicketAllot: moved to assignee category",
                    )
                    moved_category = cat
                    logger.info(
                        "ticketallot: moved channel %s to category %s for member %s",
                        cid, cat.id, member.id,
                    )
                except discord.Forbidden:
                    logger.warning(
                        "ticketallot: missing permission to move channel %s to category %s",
                        cid, cat.id,
                    )

        # ── Build embed ───────────────────────────────────────────────────────
        deadline_h = role_cfg.get("deadline_hours", 0)
        embed = discord.Embed(
            title="🎫 Ticket Assigned" + (" (Manual)" if assigned_by else ""),
            color=self.bot.main_color,
            timestamp=now,
        )
        embed.add_field(name="Assigned To", value=member.mention,                             inline=True)
        embed.add_field(name="Role",        value=role.mention if role else f"`{role_id}`",   inline=True)

        if moved_category:
            embed.add_field(
                name="📂 Moved To Category",
                value=f"**{moved_category.name}**",
                inline=True,
            )
            embed.description = (
                f"This ticket has been moved to **{moved_category.mention}**."
            )

        if deadline_h:
            due = now + timedelta(hours=deadline_h)
            embed.add_field(
                name="Due By",
                value=(
                    f"{discord.utils.format_dt(due, 'f')} "
                    f"({discord.utils.format_dt(due, 'R')})"
                ),
                inline=True,
            )

        footer_parts: List[str] = [f"Staff ID: {member.id}"]
        if assigned_by:
            footer_parts.append(f"Assigned by {assigned_by.display_name}")
        footer_parts.append("Use `ta complete` when done")
        embed.set_footer(text=" • ".join(footer_parts))

        try:
            await channel.send(content=member.mention, embed=embed)
        except discord.HTTPException as e:
            logger.warning(
                "ticketallot: failed to send assignment embed in channel %s: %s", cid, e
            )

    # ─── Listeners ────────────────────────────────────────────────────────────

    async def _get_log(self, channel) -> Optional[dict]:
        await asyncio.sleep(2)
        if channel.guild != self.bot.modmail_guild:
            return None
        try:
            return await self.bot.api.get_log(channel.id) or None
        except Exception:
            return None

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.TextChannel) -> None:
        if not self.enabled or not isinstance(channel, discord.TextChannel) or not self.roles:
            return
        if not await self._get_log(channel):
            return

        result = self._pick_new_ticket_member()
        if not result:
            return

        member, role_id = result

        await self._do_assign(channel, member, role_id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Auto-complete when a modmail thread channel is deleted."""
        cid = str(channel.id)
        if self._reminder_msg_cache.pop(cid, None) is not None:
            logger.debug(
                "ticketallot: dropped cached reminder for deleted channel %s", cid
            )
        if cid in self.assignments and not self.assignments[cid].get("completed"):
            self.assignments[cid]["completed"]    = True
            self.assignments[cid]["completed_at"] = utcnow().isoformat()
            # Silence any ongoing reminder
            self.assignments[cid]["in_ping_mode"] = False
            await self._save()
            logger.info(
                "ticketallot: channel %s deleted — marked assignment complete", cid
            )

    # ─── Background: Deadlines + Escalation ──────────────────────────────────

    @tasks.loop(minutes=5)
    async def deadline_check_loop(self) -> None:
        now     = utcnow()
        changed = False

        for cid, a in list(self.assignments.items()):
            if a.get("completed"):
                continue

            rid = str(a.get("role_id", 0))
            if rid not in self.roles:
                continue

            cfg        = self.roles[rid]
            assigned   = ensure_utc(datetime.fromisoformat(a["assigned_at"]))
            elapsed_h  = (now - assigned).total_seconds() / 3600
            deadline_h = cfg.get("deadline_hours", 0)
            esc_h      = cfg.get("escalation_hours", 0)

            # ── Deadline: tag assignee inside ticket ──────────────────────────
            if deadline_h and elapsed_h >= deadline_h and not a.get("notified"):
                channel = self.bot.modmail_guild.get_channel(int(cid))
                member  = self.bot.modmail_guild.get_member(a["member_id"])
                if channel and member:
                    dl_str = human_timedelta(
                        now + timedelta(hours=deadline_h), source=now, suffix=False
                    )
                    embed = discord.Embed(
                        title="⏰ Deadline Reached",
                        description=(
                            f"{member.mention}, this ticket has been open for "
                            f"**{human_timedelta(assigned, source=now, suffix=False)}** "
                            f"and has reached its **{dl_str}** deadline. "
                            "Please action it as soon as possible."
                        ),
                        color=discord.Color.orange(),
                        timestamp=now,
                    )
                    embed.set_footer(text="Automated deadline reminder")
                    try:
                        await channel.send(embed=embed)
                        logger.info(
                            "ticketallot: deadline reached for channel %s (member %s)",
                            cid, a["member_id"],
                        )
                    except discord.HTTPException as e:
                        logger.warning(
                            "ticketallot: failed to send deadline embed for channel %s: %s",
                            cid, e,
                        )
                else:
                    logger.warning(
                        "ticketallot: deadline reached for channel %s but channel/member "
                        "missing (channel=%s, member=%s)",
                        cid, bool(channel), bool(member),
                    )
                self.assignments[cid]["notified"] = True
                changed = True

            # ── Escalation ────────────────────────────────────────────────────
            if esc_h and elapsed_h >= esc_h and not a.get("escalated"):
                logger.info(
                    "ticketallot: escalation triggered for channel %s (member %s, "
                    "role %s, transfer=%s)",
                    cid, a["member_id"], rid, cfg.get("transfer", False),
                )
                if cfg.get("transfer"):
                    # Transfer resets the record so future escalation can fire again
                    await self._handle_escalation_transfer(cid, a, now)
                    # Do NOT set escalated=True — the fresh record will accumulate its own time
                else:
                    self.assignments[cid]["escalated"] = True
                await self._post_escalation(cid, a, now, elapsed_h)
                changed = True

        if changed:
            await self._save()

    async def _handle_escalation_transfer(
        self, cid: str, a: dict, now: datetime
    ) -> None:
        """Reassign the ticket to a higher-authority role member."""
        current_rid = str(a.get("role_id", 0))
        higher_rid  = self._pick_higher_role(current_rid)
        if not higher_rid:
            return

        new_member = self._pick_role_member(higher_rid)
        if not new_member:
            return

        guild      = self.bot.modmail_guild
        channel    = guild.get_channel(int(cid))
        if not channel:
            return

        old_member = guild.get_member(a["member_id"])
        old_member_id = a["member_id"]
        new_role   = guild.get_role(int(higher_rid))

        await self._delete_cached_reminder(cid, reason="escalation transfer")

        # Mutate the existing record in-place (shared reference with self.assignments[cid])
        a["member_id"]        = new_member.id
        a["role_id"]          = int(higher_rid)
        a["assigned_at"]      = now.isoformat()
        a["notified"]         = False
        a["escalated"]        = False  # reset so it can escalate again under new role
        a["last_reminder_at"] = None
        a["in_ping_mode"]     = False

        logger.info(
            "ticketallot: escalation transfer — channel %s reassigned from member %s "
            "(role %s) to member %s (role %s)",
            cid, old_member_id, current_rid, new_member.id, higher_rid,
        )

        embed = discord.Embed(
            title="🚨 Ticket Escalated & Transferred",
            description=(
                "This ticket has been escalated and automatically reassigned to a "
                "higher-authority role.\n"
                f"**New Assignee:** {new_member.mention}\n"
                f"**New Role:** {new_role.mention if new_role else f'<@&{higher_rid}>'}"
            ),
            color=discord.Color.red(),
            timestamp=now,
        )
        if old_member:
            embed.add_field(name="Previous Assignee", value=old_member.mention, inline=True)

        # Move to new assignee's category if configured
        cat_id = self.member_categories.get(str(new_member.id))
        if cat_id:
            category = guild.get_channel(cat_id)
            if isinstance(category, discord.CategoryChannel):
                try:
                    await channel.edit(category=category)
                    embed.add_field(name="Moved To", value=f"#{category.name}", inline=True)
                except discord.Forbidden:
                    logger.warning(
                        "ticketallot: missing permission to move channel %s to category %s "
                        "during transfer",
                        cid, category.id,
                    )

        old_role = guild.get_role(int(current_rid))
        embed.set_footer(
            text=f"Escalated from {old_role.name if old_role else 'Unknown Role'}"
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            logger.warning(
                "ticketallot: failed to send transfer embed for channel %s: %s", cid, e
            )

    async def _post_escalation(
        self, cid: str, a: dict, now: datetime, elapsed_h: float
    ) -> None:
        if not self.alert_channel:
            logger.debug(
                "ticketallot: escalation for channel %s not posted — no alert channel configured",
                cid,
            )
            return
        alert_ch = self.bot.modmail_guild.get_channel(self.alert_channel)
        if not alert_ch:
            logger.warning(
                "ticketallot: configured alert channel %s not found", self.alert_channel
            )
            return

        guild      = self.bot.modmail_guild
        member     = guild.get_member(a["member_id"])
        a_role     = guild.get_role(a.get("role_id", 0))
        ticket_ch  = guild.get_channel(int(cid))
        assigned   = ensure_utc(datetime.fromisoformat(a["assigned_at"]))

        role_mentions = " ".join(
            r.mention for rid in self.roles if (r := guild.get_role(int(rid))) is not None
        )

        embed = discord.Embed(
            title="🚨 Escalation Alert — Unresolved Ticket",
            color=discord.Color.red(),
            timestamp=now,
        )
        embed.description = (
            f"{role_mentions}\n\n"
            "A ticket has **not been completed** within the escalation window. "
            "Please ensure it is addressed immediately."
        )
        embed.add_field(
            name="Staff Member",
            value=member.mention if member else f"`{a['member_id']}`",
            inline=True,
        )
        embed.add_field(
            name="Role",
            value=a_role.mention if a_role else f"`{a.get('role_id')}`",
            inline=True,
        )
        embed.add_field(
            name="Ticket",
            value=ticket_ch.mention if ticket_ch else f"#{a.get('channel_name', cid)}",
            inline=True,
        )
        embed.add_field(
            name="Open For",
            value=human_timedelta(assigned, source=now, suffix=False),
            inline=True,
        )
        embed.set_footer(text="Automated escalation alert")
        try:
            await alert_ch.send(content=role_mentions, embed=embed)
            logger.info("ticketallot: posted escalation alert for channel %s", cid)
        except discord.HTTPException as e:
            logger.warning(
                "ticketallot: failed to post escalation alert for channel %s: %s", cid, e
            )

    # ─── Background: Reminders ────────────────────────────────────────────────
    #
    # TWO-PHASE LOGIC per ticket
    # ─────────────────────────────
    # WAIT phase  (in_ping_mode = False)
    #   last_ref = last_reminder_at  OR  assigned_at  (whichever is set)
    #   When (now − last_ref) ≥ repeat_m → send first ping, enter SPAM phase.
    #
    # SPAM phase  (in_ping_mode = True)
    #   When (now − last_reminder_at) ≥ ping_m → send another ping.
    #
    # `ta reminder stop` sets in_ping_mode=False and last_reminder_at=now,
    # restarting the WAIT phase from that moment.

    @tasks.loop(minutes=1)
    async def reminder_loop(self) -> None:
        now     = utcnow()
        changed = False

        for cid, a in list(self.assignments.items()):
            if a.get("completed"):
                continue

            mid = str(a.get("member_id", 0))

            # Determine which reminder config applies (personal > global default)
            if mid in self.member_reminders:
                cfg      = self.member_reminders[mid]
                repeat_m = cfg["repeat"]
                ping_m   = cfg["ping"]
            elif self.auto_reminder_enabled:
                repeat_m = self.default_repeat   # 120 min = 2 hours
                ping_m   = self.default_ping      # 1 min
            else:
                continue

            # Reference timestamp for the current phase
            last_ref_str = a.get("last_reminder_at")
            last_ref = (
                ensure_utc(datetime.fromisoformat(last_ref_str))
                if last_ref_str
                else ensure_utc(datetime.fromisoformat(a["assigned_at"]))
            )

            elapsed_m = (now - last_ref).total_seconds() / 60
            in_ping   = a.get("in_ping_mode", False)
            trigger_m = ping_m if in_ping else repeat_m

            if elapsed_m < trigger_m:
                continue

            logger.debug(
                "ticketallot: reminder due for channel %s (member=%s, in_ping=%s, "
                "elapsed=%.1fm, trigger=%dm)",
                cid, mid, in_ping, elapsed_m, trigger_m,
            )

            # Fetch targets
            channel = self.bot.modmail_guild.get_channel(int(cid))
            member  = self.bot.modmail_guild.get_member(int(mid))

            if not channel:
                logger.warning(
                    "ticketallot: reminder skipped — channel %s not found (deleted?)", cid
                )
            elif not member:
                logger.warning(
                    "ticketallot: reminder skipped — member %s not found in guild for channel %s",
                    mid, cid,
                )

            if channel and member:
                assigned = ensure_utc(datetime.fromisoformat(a["assigned_at"]))

                if not in_ping:
                    # First reminder — enter spam phase
                    title       = "🔔 Ticket Reminder — First Ping"
                    color       = discord.Color.yellow()
                    description = (
                        f"{member.mention}, this ticket has been open for "
                        f"**{human_timedelta(assigned, source=now, suffix=False)}**.\n\n"
                        f"Pings will now repeat every **{ping_m} minute(s)**. "
                        f"Use `ta reminder stop` in this channel to pause them "
                        f"(next reminder in {repeat_m} min after stopping)."
                    )
                else:
                    # Subsequent ping
                    title       = "🔔 Ticket Reminder"
                    color       = discord.Color.orange()
                    description = (
                        f"{member.mention}, this ticket is still pending — "
                        f"open for **{human_timedelta(assigned, source=now, suffix=False)}**.\n\n"
                        f"Use `ta reminder stop` in this channel to pause pings."
                    )

                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=color,
                    timestamp=now,
                )
                embed.set_footer(
                    text=f"Repeat: {repeat_m}m • Ping interval: {ping_m}m"
                )

                await self._delete_cached_reminder(cid, reason="new reminder replacing old")

                try:
                    sent = await channel.send(content=member.mention, embed=embed)
                    self._reminder_msg_cache[cid] = sent
                    logger.info(
                        "ticketallot: sent %s reminder for channel %s to member %s (msg id %s)",
                        "first" if not in_ping else "follow-up", cid, mid, sent.id,
                    )
                except discord.HTTPException as e:
                    logger.warning(
                        "ticketallot: failed to send reminder for channel %s: %s", cid, e
                    )

            # Update state
            self.assignments[cid]["last_reminder_at"] = now.isoformat()
            self.assignments[cid]["in_ping_mode"]     = True
            changed = True

        if changed:
            await self._save()

    @reminder_loop.error
    async def reminder_loop_error(self, error: Exception) -> None:
        logger.error("ticketallot: reminder_loop crashed: %s", error, exc_info=error)
        if not self.reminder_loop.is_running():
            logger.info("ticketallot: restarting reminder_loop after error")
            self.reminder_loop.start()

    @deadline_check_loop.error
    async def deadline_check_loop_error(self, error: Exception) -> None:
        logger.error("ticketallot: deadline_check_loop crashed: %s", error, exc_info=error)
        if not self.deadline_check_loop.is_running():
            logger.info("ticketallot: restarting deadline_check_loop after error")
            self.deadline_check_loop.start()

    @reminder_loop.before_loop
    @deadline_check_loop.before_loop
    async def _before_loops(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)  # brief grace period after startup

    # ─── Dashboard ────────────────────────────────────────────────────────────

    def _build_dashboard_embeds(
        self, target_member: Optional[discord.Member] = None
    ) -> List[discord.Embed]:
        now   = utcnow()
        guild = self.bot.modmail_guild
        color = self.bot.main_color
        pages: List[discord.Embed] = []

        # ── Page 0: Role summary (skipped when filtering by member) ───────────
        if not target_member:
            total_all = len(self.assignments)
            role_counts = self._role_open_counts()

            re = discord.Embed(
                title="📊 Ticket Dashboard — Role Summary",
                color=color,
                timestamp=now,
            )
            re.description = f"Total Allotments tracked: **{total_all}**"

            for rid, cfg in self.roles.items():
                role = guild.get_role(int(rid))
                if not role:
                    continue

                members = [m for m in role.members if not m.bot]
                if not members:
                    continue
                
                # Calculate open and closed tickets
                open_c   = role_counts.get(rid, 0)
                closed_c = sum(
                    1 for a in self.assignments.values()
                    if str(a.get("role_id")) == rid and a.get("completed")
                )

                # Calculate role-level deficit
                ratio = cfg.get("ratio", 0)
                target_share = ratio / 100
                expected = total_all * target_share
                
                # Actual total for role
                actual_total = sum(self._member_total_count(m.id) for m in members)
                actual_pct = (actual_total / total_all * 100) if total_all else 0
                
                # Find the member with the most deficit in this role
                best_member = None
                max_deficit = -float("inf")
                
                for m in members:
                    m_total = self._member_total_count(m.id)
                    member_share = ratio / len(members)
                    m_expected = total_all * (member_share / 100)
                    m_deficit = m_expected - m_total
                    
                    if m_deficit > max_deficit:
                        max_deficit = m_deficit
                        best_member = m
                    elif m_deficit == max_deficit:
                        # Tie-breaker: fewer open tickets
                        if best_member and self._member_open_count(m.id) < self._member_open_count(best_member.id):
                            best_member = m

                dl_h = cfg.get("deadline_hours", 0)
                esc_h = cfg.get("escalation_hours", 0)
                dl_str = human_timedelta(now + timedelta(hours=dl_h), source=now, suffix=False) if dl_h else "—"
                esc_str = human_timedelta(now + timedelta(hours=esc_h), source=now, suffix=False) if esc_h else "—"

                re.add_field(
                    name=role.name,
                    value=(
                        f"Target Share: **{ratio}%** | Actual: **{actual_pct:.1f}%**\n"
                        f"Expected Total Assigned: **{expected:.1f}** | Actual: **{actual_total}**\n"
                        f"Open: **{open_c}** | Closed: **{closed_c}**\n"
                        f"Next Assignee: {best_member.mention if best_member else 'None'} (Deficit: {max_deficit:.2f})\n"
                        f"Deadline: **{dl_str}** | Escalation: **{esc_str}**"
                    ),
                    inline=False,
                )
            if not self.roles:
                re.description = "No roles configured."
            pages.append(re)

        # ── Collect per-member data ───────────────────────────────────────────
        member_data: Dict[int, dict] = {}
        for cid, a in self.assignments.items():
            mid = a["member_id"]
            if target_member and mid != target_member.id:
                continue
            if mid not in member_data:
                member_data[mid] = {
                    "pending":   [],
                    "completed": [],
                    "role_id":   a.get("role_id"),
                }
            assigned = ensure_utc(datetime.fromisoformat(a["assigned_at"]))
            elapsed  = (now - assigned).total_seconds()
            entry    = {
                "cid":       cid,
                "channel":   a.get("channel_name", cid),
                "assigned":  assigned,
                "elapsed":   elapsed,
                "notified":  a.get("notified", False),
                "escalated": a.get("escalated", False),
                "pinging":   a.get("in_ping_mode", False),
            }
            if a.get("completed"):
                comp = ensure_utc(datetime.fromisoformat(a["completed_at"])) if a.get("completed_at") else now
                entry["resolution"] = (comp - assigned).total_seconds()
                member_data[mid]["completed"].append(entry)
            else:
                member_data[mid]["pending"].append(entry)

        if not member_data:
            pages.append(discord.Embed(
                title="📊 Ticket Dashboard",
                description="No assignment data to display.",
                color=color,
            ))
            _fix_footers(pages)
            return pages

        # ── One page per member ───────────────────────────────────────────────
        for mid, data in member_data.items():
            m       = guild.get_member(mid)
            display = m.display_name if m else f"User {mid}"
            role    = guild.get_role(data["role_id"]) if data["role_id"] else None

            embed = discord.Embed(title=f"📋 {display}", color=color, timestamp=now)
            if m:
                embed.set_thumbnail(url=m.display_avatar.url)
            if role:
                embed.add_field(name="Role", value=role.mention, inline=True)

            pending   = sorted(data["pending"],   key=lambda e: e["elapsed"], reverse=True)
            completed = data["completed"]

            embed.add_field(name="⏳ Pending",   value=str(len(pending)),   inline=True)
            embed.add_field(name="✅ Completed", value=str(len(completed)), inline=True)

            if pending:
                lines = []
                for e in pending[:6]:
                    ch    = guild.get_channel(int(e["cid"]))
                    ref   = ch.mention if ch else f"#{e['channel']}"
                    flags = (" 🚨" if e["escalated"] else (" ⏰" if e["notified"] else ""))
                    flags += " 🔔" if e["pinging"] else ""
                    dur   = human_timedelta(e["assigned"], source=now, brief=True, suffix=False)
                    lines.append(f"{ref} — **{dur}**{flags}")
                embed.add_field(
                    name="Pending Tickets (longest open first)",
                    value="\n".join(lines),
                    inline=False,
                )

            if completed:
                def _fmt(s: float) -> str:
                    return human_timedelta(now + timedelta(seconds=s), source=now, brief=True, suffix=False)

                res = [e.get("resolution", 0) for e in completed]
                embed.add_field(
                    name="Resolution Stats",
                    value=(
                        f"**Avg:** {_fmt(sum(res) / len(res))}\n"
                        f"**Fastest:** {_fmt(min(res))}\n"
                        f"**Slowest:** {_fmt(max(res))}"
                    ),
                    inline=False,
                )

            pages.append(embed)

        _fix_footers(pages)
        return pages

    # ═══════════════════════════════════════════════════════════════════════════
    # Commands
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Root ──────────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(name="ticketallot", aliases=["ta"], invoke_without_command=True)
    async def ticketallot_(self, ctx):
        """
        **🎫 Ticket Allotment Plugin**

        Distributes modmail tickets to staff by role ratio, with category routing
        and a two-phase automatic reminder system.

        ─────────────────────────────────────────────────
        **⚙️ Configuration  (Admin)**
        ─────────────────────────────────────────────────
        `{prefix}ta toggle`                   Enable / disable auto-assign
        `{prefix}ta alertchannel #channel`    Set escalation alert channel
        `{prefix}ta status`                   Live status summary
        `{prefix}ta reset`                    ⚠️ Wipe all assignment records

        ─────────────────────────────────────────────────
        **🎭 Role Management  (Admin)**
        ─────────────────────────────────────────────────
        `{prefix}ta role add @R ratio [deadline] [escalation] [transfer]`
        `{prefix}ta role remove @R`
        `{prefix}ta role view`
        `{prefix}ta role deadline @R <time>`
        `{prefix}ta role escalation @R <time> [transfer]`

        ─────────────────────────────────────────────────
        **📂 Category Routing  (Mod)**
        ─────────────────────────────────────────────────
        `{prefix}ta category [#category]`              Set / clear your own ticket category
        `{prefix}ta categoryfor @member [#category]`   Admin: set / clear for another member

        ─────────────────────────────────────────────────
        **⏰ Reminders  (Admin config / Mod stop)**
        ─────────────────────────────────────────────────
        `{prefix}ta reminder [repeat] [ping]`         View / set personal schedule
        `{prefix}ta reminder stop [#channel]`         Stop spam, reset cycle
        `{prefix}ta reminder auto [repeat] [ping]`    View / set global defaults
        `{prefix}ta reminder auto toggle`             Toggle auto-remind on assign

        Default: first ping after **2 hours**, then every **1 minute** until stopped.

        ─────────────────────────────────────────────────
        **📋 Ticket Actions  (Mod)**
        ─────────────────────────────────────────────────
        `{prefix}ta assign @member [#channel]`   Manual assignment (channel defaults to current)
        `{prefix}ta complete [#channel]`       Mark ticket complete
        `{prefix}ta dashboard [mod]`           Paginated dashboard
        `{prefix}ta rolecheck`                 Live ratio snapshot

        ─────────────────────────────────────────────────
        💡 Role ratios must sum to **100%**.
        🔔 dashboard legend: ⏰ deadline tagged · 🚨 escalated · 🔔 reminder spamming
        """
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    # ── role subgroup ──────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketallot_.group(name="role", invoke_without_command=True)
    async def ta_role(self, ctx):
        """Manage roles, ratio targets, deadline and escalation timers."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_role.command(name="add")
    async def ta_role_add(
        self,
        ctx,
        role: discord.Role,
        ratio: float,
        deadline: Time = None,
        escalation: Time = None,
        transfer: bool = False,
    ):
        """
        Add or update a role in the allotment system.

        **Arguments:**
        `role`       — Discord role to configure.
        `ratio`      — Target % of tickets (1–100). E.g. `50` = 50 %.
        `deadline`   — Time until the assigned member is tagged in the ticket.
                       Accepts any time string: ``12h``, ``1d``, ``90m``.  Default: ``24h``.
        `escalation` — Time until all roles are alerted.  Must be ≥ deadline.
                       Default: ``48h``.
        `transfer`   — ``True`` to auto-reassign to a higher-authority role on escalation.

        **Examples:**
        ```
        {prefix}ta role add @Senior-Support 50 12h 36h True
        {prefix}ta role add @Junior-Support 20 1d 3d
        ```
        """
        if not (0 < ratio <= 100):
            return await ctx.send("❌ Ratio must be between 1 and 100.")

        now      = utcnow()
        dl_dt    = ensure_utc(deadline.dt)   if deadline   else now + timedelta(hours=24)
        esc_dt   = ensure_utc(escalation.dt) if escalation else now + timedelta(hours=48)
        dl_sec   = (dl_dt  - now).total_seconds()
        esc_sec  = (esc_dt - now).total_seconds()

        if esc_sec < dl_sec:
            return await ctx.send(
                "❌ Escalation time must be greater than or equal to deadline time."
            )

        other_total = sum(
            v.get("ratio", 0) for k, v in self.roles.items() if k != str(role.id)
        )
        projected = other_total + ratio
        if projected > 100:
            return await ctx.send(
                f"❌ Adding **{ratio}%** would make the total **{projected}%** (exceeds 100%). "
                f"Other roles use **{other_total}%**."
            )

        self.roles[str(role.id)] = {
            "ratio":            ratio,
            "deadline_hours":   dl_sec  / 3600,
            "escalation_hours": esc_sec / 3600,
            "transfer":         transfer,
        }
        await self._save()

        embed = discord.Embed(title="✅ Role Added / Updated", color=self.bot.main_color)
        embed.add_field(name="Role",                  value=role.mention)
        embed.add_field(name="Ratio",                 value=f"{ratio}%")
        embed.add_field(name="Deadline",              value=human_timedelta(dl_dt,  source=now, suffix=False))
        embed.add_field(name="Escalation",            value=human_timedelta(esc_dt, source=now, suffix=False))
        embed.add_field(name="Transfer on Escalation",value="Enabled" if transfer else "Disabled")
        embed.add_field(
            name="New Total Ratio",
            value=f"**{projected}%** {'✅' if projected == 100 else '⚠️ (should be 100%)'}",
            inline=False,
        )
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_role.command(name="remove", aliases=["del", "delete"])
    async def ta_role_remove(self, ctx, role: discord.Role):
        """
        Remove a role from the allotment system.

        Historical records are preserved; the role simply won't receive new tickets.

        **Example:** `{prefix}ta role remove @Junior-Support`
        """
        rid = str(role.id)
        if rid not in self.roles:
            return await ctx.send(f"❌ {role.mention} is not in the allotment list.")
        del self.roles[rid]
        await self._save()
        new_total = sum(v.get("ratio", 0) for v in self.roles.values())
        await ctx.send(
            f"✅ Removed {role.mention}. Remaining total ratio: **{new_total}%**."
        )

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_role.command(name="view")
    async def ta_role_view(self, ctx):
        """List all configured roles with their ratios, timers and settings."""
        if not self.roles:
            return await ctx.send(
                "No roles configured. Use `ta role add @Role ratio` to add one."
            )

        now   = utcnow()
        embed = discord.Embed(title="🎭 Allotment Role Configuration", color=self.bot.main_color)
        total = 0.0

        for rid, cfg in self.roles.items():
            role    = self.bot.modmail_guild.get_role(int(rid))
            total  += cfg.get("ratio", 0)
            members = len([m for m in role.members if not m.bot]) if role else 0
            dl_h    = cfg.get("deadline_hours", 0)
            esc_h   = cfg.get("escalation_hours", 0)
            dl_str  = human_timedelta(now + timedelta(hours=dl_h),  source=now, suffix=False) if dl_h  else "—"
            esc_str = human_timedelta(now + timedelta(hours=esc_h), source=now, suffix=False) if esc_h else "—"
            embed.add_field(
                name=role.name if role else f"Unknown ({rid})",
                value=(
                    f"Ratio: **{cfg.get('ratio', 0)}%**\n"
                    f"Deadline: **{dl_str}**\n"
                    f"Escalation: **{esc_str}**\n"
                    f"Transfer: **{'Yes' if cfg.get('transfer') else 'No'}**\n"
                    f"Members: **{members}**"
                ),
                inline=True,
            )

        embed.set_footer(
            text=f"Total Ratio: {total}% {'✅' if total == 100 else '⚠️  should sum to 100%'}"
        )
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_role.command(name="deadline")
    async def ta_role_deadline(self, ctx, role: discord.Role, deadline: Time):
        """
        Update the deadline timer for a role.

        The deadline triggers an in-ticket tag of the assigned member.
        Must not exceed the role's escalation time.

        **Examples:**
        `{prefix}ta role deadline @Senior-Support 8h`
        `{prefix}ta role deadline @Junior-Support 2d`
        """
        rid = str(role.id)
        if rid not in self.roles:
            return await ctx.send(f"❌ {role.mention} is not configured.")

        now    = utcnow()
        dl_sec = (ensure_utc(deadline.dt) - now).total_seconds()
        esc_h  = self.roles[rid].get("escalation_hours", 0)

        if esc_h and dl_sec > esc_h * 3600:
            return await ctx.send(
                f"❌ Deadline (**{human_timedelta(deadline.dt, source=now, suffix=False)}**) "
                f"must be ≤ escalation time (**{human_timedelta(now + timedelta(hours=esc_h), source=now, suffix=False)}**)."
            )

        self.roles[rid]["deadline_hours"] = dl_sec / 3600
        await self._save()
        await ctx.send(
            f"✅ Deadline for {role.mention} → "
            f"**{human_timedelta(deadline.dt, source=now, suffix=False)}**."
        )

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_role.command(name="escalation")
    async def ta_role_escalation(
        self, ctx, role: discord.Role, escalation: Time, transfer: bool = False
    ):
        """
        Update the escalation timer for a role.

        Must be ≥ the role's deadline time.

        **Examples:**
        `{prefix}ta role escalation @Senior-Support 24h True`
        `{prefix}ta role escalation @Junior-Support 3d`
        """
        rid = str(role.id)
        if rid not in self.roles:
            return await ctx.send(f"❌ {role.mention} is not configured.")

        now     = utcnow()
        esc_sec = (ensure_utc(escalation.dt) - now).total_seconds()
        dl_h    = self.roles[rid].get("deadline_hours", 0)

        if dl_h and esc_sec < dl_h * 3600:
            return await ctx.send(
                f"❌ Escalation (**{human_timedelta(escalation.dt, source=now, suffix=False)}**) "
                f"must be ≥ deadline (**{human_timedelta(now + timedelta(hours=dl_h), source=now, suffix=False)}**)."
            )

        self.roles[rid]["escalation_hours"] = esc_sec / 3600
        self.roles[rid]["transfer"]         = transfer
        await self._save()
        await ctx.send(
            f"✅ Escalation for {role.mention} → "
            f"**{human_timedelta(escalation.dt, source=now, suffix=False)}**, "
            f"transfer **{'enabled' if transfer else 'disabled'}**."
        )

    # ── category ──────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="category", aliases=["cat"])
    async def ta_category(self, ctx, category: discord.CategoryChannel = None):
        """
        Set or clear **your own** ticket category.

        When a ticket is assigned to you its channel is automatically moved
        into this category and the assignment embed shows where it was moved.

        Omit `category` to clear your current setting.

        **Examples:**
        `{prefix}ta category "My Tickets"`   — set your category
        `{prefix}ta category`                 — clear your category
        """
        mid = str(ctx.author.id)

        if category is None:
            if mid in self.member_categories:
                del self.member_categories[mid]
                await self._save()
                return await ctx.send("✅ Your ticket category has been cleared.")
            return await ctx.send(
                f"ℹ️ You don't have a ticket category set.\n"
                f"Use `{ctx.prefix}ta category <category_name>` to set one."
            )

        self.member_categories[mid] = category.id
        await self._save()
        await ctx.send(
            f"✅ Your tickets will be moved to **{category.name}** on assignment."
        )

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketallot_.command(name="categoryfor", aliases=["catfor"])
    async def ta_category_for(self, ctx, member: discord.Member, category: discord.CategoryChannel = None):
        """
        Admin: set or clear the ticket category for **another** staff member.

        Omit `category` to clear their setting.

        **Examples:**
        `{prefix}ta categoryfor @StaffMember "Senior Queue"`  — set category
        `{prefix}ta categoryfor @StaffMember`                  — clear category
        """
        mid = str(member.id)

        if category is None:
            if mid in self.member_categories:
                del self.member_categories[mid]
                await self._save()
                return await ctx.send(
                    f"✅ Ticket category for {member.mention} has been cleared."
                )
            return await ctx.send(
                f"ℹ️ {member.mention} doesn't have a ticket category set."
            )

        self.member_categories[mid] = category.id
        await self._save()
        await ctx.send(
            f"✅ Tickets assigned to {member.mention} will be moved to "
            f"**{category.name}**."
        )

    # ── reminder subgroup ──────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.group(name="reminder", aliases=["remind"], invoke_without_command=True)
    async def ta_reminder(self, ctx, repeat: Time = None, ping: Time = None):
        """
        View or set your **personal** ticket reminder schedule.

        **Arguments:**
        `repeat` — How long to wait after assignment before the first ping
                   (e.g. ``2h``, ``90m``).
        `ping`   — How long between subsequent pings while in the spam phase
                   (e.g. ``1m``, ``5m``).  Must be ≥ 1 minute and < repeat.

        Omit both arguments to display your current settings.

        **Two-phase behaviour:**
        1. After `repeat` time the first ping fires (WAIT → SPAM phase).
        2. Pings repeat every `ping` minutes until you run `ta reminder stop`.
        3. `stop` resets the cycle: next ping will be `repeat` minutes from now.

        **Examples:**
        `{prefix}ta reminder 2h 1m`       — ping after 2 h, then every 1 min
        `{prefix}ta reminder 30m 5m`      — ping after 30 min, then every 5 min
        `{prefix}ta reminder`             — show your current settings
        """
        mid = str(ctx.author.id)
        if repeat is None or ping is None:
            if mid in self.member_reminders:
                cfg = self.member_reminders[mid]
                return await ctx.send(
                    f"🔔 **Your reminder settings** — "
                    f"Repeat: **{cfg['repeat']} min**, Ping: **{cfg['ping']} min**.\n"
                    f"Use `{ctx.prefix}ta reminder stop` inside a ticket to reset the cycle."
                )
            return await ctx.send_help(ctx.command)

        now    = utcnow()
        rep_m  = (ensure_utc(repeat.dt) - now).total_seconds() / 60
        ping_m = (ensure_utc(ping.dt)   - now).total_seconds() / 60

        if ping_m < 1:
            return await ctx.send("❌ Ping interval must be at least 1 minute.")
        if ping_m >= rep_m:
            return await ctx.send(
                "❌ Ping interval must be less than the Repeat interval."
            )

        self.member_reminders[mid] = {"repeat": int(rep_m), "ping": int(ping_m)}
        await self._save()
        await ctx.send(
            f"✅ Personal reminder set — first ping after "
            f"**{human_timedelta(repeat.dt, source=now, suffix=False)}**, "
            f"then every **{human_timedelta(ping.dt, source=now, suffix=False)}**."
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @ta_reminder.command(name="stop", aliases=["reset"])
    async def ta_reminder_stop(self, ctx, channel: discord.TextChannel = None):
        """
        Stop the current ping spam for a ticket and restart the repeat countdown.

        **What this does:**
        1. Exits the spam phase (stops pinging every minute).
        2. Resets `last_reminder_at` to now — next ping fires after the full
           `repeat` interval from this moment.

        Defaults to the current channel if none is specified.

        **Examples:**
        `{prefix}ta reminder stop`
        `{prefix}ta reminder stop #username-1234`
        """
        channel = channel or ctx.channel
        cid     = str(channel.id)

        if cid not in self.assignments or self.assignments[cid].get("completed"):
            return await ctx.send("❌ No active allotment record for that channel.")

        was_pinging = self.assignments[cid].get("in_ping_mode", False)
        now         = utcnow()

        await self._delete_cached_reminder(cid, reason="ta reminder stop")

        self.assignments[cid]["last_reminder_at"] = now.isoformat()
        self.assignments[cid]["in_ping_mode"]     = False
        await self._save()

        logger.info(
            "ticketallot: reminder stopped for channel %s by %s (was_pinging=%s)",
            cid, ctx.author.id, was_pinging,
        )

        # Determine which repeat interval applies
        mid     = str(self.assignments[cid]["member_id"])
        rep_m   = (
            self.member_reminders[mid]["repeat"]
            if mid in self.member_reminders
            else self.default_repeat
        )
        next_at = now + timedelta(minutes=rep_m)

        embed = discord.Embed(
            title="🔕 Reminder Stopped",
            color=self.bot.main_color,
            timestamp=now,
        )
        member = ctx.guild.get_member(self.assignments[cid]["member_id"])
        embed.add_field(name="Channel",    value=channel.mention,                          inline=True)
        embed.add_field(name="Assignee",   value=member.mention if member else "Unknown",  inline=True)
        embed.add_field(name="Was Active", value="Yes 🔔" if was_pinging else "No",        inline=True)
        embed.add_field(
            name="Next Reminder",
            value=(
                f"{discord.utils.format_dt(next_at, 'f')} "
                f"({discord.utils.format_dt(next_at, 'R')})"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Reset by {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_reminder.group(name="auto", invoke_without_command=True)
    async def ta_reminder_auto(self, ctx, repeat: Time = None, ping: Time = None):
        """
        View or set the **global default** reminder schedule applied to all newly
        assigned tickets that don't have a personal override.

        **Arguments:**
        `repeat` — Time before the first ping  (e.g. ``2h``).  Default: ``2h``.
        `ping`   — Time between spam pings     (e.g. ``1m``).  Default: ``1m``.

        Omit both to display the current defaults.

        **Examples:**
        `{prefix}ta reminder auto 2h 1m`    — default: 2 h wait, 1 min spam
        `{prefix}ta reminder auto 4h 2m`    — change defaults
        `{prefix}ta reminder auto`          — show current defaults
        """
        if repeat is None or ping is None:
            state = "Enabled ✅" if self.auto_reminder_enabled else "Disabled ❌"
            return await ctx.send(
                f"🤖 **Auto-Reminder Status:** {state}\n"
                f"Default Repeat: **{self.default_repeat} min** | "
                f"Default Ping: **{self.default_ping} min**.\n"
                f"Use `{ctx.prefix}ta reminder auto <repeat> <ping>` to update."
            )

        now    = utcnow()
        rep_m  = (ensure_utc(repeat.dt) - now).total_seconds() / 60
        ping_m = (ensure_utc(ping.dt)   - now).total_seconds() / 60

        if ping_m < 1:
            return await ctx.send("❌ Default ping interval must be at least 1 minute.")
        if ping_m >= rep_m:
            return await ctx.send(
                "❌ Default ping interval must be less than the Repeat interval."
            )

        self.default_repeat = int(rep_m)
        self.default_ping   = int(ping_m)
        await self._save()
        await ctx.send(
            f"✅ Global auto-reminder updated — first ping after "
            f"**{human_timedelta(repeat.dt, source=now, suffix=False)}**, "
            f"then every **{human_timedelta(ping.dt, source=now, suffix=False)}**."
        )

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ta_reminder_auto.command(name="toggle")
    async def ta_reminder_auto_toggle(self, ctx):
        """
        Toggle automatic reminders for all newly assigned tickets.

        When disabled, no reminders are sent unless a member has a personal
        override via `ta reminder <repeat> <ping>`.
        """
        self.auto_reminder_enabled = not self.auto_reminder_enabled
        await self._save()
        state = "enabled ✅" if self.auto_reminder_enabled else "disabled ❌"
        await ctx.send(f"✅ Automatic reminders are now **{state}**.")

    # ── assign / complete ──────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="assign")
    async def ta_assign(self, ctx, member: discord.Member, channel: discord.TextChannel = None):
        """
        Manually assign a ticket to a specific staff member.

        `channel` defaults to the current channel if not specified.
        Deadline tracking, escalation and reminders apply exactly as for
        automatic assignments.  The member's allotment role is inferred from
        the highest-ratio configured role they belong to.

        **Examples:**
        `{prefix}ta assign @StaffMember`                — assign current channel
        `{prefix}ta assign @StaffMember #ticket-name`   — assign a specific channel
        """
        channel = channel or ctx.channel
        # Infer role
        role_id:    int = 0
        best_ratio: float = -1.0
        guild = self.bot.modmail_guild
        for rid, cfg in self.roles.items():
            r = guild.get_role(int(rid))
            if r and r in member.roles and cfg.get("ratio", 0) > best_ratio:
                role_id    = int(rid)
                best_ratio = cfg.get("ratio", 0)

        await self._do_assign(channel, member, role_id, assigned_by=ctx.author)
        # _do_assign already posts the embed inside the channel
        await ctx.message.add_reaction("✅")

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="complete", aliases=["done", "close"])
    async def ta_complete(self, ctx, channel: discord.TextChannel = None):
        """
        Mark a ticket as completed in the allotment system.

        Defaults to the current channel.  Does **not** close the modmail thread.
        Automatically stops any ongoing reminder spam.

        **Examples:**
        `{prefix}ta complete`
        `{prefix}ta complete #username-1234`
        """
        channel = channel or ctx.channel
        cid     = str(channel.id)

        if cid not in self.assignments:
            return await ctx.send(
                "❌ No allotment record for that channel — "
                "it may not have been assigned through this plugin."
            )
        if self.assignments[cid].get("completed"):
            comp_at = self.assignments[cid].get("completed_at")
            ts = (
                f" (at {discord.utils.format_dt(ensure_utc(datetime.fromisoformat(comp_at)), 'R')})"
                if comp_at else ""
            )
            return await ctx.send(f"ℹ️ This ticket is already marked as completed{ts}.")

        now      = utcnow()
        assigned = ensure_utc(datetime.fromisoformat(self.assignments[cid]["assigned_at"]))

        self.assignments[cid]["completed"]        = True
        self.assignments[cid]["completed_at"]     = now.isoformat()
        self.assignments[cid]["in_ping_mode"]     = False  # silence reminders
        self.assignments[cid]["last_reminder_at"] = now.isoformat()
        await self._save()

        await self._delete_cached_reminder(cid, reason="ta complete")

        logger.info(
            "ticketallot: channel %s marked complete by %s (resolution=%.1fm)",
            cid, ctx.author.id, (now - assigned).total_seconds() / 60,
        )

        member = self.bot.modmail_guild.get_member(self.assignments[cid]["member_id"])
        embed  = discord.Embed(
            title="✅ Ticket Marked Complete",
            color=discord.Color.green(),
            timestamp=now,
        )
        embed.add_field(name="Channel",         value=channel.mention)
        embed.add_field(name="Assignee",        value=member.mention if member else "Unknown")
        embed.add_field(
            name="Resolution Time",
            value=human_timedelta(assigned, source=now, suffix=False),
        )
        embed.set_footer(text=f"Completed by {ctx.author.display_name}")
        await ctx.send(embed=embed)

        if self.alert_channel:
            alert_ch = self.bot.modmail_guild.get_channel(self.alert_channel)
            if alert_ch:
                alert_embed = discord.Embed(
                    title="✅ Ticket Marked Complete",
                    color=discord.Color.green(),
                    timestamp=now,
                )
                alert_embed.add_field(name="Channel",         value=channel.name, inline=True)
                alert_embed.add_field(name="Assignee",        value=member.mention if member else "Unknown", inline=True)
                alert_embed.add_field(name="Completed By",    value=ctx.author.mention, inline=True)
                alert_embed.add_field(
                    name="Resolution Time",
                    value=human_timedelta(assigned, source=now, suffix=False),
                    inline=True,
                )
                try:
                    await alert_ch.send(embed=alert_embed)
                except discord.HTTPException:
                    pass

    # ── dashboard ─────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="dashboard", aliases=["dash", "stats", "board"])
    async def ta_dashboard(self, ctx, mod: discord.Member = None):
        """
        Paginated dashboard of all ticket assignments.

        **Optional:** `mod` — filter to a specific staff member.

        **Page 1** — Role summary (targets vs actual distribution).
        **Subsequent pages** — Per-member breakdown.

        **Legend:** ⏰ deadline tagged · 🚨 escalated · 🔔 reminder spamming

        **Examples:**
        `{prefix}ta dashboard`
        `{prefix}ta dashboard @StaffMember`
        """
        async with ctx.typing():
            embeds = self._build_dashboard_embeds(mod)

        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])

        session = EmbedPaginatorSession(ctx, *embeds)
        await session.run()

    # ── rolecheck ─────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="rolecheck", aliases=["ratio"])
    async def ta_rolecheck(self, ctx):
        """
        Live snapshot of ticket distribution vs targets based on total allotments.

        Shows expected share, actual total, and 'deficit' (how many tickets
        behind/ahead a member is relative to their target).
        """
        total_all = len(self.assignments)
        guild = self.bot.modmail_guild
        color = self.bot.main_color

        if not self.roles:
            return await ctx.send("No roles configured.")

        # Collect data for all roles and members
        role_data = []
        for rid, cfg in self.roles.items():
            role = guild.get_role(int(rid))
            if not role:
                continue

            members = [m for m in role.members if not m.bot]
            if not members:
                continue

            ratio = cfg.get("ratio", 0)
            role_target_share = ratio / 100
            role_expected = total_all * role_target_share
            
            member_stats = []
            role_actual = 0
            for m in members:
                m_total = self._member_total_count(m.id)
                m_open = self._member_open_count(m.id)
                role_actual += m_total
                
                # Deficit calculation logic from _pick_new_ticket_member
                member_share = ratio / len(members)
                expected_total = total_all * (member_share / 100)
                deficit = expected_total - m_total
                
                member_stats.append({
                    "name": m.display_name,
                    "total": m_total,
                    "open": m_open,
                    "deficit": deficit,
                    "expected": expected_total
                })
            
            # Sort members by deficit (highest deficit first, same as _pick_new_ticket_member)
            member_stats.sort(key=lambda x: (-x["deficit"], x["open"]))
            
            role_data.append({
                "name": role.name,
                "target": ratio,
                "expected": role_expected,
                "actual": role_actual,
                "delta": role_actual - role_expected,
                "members": member_stats
            })

        # Build pages
        pages = []
        # Chunk roles if there are many, but usually roles are few. 
        # Members within roles are more likely to need chunking.
        
        for r in role_data:
            # Create a page for each role to show detailed member deficits
            actual_pct = (r["actual"] / total_all * 100) if total_all else 0
            status = "✅" if abs(actual_pct - r["target"]) <= 5 else ("🔴" if actual_pct > r["target"] else "🟡")
            
            embed = discord.Embed(
                title=f"📈 Distribution: {r['name']}",
                color=color,
                timestamp=utcnow()
            )
            embed.description = (
                f"**Target Share:** {r['target']}% | **Actual Share:** {actual_pct:.1f}%\n"
                f"**Expected Total:** {r['expected']:.1f} | **Actual Total:** {r['actual']} {status}\n"
                f"**Next in line:** {r['members'][0]['name']} (Deficit: {r['members'][0]['deficit']:.2f})"
            )
            
            # Chunk members if many
            member_chunks = chunks(r["members"], 10)
            for i, chunk in enumerate(member_chunks):
                if i > 0:
                    # Create a new page for overflow members
                    pages.append(embed)
                    embed = discord.Embed(
                        title=f"📈 Distribution: {r['name']} (cont.)",
                        color=color,
                        timestamp=utcnow()
                    )
                
                mlines = []
                for m in chunk:
                    # Deficit formatting: + means they are behind (deficit), - means they are ahead (surplus)
                    def_str = f"+{m['deficit']:.2f}" if m['deficit'] >= 0 else f"{m['deficit']:.2f}"
                    mlines.append(
                        f"• **{m['name']}**: {m['total']} total ({m['open']} open) | Deficit: `{def_str}`"
                    )
                embed.add_field(name="Member Deficit Analysis", value="\n".join(mlines), inline=False)
            
            pages.append(embed)

        if not pages:
            return await ctx.send("No distribution data available (no members found in roles).")

        if len(pages) == 1:
            return await ctx.send(embed=pages[0])

        session = EmbedPaginatorSession(ctx, *pages)
        await session.run()

    # ── status / toggle / alertchannel / reset ────────────────────────────────

    @checks.has_permissions(PermissionLevel.MOD)
    @ticketallot_.command(name="status")
    async def ta_status(self, ctx):
        """Show plugin status, configuration summary and current open ticket count."""
        guild = self.bot.modmail_guild
        embed = discord.Embed(title="🎫 Ticket Allotment — Status", color=self.bot.main_color)

        embed.add_field(
            name="Plugin",
            value="✅ Enabled" if self.enabled else "❌ Disabled",
            inline=True,
        )
        alert_ch = guild.get_channel(self.alert_channel) if self.alert_channel else None
        embed.add_field(
            name="Alert Channel",
            value=alert_ch.mention if alert_ch else "⚠️ Not configured",
            inline=True,
        )
        embed.add_field(
            name="Assignments",
            value=f"Open: **{len(self._open_assignments())}** | Total: **{len(self.assignments)}**",
            inline=True,
        )
        embed.add_field(
            name="Roles",
            value=(
                f"{len(self.roles)} configured | "
                f"Target Total Share: **{sum(v.get('ratio', 0) for v in self.roles.values())}%**"
            ),
            inline=True,
        )
        rem_state = "✅" if self.auto_reminder_enabled else "❌"
        embed.add_field(
            name="Auto-Reminder",
            value=(
                f"{rem_state} Repeat: **{self.default_repeat}m** | "
                f"Ping: **{self.default_ping}m**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Loops Running",
            value=(
                f"Deadline: {'✅' if self.deadline_check_loop.is_running() else '❌'} | "
                f"Reminder: {'✅' if self.reminder_loop.is_running() else '❌'}"
            ),
            inline=True,
        )
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketallot_.command(name="toggle")
    async def ta_toggle(self, ctx):
        """
        Enable or disable automatic ticket allotment.

        When disabled, new tickets are **not** assigned automatically.
        Deadline tracking and reminders for existing assignments continue.
        """
        self.enabled = not self.enabled
        await self._save()
        state = "enabled ✅" if self.enabled else "disabled ❌"
        await ctx.send(embed=discord.Embed(
            title="Ticket Allotment",
            description=f"Automatic allotment is now **{state}**.",
            color=self.bot.main_color,
        ))

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketallot_.command(name="alertchannel", aliases=["alert"])
    async def ta_alertchannel(self, ctx, channel: discord.TextChannel):
        """
        Set the channel for escalation alerts.

        All configured role mentions are posted here when a ticket exceeds its
        escalation time.

        **Example:** `{prefix}ta alertchannel #staff-escalations`
        """
        self.alert_channel = channel.id
        await self._save()
        await ctx.send(f"✅ Escalation alerts → {channel.mention}.")

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketallot_.command(name="reset")
    async def ta_reset(self, ctx):
        """
        ⚠️ Clear **all** assignment records.

        Role configs, ratios, timers, categories and reminder settings are **preserved**.
        This action is **irreversible**.
        """
        count = len(self.assignments)
        self.assignments = {}
        await self._save()
        await ctx.send(
            f"✅ Cleared **{count}** assignment record(s). All other config preserved."
        )


async def setup(bot):
    await bot.add_cog(TicketAllot(bot))