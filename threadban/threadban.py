# created for gumby#0203 (discord)

import discord
from discord.ext import commands
from typing import Union
from core import checks
from core.models import PermissionLevel

class ThreadBan(commands.Cog):
    """Whitelist a member or role for using modmail"""
    default_global = {
        "enabled": True,
        "whitelist": [],
    }
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.task = self.bot.loop.create_task(self.load_db())
        self.global_config = None

    async def load_db(self):
        self.global_config = await self.db.find_one({"_id": "threadban"})
        if self.global_config is None:
            self.global_config = self.default_global
            await self.config_update()
            self.global_config = await self.db.find_one({"_id": "threadban"})

    async def config_update(self):
        await self.db.find_one_and_update(
            {"_id": "threadban"},
            {"$set": self.global_config},
            upsert=True,
        )

    def cog_unload(self):
        self.task.cancel()

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, creator, category, initial_message):
        if initial_message.author.bot:
            return

        if not self.global_config['enabled']:
            return

        close = True
        if initial_message.author.id in self.global_config['whitelist']:
            close = False
        
        author = self.bot.modmail_guild.get_member(initial_message.author.id)
        if author:
            whitelist_roles = [self.bot.modmail_guild.get_role(i) for i in self.global_config['whitelist'] if self.bot.modmail_guild.get_role(i) is not None]

            for r in whitelist_roles:
                if r in author.roles:
                    close = False
                
        if close:
            message = 'Modmail is not enabled for you, contact staff in the guild instead.'
            await thread.close(closer=self.bot.modmail_guild.me, message=message)

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def threads(self, ctx, member: discord.Member):
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.MOD)
    @threads.command(name='add')
    async def threads_add(self, ctx, mem_or_role: Union[discord.Member, discord.Role]):
        """Add member or role to the whitelist"""
        if mem_or_role.id not in self.global_config['whitelist']:
            self.global_config['whitelist'].append(mem_or_role.id)
            await self.config_update()
            await ctx.send(
                embed=await self.generate_embed(
                    'Done', f"Added {mem_or_role.name} to whitelist!"
                )
            )

        else:
            await ctx.send(
                embed=await self.generate_embed(
                    'Error', f"{mem_or_role.name} is already in whitelist!"
                )
            )

    @checks.has_permissions(PermissionLevel.MOD)
    @threads.command(name='remove')
    async def threads_remove(self, ctx, mem_or_role: Union[discord.Member, discord.Role]):
        """Remove member or role from the whitelist"""
        if mem_or_role.id in self.global_config['whitelist']:
            self.global_config['whitelist'].remove(mem_or_role.id)
            await self.config_update()
            await ctx.send(
                embed=await self.generate_embed(
                    'Done', f"Removed {mem_or_role.name} from whitelist!"
                )
            )

        else:
            await ctx.send(
                embed=await self.generate_embed(
                    'Error', f"{mem_or_role.name} is not in whitelist!"
                )
            )

    @checks.has_permissions(PermissionLevel.MOD)
    @threads.command(name='toggle')
    async def threads_toggle(self, ctx):
        """Toggle whitelist no/off"""
        self.global_config['enabled'] = not self.global_config['enabled']
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Done', f"**Status:** {'Enabled' if self.global_config['enabled'] else 'Disabled'}"
            )
        )

    @staticmethod
    async def generate_embed(title: str, description: str):
        embed = discord.Embed()
        embed.colour = 0x2f3136
        embed.title = title
        embed.description = description

        return embed

async def setup(bot):
    await bot.add_cog(ThreadBan(bot))