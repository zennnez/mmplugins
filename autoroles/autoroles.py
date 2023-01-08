# created for Uncle LYHME#0001 (discord)

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel

class AutoRoles(commands.Cog):
    """Auto roles"""
    default_global = {
        "enabled": False,
        "add": True,
        "remove": False,
        "roles": {},
    }
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.task = self.bot.loop.create_task(self.cog_load())
        self.global_config = None

    async def cog_load(self):
        self.global_config = await self.db.find_one({"_id": "autoroles"})
        if self.global_config is None:
            self.global_config = self.default_global
            await self.config_update()
            self.global_config = await self.db.find_one({"_id": "autoroles"})

    async def config_update(self):
        await self.db.find_one_and_update(
            {"_id": "autoroles"},
            {"$set": self.global_config},
            upsert=True,
        )

    def cog_unload(self):
        if self.task:
            self.task.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        member = after
        if member.bot or not self.global_config['enabled']:
            return
        
        added_roles = [r for r in after.roles if r not in before.roles]
        removed_roles = [r for r in before.roles if r not in after.roles]

        if len(removed_roles) > 0 and self.global_config['remove']:
            for role in removed_roles:
                if str(role.id) not in self.global_config['roles']:
                    continue

                for v in self.global_config['roles'][str(role.id)]:
                    c_role = member.guild.get_role(v)
                    if c_role:
                        await after.remove_roles(c_role)
        
        if len(added_roles) > 0 and self.global_config['add']:
            for role in added_roles:
                if str(role.id) not in self.global_config['roles']:
                    continue

                for v in self.global_config['roles'][str(role.id)]:
                    c_role = member.guild.get_role(v)
                    if c_role:
                        await after.add_roles(c_role)

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def autoroles(self, ctx):
        """Add/remove multiple auto_roles when a member adds/removes another (one) role"""
        await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.MOD)
    @autoroles.command(name='add')
    async def autoroles_add(self, ctx, role: discord.Role, auto_role: discord.Role):
        """Add auto_role to a role"""

        if str(role.id) in self.global_config['roles']:
            if auto_role.id in self.global_config['roles'][str(role.id)]:
                return await ctx.send(f"{auto_role.name} is already in {role} list")

            self.global_config['roles'][str(role.id)].append(auto_role.id)
        else:
            self.global_config['roles'][str(role.id)] = [auto_role.id]

        await self.config_update()
        self.global_config = await self.db.find_one({"_id": "autoroles"})
        await ctx.send(
            embed=await self.generate_embed(
                'Done', f'Added {auto_role.name} to {role.name} list'
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @autoroles.command(name='remove')
    async def autoroles_remove(self, ctx, role: discord.Role, auto_role: discord.Role):
        """Remove auto_role from a role"""

        if str(role.id) not in self.global_config['roles']:
            return await ctx.send(f"{role.name} is not set as parent role.")

        if auto_role.id not in self.global_config['roles'][str(role.id)]:
            return await ctx.send(f"{auto_role.name} is not in {role} list")

        self.global_config['roles'][str(role.id)].remove(auto_role.id)
        await self.config_update()
        self.global_config = await self.db.find_one({"_id": "autoroles"})
        await ctx.send(
            embed=await self.generate_embed(
                'Done', f'Removed {auto_role.name} from {role.name} list'
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @autoroles.command(name='toggle')
    async def autoroles_toggle(self, ctx):
        """Toggle the cog no/off"""
        self.global_config['enabled'] = not self.global_config['enabled']
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Done', f"**Status:** {'Enabled' if self.global_config['enabled'] else 'Disabled'}"
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @autoroles.command(name='adding')
    async def autoroles_adding(self, ctx, yes_no: bool):
        """
        Enable/Disable auto_roles adding
        """
        self.global_config['add'] = yes_no
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Adding', yes_no
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @autoroles.command(name='removing')
    async def autoroles_removing(self, ctx, yes_no: bool):
        """
        Enable/Disable auto_roles removal
        """
        self.global_config['remove'] = yes_no
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Removing', yes_no
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
    await bot.add_cog(AutoRoles(bot))