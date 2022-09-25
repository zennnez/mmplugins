# created for TheArxOfTheNel#4007 (discord)

import discord
import time
from discord.ext import commands, tasks
from core import checks
from core.checks import PermissionLevel
from core.paginator import EmbedPaginatorSession
from typing import Union

class Mentions(commands.Cog):
    """Reply to role/member mentions with an embed message"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)
        self.role_msg = dict()
        self.ignore_ = list()
        self.ignore = list()
        self.enabled = bool()
        self.reference = bool()
        self.cooldown_ = dict()
        self.cooldown = int()
        self.task = self.bot.loop.create_task(self.cog_load())

    async def cog_load(self):
        config = await self.db.find_one({"_id": "config"})
        if config is None:
            await self.db.find_one_and_update({"_id": "config"},
                {"$set": {
                    "role_msg": dict(),
                    "enabled": False,
                    "reference": False,
                    "cooldown": int(),
                    "ignore": []}
                }, upsert=True)

            config = await self.db.find_one({"_id": "config"})

        self.role_msg = config.get("role_msg", dict())
        self.enabled = config.get("enabled", bool())
        self.reference = config.get("reference", bool())
        self.cooldown = config.get("cooldown", int())
        self.ignore_ = config.get("ignore", list())
        self.ignore = [self.bot.guild.get_role(r) for r in self.ignore_ if self.bot.guild.get_role(r) is not None]

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "role_msg": self.role_msg,
                "enabled": self.enabled,
                "reference": self.reference,
                "cooldown": self.cooldown,
                "ignore": self.ignore_}
            }, upsert=True)

    def cog_unload(self):
        self.task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message):
        author = message.author
        guild = message.guild
        if not isinstance(message.channel, discord.TextChannel):
            return
        if author.id == self.bot.user.id:
            return
        if author.bot:
            return
        if len(message.clean_content) == 0:
            return
        if not self.enabled:
            return
        if len(self.role_msg) == 0:
            return

        for r in author.roles:
            if r in self.ignore:
                return

        if message.role_mentions:
            for role in message.role_mentions:
                if str(role.id) in self.role_msg:
                    cooldown = self.cooldown_.setdefault(guild.id, {}).get(
                        role.id, 0
                    )
                    if (time.time() - cooldown) < self.cooldown:
                        continue

                    await message.reply(embed=discord.Embed.from_dict(self.role_msg[str(role.id)]))
                    self.cooldown_[guild.id][role.id] = time.time()
                    break
            
        elif message.mentions:
            for member in message.mentions:
                if str(member.id) in self.role_msg:
                    cooldown = self.cooldown_.setdefault(guild.id, {}).get(
                        member.id, 0
                    )
                    if (time.time() - cooldown) < self.cooldown:
                        continue

                    await message.reply(embed=discord.Embed.from_dict(self.role_msg[str(member.id)]))
                    self.cooldown_[guild.id][member.id] = time.time()
                    break

                for role in member.roles:
                    if str(role.id) in self.role_msg:
                        cooldown = self.cooldown_.setdefault(guild.id, {}).get(
                            member.id, 0
                        )
                        if (time.time() - cooldown) < self.cooldown:
                            continue
                        await message.reply(embed=discord.Embed.from_dict(self.role_msg[str(role.id)]))
                        self.cooldown_[guild.id][member.id] = time.time()
                        break

        elif self.reference and message.reference:
            message_reference = message.reference
            if not (message_reference and message_reference.resolved and
                    isinstance(message_reference.resolved, discord.Message)):
                return
            member = message_reference.resolved.author

            if str(member.id) in self.role_msg:
                cooldown = self.cooldown_.setdefault(guild.id, {}).get(
                    member.id, 0
                )
                if (time.time() - cooldown) < self.cooldown:
                    return
                await message.reply(embed=discord.Embed.from_dict(self.role_msg[str(member.id)]))
                self.cooldown_[guild.id][member.id] = time.time()
                return

            for role in member.roles:
                if str(role.id) in self.role_msg:
                    cooldown = self.cooldown_.setdefault(guild.id, {}).get(
                        member.id, 0
                    )
                    if (time.time() - cooldown) < self.cooldown:
                        continue
                    await message.reply(embed=discord.Embed.from_dict(self.role_msg[str(role.id)]))
                    self.cooldown_[guild.id][member.id] = time.time()
                    break

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.group(name='mentions', invoke_without_command=True)
    async def mentions_(self, ctx):
        """Mention commands"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='toggle')
    async def mentions_toggle(self, ctx, yes_no: bool):
        """Enable/Disable the plugin"""
        self.enabled = yes_no
        await self._update_config()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='cooldown')
    async def mentions_cooldown(self, ctx, seconds: int):
        """Enable/Disable the plugin"""
        self.cooldown = seconds
        await self._update_config()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='add')
    async def mentions_add(self, ctx, role_member: Union[discord.Member, discord.Role], embed_message: discord.Message):
        """
        Add a reply to a role/member mention
        `role_member` = a role or member
        `embed_message` = a message with embed
        """
        if str(role_member.id) in self.role_msg:
            await ctx.reply('Already in database')
        else:
            embeds = embed_message.embeds
            if not embeds:
                raise commands.BadArgument('That message has no embeds.')

            embed = embed_message.embeds[0]
            self.role_msg[str(role_member.id)] = embed.to_dict()
            await self._update_config()
            await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='remove')
    async def mentions_remove(self, ctx, role_member: Union[discord.Member, discord.Role]):
        """
        Remove a role/member mention from database
        `role_member` = a role or member
        """
        if str(role_member.id) in self.role_msg:
            del self.role_msg[str(role_member.id)]
            await self._update_config()
            await ctx.message.add_reaction('✅')
        else:
            await ctx.reply('Not found on database!')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.group(name='ignore', invoke_without_command=True)
    async def mentions_ignore(self, ctx, role: discord.Role):
        """Ignore these roles from mention replies"""
        if not ctx.invoked_subcommand:
            if role.id in self.ignore_:
                self.ignore_.remove(role.id)
                if role in self.ignore:
                    self.ignore.remove(role)
                await self._update_config()
                await ctx.send(f"Removed {role.name} from ignore list.")
            else:
                self.ignore_.append(role.id)
                if role not in self.ignore:
                    self.ignore.append(role)
                await self._update_config()
                await ctx.send(f"Added {role.name} to ignore list.")

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_ignore.command(name='list')
    async def mentions_ignore_list(self, ctx):
        """List all the ignored roles saved on database"""
        embeds = [
            discord.Embed(
                title=f"Ignored List",
                color=self.bot.main_color,
                description="",
            )
        ]
        entries = 0
        embed = embeds[0]
        index = 0
        try:
            for hmm in self.ignore:
                index += 1
                hm = f"{index}. {hmm.name}\n"
                if entries == 20:
                    embed = discord.Embed(
                        title=f"Ignored List (Continued)",
                        color=self.bot.main_color,
                        description=hm,
                    )
                    embeds.append(embed)
                    entries = 1
                else:
                    embed.description += hm
                    entries += 1

            if len(embeds) > 0:
                session = EmbedPaginatorSession(ctx, *embeds)
                await session.run()
            else:
                embed=discord.Embed(title='No roles in db yet', color=self.bot.error_color)
                await ctx.reply(embed=embed)
        except Exception as e:
            embed=discord.Embed(title='Failed', color=self.bot.error_color)
            embed.set_footer(text=str(e))
            await ctx.reply(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='replies')
    async def mentions_replies(self, ctx, yes_no: bool):
        """Enable/Disable the plugin for __replied messages__
        i.e. If you set `{prefix}mentions replied no`: Plugin will work only for `@mentions`
        If you set `{prefix}mentions replied yes`: Plugin will work for `@mentions` and `replied messages`
        """
        self.reference = yes_no
        await self._update_config()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='list')
    async def mentions_list(self, ctx):
        """List all the current roles/members saved on database"""
        embeds = [
            discord.Embed(
                title=f"Mention List",
                color=self.bot.main_color,
                description="",
            )
        ]
        entries = 0
        embed = embeds[0]
        index = 0
        try:
            for k in self.role_msg:
                hmm = ctx.guild.get_role(int(k)) or ctx.guild.get_member(int(k))
                if not hmm:
                    del self.role_msg[str(k)]
                    await self._update_config()
                    continue
                index += 1
                hm = f"{index}. {hmm}\n"
                if entries == 20:
                    embed = discord.Embed(
                        title=f"Mention List (Continued)",
                        color=self.bot.main_color,
                        description=hm,
                    )
                    embeds.append(embed)
                    entries = 1
                else:
                    embed.description += hm
                    entries += 1

            if len(embeds) > 0:
                session = EmbedPaginatorSession(ctx, *embeds)
                await session.run()
            else:
                embed=discord.Embed(title='No roles in db yet', color=self.bot.error_color)
                await ctx.reply(embed=embed)
        except Exception as e:
            embed=discord.Embed(title='Failed', color=self.bot.error_color)
            embed.set_footer(text=str(e))
            await ctx.reply(embed=embed)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @mentions_.command(name='view')
    async def mentions_view(self, ctx, role_member: Union[discord.Member, discord.Role]):
        """View the embed response to a role/member mention"""
        if str(role_member.id) in self.role_msg:
            embed=discord.Embed.from_dict(self.role_msg[str(role_member.id)])
            await ctx.send(embed=embed)
        else:
            await ctx.reply('Not found on database!')

async def setup(bot):
    await bot.add_cog(Mentions(bot))