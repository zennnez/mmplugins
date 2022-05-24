# Credits and orignal author: https://github.com/fourjr/modmail-plugins/blob/master/claim/claim.py
# Slightly modified for Minion_Kadin#2022 (discord)
# Please use the original plugin as this one may cause your bot to nuke the world

import discord
from discord.ext import commands

from core import checks
from core.checks import PermissionLevel
from core.utils import match_user_id


class ClaimThread(commands.Cog):
    """Allows supporters to claim thread by sending claim in the thread channel"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)
        check_reply.fail_msg = 'This thread has been claimed by another user.'
        self.bot.get_command('reply').add_check(check_reply)
        self.bot.get_command('areply').add_check(check_reply)
        self.bot.get_command('fareply').add_check(check_reply)
        self.bot.get_command('freply').add_check(check_reply)

    async def check_claimer(self, ctx, claimer_id):
        cursor = self.db.find({'guild':str(ctx.guild.id)})
        count = 0
        async for x in cursor:
            if 'claimers' in x and str(claimer_id) in x['claimers']:
                count += 1

        config = await self.db.find_one({'_id': 'config'})
        if config and 'limit' in config:
            if count == config['limit']:
                return False
        else:
            raise commands.BadArgument(f"Set Limit first. `{ctx.prefix}claim limit`")

        return True

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.group(name='claim', invoke_without_command=True)
    async def claim_(self, ctx, subscribe: bool = True):
        """Claim a thread"""
        if not ctx.invoked_subcommand:
            if not await self.check_claimer(ctx, ctx.author.id):
                return await ctx.reply(f"Limit reached, can't claim the thread.")

            thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
            recipient_id = match_user_id(ctx.thread.channel.topic)
            recipient = self.bot.get_user(recipient_id) or await self.bot.fetch_user(recipient_id)

            embed = discord.Embed(
                color=self.bot.main_color,
                title="Ticket Claimed",
                description="Please wait as the assigned support agent reviews your case, you will receive a response shortly.",
                timestamp=ctx.message.created_at,
            )
            embed.set_footer(
                text=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.avatar_url)

            description = ""
            if subscribe:
                if str(ctx.thread.id) not in self.bot.config["subscriptions"]:
                    self.bot.config["subscriptions"][str(ctx.thread.id)] = []

                mentions = self.bot.config["subscriptions"][str(ctx.thread.id)]

                if ctx.author.mention in mentions:
                    mentions.remove(ctx.author.mention)
                    description += f"{ctx.author.mention} will __not__ be notified of any message now.\n"
                else:
                    mentions.append(ctx.author.mention)
                    description += f"{ctx.author.mention} will now be notified of all messages received.\n"
                await self.bot.config.update()

            if thread is None:
                await self.db.insert_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id), 'claimers': [str(ctx.author.id)]})
                async with ctx.typing():
                    await recipient.send(embed=embed)
                description += "Please respond to the case asap."
                embed.description = description
                await ctx.reply(embed=embed)
            elif thread and len(thread['claimers']) == 0:
                await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$addToSet': {'claimers': str(ctx.author.id)}})
                async with ctx.typing():
                    await recipient.send(embed=embed)
                description += "Please respond to the case asap."
                embed.description = description
                await ctx.reply(embed=embed)
            else:
                description += "Thread is already claimed"
                embed.description = description
                await ctx.reply(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def unclaim(self, ctx):
        """Unclaim a thread"""
        embed = discord.Embed(color=self.bot.main_color)
        description = ""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$pull': {'claimers': str(ctx.author.id)}})
            description += 'Removed from claimers.\n'

        if str(ctx.thread.id) not in self.bot.config["subscriptions"]:
            self.bot.config["subscriptions"][str(ctx.thread.id)] = []

        mentions = self.bot.config["subscriptions"][str(ctx.thread.id)]

        if ctx.author.mention in mentions:
            mentions.remove(ctx.author.mention)
            await self.bot.config.update()
            description += f"{ctx.author.mention} is now unsubscribed from this thread."

        if description == "":
            description = "Nothing to do"

        embed.description = description
        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def forceclaim(self, ctx, *, member: discord.Member):
        """Make a user froce claim an already claimed thread"""
        if not await self.check_claimer(ctx, member.id):
            return await ctx.reply(f"Limit reached, can't claim the thread.")

        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread is None:
            await self.db.insert_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id), 'claimers': [str(member.id)]})
            await ctx.send(f'{member.name} is added to claimers')
        elif str(member.id) not in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$addToSet': {'claimers': str(member.id)}})
            await ctx.send(f'{member.name} is added to claimers')
        else:
            await ctx.send(f'{member.name} is already in claimers')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def forceunclaim(self, ctx, *, member: discord.Member):
        """Force remove a user from the thread claimers"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread:
            if str(member.id) in thread['claimers']:
                await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$pull': {'claimers': str(member.id)}})
                await ctx.send(f'{member.name} is removed from claimers')
            else:
                await ctx.send(f'{member.name} is not in claimers')
        else:
            await ctx.send(f'No one claimed this thread yet')

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def addclaim(self, ctx, *, member: discord.Member):
        """Adds another user to the thread claimers"""
        if not await self.check_claimer(ctx, member.id):
            return await ctx.reply(f"Limit reached, can't claim the thread.")

        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$addToSet': {'claimers': str(member.id)}})
            await ctx.send('Added to claimers')

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def removeclaim(self, ctx, *, member: discord.Member):
        """Removes a user from the thread claimers"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$pull': {'claimers': str(member.id)}})
            await ctx.send('Removed from claimers')

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def transferclaim(self, ctx, *, member: discord.Member):
        """Removes all users from claimers and gives another member all control over thread"""
        if not await self.check_claimer(ctx, member.id):
            return await ctx.reply(f"Limit reached, can't claim the thread.")

        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$set': {'claimers': [str(member.id)]}})
            await ctx.send('Added to claimers')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def overrideaddclaim(self, ctx, *, member: discord.Member):
        """Allow mods to bypass claim thread check in add"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
        if thread:
            await self.db.find_one_and_update({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)}, {'$addToSet': {'claimers': str(member.id)}})
            await ctx.send('Added to claimers')


    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    @claim_.command(name='limit')
    async def claim_limit_(self, ctx, limit: int):
        """Set max threads a member can claim"""
        if await self.db.find_one({'_id': 'config'}):
            await self.db.find_one_and_update({'_id': 'config'}, {'$set': {'limit': limit}})
        else:
            await self.db.insert_one({'_id': 'config', 'limit': limit})

        await ctx.send(f'Set limit to {limit}')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    @claim_.group(name='bypass', invoke_without_command=True)
    async def claim_bypass_(self, ctx):
        """Manage bypass roles to claim check"""
        if not ctx.invoked_subcommand:
            if (roles_guild:= await self.db.find_one({'_id': 'config'})) and len(roles_guild['bypass_roles']) != 0:
                added = ", ".join(f"`{ctx.guild.get_role(r).name}`" for r in roles_guild['bypass_roles'])
                await ctx.send(f'By-pass roles: {added}')
            else:
                await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    @claim_bypass_.command(name='add')
    async def claim_bypass_add(self, ctx, *roles):
        """Add bypass roles to claim check"""
        bypass_roles = []
        for rol in roles:
            try:
                role = await commands.RoleConverter().convert(ctx, rol)
            except:
                role = discord.utils.find(
                    lambda r: r.name.lower() == rol.lower(), ctx.guild.roles
                )
            if role:
                bypass_roles.append(role)

        if len(bypass_roles) != 0:
            if await self.db.find_one({'_id': 'config'}):
                for role in bypass_roles:
                    await self.db.find_one_and_update({'_id': 'config'}, {'$addToSet': {'bypass_roles': role.id}})
            else:
                await self.db.insert_one({'_id': 'config', 'bypass_roles': [r.id for r in bypass_roles]})
            added = ", ".join(f"`{r.name}`" for r in bypass_roles)
           
        else:
            added = "`None`"

        await ctx.send(f'**Added to by-pass roles**:\n{added}')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    @claim_bypass_.command(name='remove')
    async def claim_bypass_remove(self, ctx, role: discord.Role):
        """Remove a bypass role from claim check"""
        roles_guild = await self.db.find_one({'_id': 'config'})
        if roles_guild and role.id in roles_guild['bypass_roles']:
            await self.db.find_one_and_update({'_id': 'config'}, {'$pull': {'bypass_roles': role.id}})
            await ctx.send(f'**Removed from by-pass roles**:\n`{role.name}`')
        else:
            await ctx.send(f'`{role.name}` is not in by-pass roles')

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def overridereply(self, ctx, *, msg: str=""):
        """Allow mods to bypass claim thread check in reply"""
        await ctx.invoke(self.bot.get_command('reply'), msg=msg)

async def check_reply(ctx):
    thread = await ctx.bot.get_cog('ClaimThread').db.find_one({'thread_id': str(ctx.thread.channel.id), 'guild': str(ctx.guild.id)})
    if thread and len(thread['claimers']) != 0:
        in_role = False
        if config:= await ctx.bot.get_cog('ClaimThread').db.find_one({'_id': 'config'}):
            roles = [ctx.guild.get_role(r) for r in config['bypass_roles'] if ctx.guild.get_role(r) is not None]
            for role in roles:
                if role in ctx.author.roles:
                    in_role = True
        return ctx.author.bot or in_role or str(ctx.author.id) in thread['claimers']
    return True


def setup(bot):
    bot.add_cog(ClaimThread(bot))