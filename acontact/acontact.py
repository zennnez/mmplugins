#made for Jynkofist#7435 (discord)

import asyncio
import discord
from discord.ext import commands
from typing import Union

from core import checks, utils
from core.models import DMDisabled, PermissionLevel, SimilarCategoryConverter
from core.paginator import EmbedPaginatorSession

class Creator:
    def __init__(self):
        pass

class AContact(commands.Cog):
    __slots__ = ("mention", "id", "discriminator", "display_avatar", "avatar", "name", "nickname", "server_avatar", "roles", "server", "permissions")

    def __init__(self, bot):
        self.bot = bot

    @commands.command(usage="<user> [category] [options]")
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def acontact(
        self,
        ctx,
        users: commands.Greedy[Union[discord.Member, discord.User, discord.Role]],
        *,
        category: Union[SimilarCategoryConverter, str] = None,
        manual_trigger=True,
    ):
        """
        Create a thread with a specified member, marking the mod be Anonymous.

        If `category` is specified, the thread
        will be created in that specified category.

        `category`, if specified, may be a category ID, mention, or name.
        `users` may be a user ID, mention, or name. If multiple users are specified, a group thread will start.
        A maximum of 5 users are allowed.
        `options` can be `silent` or `silently`.
        """
        silent = False
        if isinstance(category, str):
            category = category.split()

            # just check the last element in the list
            if category[-1].lower() in ("silent", "silently"):
                silent = True
                # remove the last element as we no longer need it
                category.pop()

            category = " ".join(category)
            if category:
                try:
                    category = await SimilarCategoryConverter().convert(
                        ctx, category
                    )  # attempt to find a category again
                except commands.BadArgument:
                    category = None

            if isinstance(category, str):
                category = None

        errors = []
        for u in list(users):
            if isinstance(u, discord.Role):
                users += u.members
                users.remove(u)

        for u in list(users):
            exists = await self.bot.threads.find(recipient=u)
            if exists:
                errors.append(f"A thread for {u} already exists.")
                if exists.channel:
                    errors[-1] += f" in {exists.channel.mention}"
                errors[-1] += "."
                users.remove(u)
            elif u.bot:
                errors.append(f"{u} is a bot, cannot add to thread.")
                users.remove(u)
            elif await self.bot.is_blocked(u):
                ref = f"{u.mention} is" if ctx.author != u else "You are"
                errors.append(f"{ref} currently blocked from contacting {self.bot.user.name}.")
                users.remove(u)

        if len(users) > 5:
            errors.append("Group conversations only support 5 users.")
            users = []

        if errors or not users:
            if not users:
                # no users left
                title = "Thread not created"
            else:
                title = None

            if manual_trigger:  # not react to contact
                embed = discord.Embed(title=title, color=self.bot.error_color, description="\n".join(errors))
                await ctx.send(embed=embed, delete_after=10)

            if not users:
                # end
                return

        creator = Creator()
        for i in ctx.author.__slots__:
            setattr(creator, i, getattr(ctx.author, i))

        setattr(creator, 'name', "Staff")
        setattr(creator, 'mention', "Staff")
        setattr(creator, 'id', "Staff")
        setattr(creator, 'discriminator', 0)
        setattr(creator, 'display_avatar', getattr(ctx.guild.me, 'display_avatar'))

        thread = await self.bot.threads.create(
            recipient=users[0],
            creator=creator,
            category=category,
            manual_trigger=manual_trigger,
        )

        if thread.cancelled:
            return

        if self.bot.config["dm_disabled"] in (DMDisabled.NEW_THREADS, DMDisabled.ALL_THREADS):
            logger.info("Contacting user %s when Eve DM is disabled.", users[0])

        if not silent and not self.bot.config.get("thread_contact_silently"):
            if creator.id == users[0].id:
                description = self.bot.config["thread_creation_self_contact_response"]
            else:
                description = self.bot.formatter.format(
                    self.bot.config["thread_creation_contact_response"], creator=creator
                )

            em = discord.Embed(
                title=self.bot.config["thread_creation_contact_title"],
                description=description,
                color=self.bot.main_color,
            )
            if self.bot.config["show_timestamp"]:
                em.timestamp = discord.utils.utcnow()
            em.set_footer(text=f"{creator.name}", icon_url=creator.display_avatar.url)

            for u in users:
                await u.send(embed=em)

        embed = discord.Embed(
            title="Created Thread",
            description=f"Thread started by {creator.mention} for {', '.join(u.mention for u in users)}.",
            color=self.bot.main_color,
        )
        await thread.wait_until_ready()

        if users[1:]:
            await thread.add_users(users[1:])

        await thread.channel.send(embed=embed)

        if manual_trigger:
            sent_emoji, _ = await self.bot.retrieve_emoji()
            await self.bot.add_reaction(ctx.message, sent_emoji)
            await asyncio.sleep(5)
            await ctx.message.delete()

async def setup(bot):
    await bot.add_cog(AContact(bot))