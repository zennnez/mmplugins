import discord

from discord.ext import commands
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core import checks
from core.models import getLogger

logger = getLogger(__name__)

class InviteRole(commands.Cog):
    _id = "config"
    default_config = {
        "invite_counts": dict(),
        "invite_role": int(),
    }

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self._config_cache: Dict[str, Any] = {}
        self.invite_cache: Dict[int, Set[discord.Invite]] = {}

    async def cog_load(self):
        await self.populate_config_cache()
        await self.populate_invite_cache()

    async def populate_config_cache(self):
        db_config = await self.db.find_one({"_id": self._id})
        if db_config is None:
            db_config = {}

        to_update = False
        for guild in self.bot.guilds:
            config = db_config.get(str(guild.id))
            if config is None:
                config = {k: v for k, v in self.default_config.items()}
                to_update = True
            self._config_cache[str(guild.id)] = config

            invite_role = discord.utils.get(guild.roles, name='Inviter')
            if not invite_role:
                invite_role = await guild.create_role(
                    name='Inviter', color=discord.Color(0x818689), reason='Invite role'
                )
            config.update(dict(invite_role=invite_role.id))

        if to_update:
            await self.config_update()

    def guild_config(self, guild_id: str):
        config = self._config_cache.get(guild_id)
        if config is None:
            config = {k: v for k, v in self.default_config.items()}
            self._config_cache[guild_id] = config

        return config

    async def config_update(self):
        await self.db.find_one_and_update(
            {"_id": self._id},
            {"$set": self._config_cache},
            upsert=True,
        )

    async def populate_invite_cache(self):
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            config = self.guild_config(str(guild.id))

            logger.debug("Caching invites for guild (%s).", guild.name)
            self.invite_cache[guild.id] = {inv for inv in await guild.invites()}

    async def get_used_invite(self, member: discord.Member) -> List[Optional[discord.Invite]]:
        guild = member.guild
        new_invite_cache = {i for i in await guild.invites()}
        predicted_invites = []
        found = False

        for _inv in self.invite_cache[guild.id]:
            if _inv not in new_invite_cache:
                predicted_invites.append(_inv)
                continue

            used_inv = next(
                (inv for inv in new_invite_cache if inv.id == _inv.id and inv.uses > _inv.uses),
                None,
            )
            if used_inv is not None:
                found = True
                predicted_invites = [used_inv]
                break

        if predicted_invites and not found:
            for inv in list(predicted_invites):
                if inv.max_age:
                    expired = (
                        datetime.timestamp(inv.created_at) + inv.max_age
                    ) < member.joined_at.timestamp()
                else:
                    expired = False
                if not all((inv.max_uses == (inv.uses + 1), not expired)):
                    predicted_invites.remove(inv)

            if len(predicted_invites) == 1:
                predicted_invites[0].uses += 1

        self.invite_cache[guild.id] = new_invite_cache
        return predicted_invites

    async def save_user_data(
        self, member: discord.Member, predicted_invites: List[discord.Invite]
    ):
        if not predicted_invites:
            return

        user_data = {
            "inviter": "\n".join(str(getattr(invite.inviter, "id", "None")) for invite in predicted_invites),
            "multi": len(predicted_invites) > 1,
        }

        await self.db.find_one_and_update(
            {"guild_id": member.guild.id, "user_id": member.id}, {"$set": user_data}, upsert=True
        )

    async def remove_user_data(self, member: discord.Member):
        await self.db.find_one_and_delete({"guild_id": member.guild.id, "user_id": member.id})

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        config = self.guild_config(str(member.guild.id))
        predicted_invites = await self.get_used_invite(member)
        if not predicted_invites:
            return

        await self.save_user_data(member, predicted_invites)

        self.counts = config.get("invite_counts", dict())
        inviter = member.guild.get_member(int("\n".join(str(getattr(invite.inviter, "id", "None")) for invite in predicted_invites)))

        totalInvites = 0
        if str(inviter.id) in self.counts:
            totalInvites = self.counts[str(inviter.id)]

        totalInvites += 1
        self.counts[str(inviter.id)] = totalInvites

        await self.config_update()

        if totalInvites != 0:
            invite_role = member.guild.get_role(config.get("invite_role", dict()))
            if invite_role not in inviter.roles:
                await inviter.add_roles(invite_role)
                logger.info(f"{inviter} Got {invite_role} role.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return

        config = self.guild_config(str(member.guild.id))

        user_db = await self.db.find_one({"guild_id": member.guild.id, "user_id": member.id})
        if not user_db:
            return
        if user_db and user_db.get("multi"):
            return logger.info("More than 1 used invites were retrieved.")

        self.counts = config.get("invite_counts", dict())
        inviter = member.guild.get_member(int(user_db["inviter"]))
        totalInvites = self.counts[str(inviter.id)]
        totalInvites -= 1
        self.counts[str(inviter.id)] = totalInvites
        if totalInvites == 0:
            invite_role = member.guild.get_role(config.get("invite_role", dict()))
            if invite_role in inviter.roles:
                await inviter.remove_roles(invite_role)
                logger.info(f"{inviter} Lost {invite_role} role.")

        await self.config_update()
        await self.remove_user_data(member)

async def setup(bot):
    await bot.add_cog(InviteRole(bot))