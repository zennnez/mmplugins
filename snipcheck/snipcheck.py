# created for Zino#3646 (discord)

import discord
from discord.ext import commands
from typing import Union

from core import checks, utils
from core.models import PermissionLevel

class SnipCheck(commands.Cog):
    """
    Check Snipets and Alias permissions before run
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.snips = None
        self.enabled = None
        self.snip_check()

    async def cog_load(self):
        await self.check_dbcache()

    async def check_dbcache(self):
        config = await self.db.find_one({"_id": "SnipCheck"})
        if not config:
            await self.db.find_one_and_update({"_id": "SnipCheck"}, {"$set": {'enabled': True, 'snips': dict()}}, upsert=True)
            config = await self.db.find_one({"_id": "SnipCheck"})
        self.snips = config.get("snips", dict())
        self.enabled = config.get("enabled", bool())

    def snip_check(self):
        @self.bot.before_invoke
        async def bot_before_invoke(ctx):
            if not self.enabled:
                return

            command = ctx.message.content.lower()
            if command.startswith(ctx.clean_prefix):
                command = command[len(ctx.clean_prefix):]

            if val:= self.bot.snippets.get(command):
                if command in self.snips:
                    member_or_roles = self.snips[command]
                    if ctx.author.id in member_or_roles:
                        return
                    for role in ctx.author.roles:
                        if role.id in member_or_roles:
                            return
                    raise commands.BadArgument(f"You are not allowed to use {command} snippet")

            if val:= self.bot.aliases.get(command):
                if values:= utils.parse_alias(val):
                    if command in self.snips:
                        member_or_roles = self.snips[command]
                        if ctx.author.id in member_or_roles:
                            return
                        for role in ctx.author.roles:
                            if role.id in member_or_roles:
                                return
                        raise commands.BadArgument(f"You are not allowed to use {command} alias")

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def snipcheck(self, ctx: commands.Context):
        """SnipCheck checks if the triggered alias/snippet is enabled for the member/role who ran it."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.MOD)
    @snipcheck.command(name='toggle')
    async def snipcheck_toggle(self, ctx: commands.Context, on_off: bool):
        """Enable/Disable checking."""
        
        await self.db.find_one_and_update({"_id": "SnipCheck"}, {"$set": {'enabled': on_off}}, upsert=True)
        self.enabled = on_off
        await ctx.reply('Enabled' if on_off else 'Disabled')

    @checks.has_permissions(PermissionLevel.MOD)
    @snipcheck.command(name='add')
    async def snipcheck_add(self, ctx: commands.Context, alias: str, member_or_role: Union[discord.Member, discord.Role]):
        """Add a role or member to the alias/snippet allowed list."""

        if alias in self.bot.aliases or alias in self.bot.snippets:
            if alias in self.snips:
                if member_or_role.id in self.snips[alias]:
                    return await ctx.reply(f"`{member_or_role.name}` is already in the `{alias}` list")
                else:
                    self.snips[alias].append(member_or_role.id)
                    await ctx.reply(f"Added `{member_or_role}` to `{alias}` list")
            else:
                self.snips[alias] = [member_or_role.id]
                await ctx.reply(f"Added `{member_or_role}` to `{alias}` list")

            await self.db.find_one_and_update({"_id": "SnipCheck"}, {"$set": {'snips': self.snips}}, upsert=True)

        else:
            return await ctx.reply(f"`{alias}` alias/snippet doesn't exist")

    @checks.has_permissions(PermissionLevel.MOD)
    @snipcheck.command(name='remove')
    async def snipcheck_remove(self, ctx: commands.Context, alias: str, member_or_role: Union[discord.Member, discord.Role]):
        """Remove a role or member from the alias/snippet allowed list."""

        if alias in self.snips:
            if member_or_role.id in self.snips[alias]:
                self.snips[alias].remove(member_or_role.id)
                if len(self.snips[alias]) == 0:
                    self.snips = {k:v for k,v in self.snips.items() if k != alias}
                await self.db.find_one_and_update({"_id": "SnipCheck"}, {"$set": {'snips': self.snips}}, upsert=True)
                await ctx.reply(f"Removed `{member_or_role}` from `{alias}` list")
            else:
                await ctx.reply(f"`{member_or_role.name}` is not in `{alias}` list")
        else:
            await ctx.reply(f"`{alias}` is not in enabled list")

    @checks.has_permissions(PermissionLevel.MOD)
    @snipcheck.command(name='view')
    async def snipcheck_view(self, ctx: commands.Context, alias: str):
        """View alias/snippets perm rules."""
        if alias not in self.snips:
            return await ctx.send("Alias/Snippet not in the list")

        embeds = []
        roles = []
        members = []
        not_found = []
        for k in self.snips[alias]:
            member = ctx.guild.get_member(k)
            if member:
               members.append(member) 
            else:
                role = ctx.guild.get_role(k)
                if role:
                    roles.append(role)
                else:
                    not_found.append(k)

        embed = discord.Embed(color=self.bot.main_color)
        embed.title = alias
        if len(roles) != 0:
            embed.add_field(name="**Roles:**", value=f"{', '.join(role.name for role in roles)}", inline=False)
        
        if len(members) != 0:
            embed.add_field(name="Members", value=f"{', '.join(member.name for member in members)}", inline=False)

        if len(not_found) != 0:
            embed.add_field(name="Not found", value=f"{', '.join(k for k in not_found)}")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(SnipCheck(bot))