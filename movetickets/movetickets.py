# created for DanielH#1000 (discord)

import discord
import asyncio
from discord.ext import commands, tasks
from core import checks
from core.checks import PermissionLevel
from core.paginator import EmbedPaginatorSession
from typing import Union

class MoveTickets(commands.Cog):
    """Move tickets between 2 categories, depending on the message author"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)
        self.categoryID = int()
        self.category = None
        self.enabled = bool()

    async def cog_load(self):
        config = await self.db.find_one({"_id": "config"})
        if config is None:
            await self.db.find_one_and_update({"_id": "config"},
                {"$set": {
                    "category": int(),
                    "enabled": False}
                }, upsert=True)

            config = await self.db.find_one({"_id": "config"})

        self.categoryID = config.get("category", int())
        if self.categoryID != 0:
            self.category = await self.bot.fetch_channel(self.categoryID)
        self.enabled = config.get("enabled", bool())

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "category": self.categoryID,
                "enabled": self.enabled}
            }, upsert=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        author = message.author
        channel = message.channel
        if author.id == self.bot.user.id:
            return
        if author.bot:
            return
        if not self.enabled:
            return
        if not self.category:
            return

        if isinstance(channel, discord.TextChannel) and channel.category_id == int(self.bot.config["main_category_id"]):
            t_ch = await self.bot.api.get_log(channel.id)
            if t_ch:
                await channel.move(beginning=True, category=self.category)
                await asyncio.sleep(0.3)

        elif isinstance(channel, discord.DMChannel):
            thread = await self.bot.threads.find(recipient=author)
            if thread:
                await thread.channel.move(end=True, category=self.bot.main_category)
                await asyncio.sleep(0.3)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.group(name='movetickets', invoke_without_command=True)
    async def movetickets_(self, ctx):
        """Move tickets commands"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @movetickets_.command(name='toggle')
    async def movetickets_toggle(self, ctx, yes_no: bool):
        """Enable/Disable the plugin"""
        self.enabled = yes_no
        await self._update_config()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @movetickets_.command(name='category')
    async def movetickets_add(self, ctx, categoryID: int):
        """Set the category to move channels to"""
        category = await self.bot.fetch_channel(categoryID)
        if not isinstance(category, discord.CategoryChannel):
            return await ctx.reply("This is not a category's ID")
        self.categoryID = category.id
        await self._update_config()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @movetickets_.command(name='remove')
    async def movetickets_remove(self, ctx):
        """UnSet the category to move channels to"""
        if self.categoryID:
            self.categoryID = 0
            await self._update_config()
            await ctx.message.add_reaction('✅')
        else:
            await ctx.reply('ID not set!')

async def setup(bot):
    await bot.add_cog(MoveTickets(bot))