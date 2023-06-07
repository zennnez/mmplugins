#taken from: https://github.com/phenom4n4n/phen-cogs/tree/master/lock

from copy import copy
from typing import List, Literal, Optional, Union, Sequence

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel

from .converters import ChannelToggle, LockableChannel, LockableRole

from babel.lists import format_list as babel_list

def humanize_list(
    items: Sequence[str], *, style: str = "standard"
) -> str:
    return babel_list(items, style=style)

def get_audit_reason(author: discord.Member, reason: str = None, *, shorten: bool = False):
    """Construct a reason to appear in the audit log.

    Parameters
    ----------
    author : discord.Member
        The author behind the audit log action.
    reason : str
        The reason behind the audit log action.
    shorten : bool
        When set to ``True``, the returned audit reason string will be
        shortened to fit the max length allowed by Discord audit logs.

    Returns
    -------
    str
        The formatted audit log reason.

    """
    audit_reason = (
        "Action requested by {} (ID {}). Reason: {}".format(author, author.id, reason)
        if reason
        else "Action requested by {} (ID {}).".format(author, author.id)
    )
    if shorten and len(audit_reason) > 512:
        audit_reason = f"{audit_reason[:509]}..."
    return audit_reason

def inline(text: str) -> str:
    """Get the given text as inline code.

    Parameters
    ----------
    text : str
        The text to be marked up.

    Returns
    -------
    str
        The marked up text.

    """
    if "`" in text:
        return f"``{text}``"
    else:
        return f"`{text}`"

class Lock(commands.Cog):
    """
    Advanced channel and server locking.
    """
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.bot_has_permissions(manage_roles=True)
    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MOD)
    async def lock(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
    ):
        """
        Lock a channel.

        Provide a role or member if you would like to lock it for them.
        You can only lock a maximum of 10 things at once.

        **Examples:**
        `{prefix}lock #general`
        `{prefix}lock 123456789000000 @members`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:  # when another bot is faster to lock
            return

        if not channel:
            channel = ctx.channel
        if not roles_or_members:
            roles_or_members = [ctx.guild.default_role]
        else:
            roles_or_members = roles_or_members[:10]
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        if isinstance(channel, discord.TextChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                my_perms = channel.overwrites_for(ctx.me)
                if my_perms.send_messages != True:
                    my_perms.update(send_messages=True)
                    await channel.set_permissions(ctx.me, overwrite=my_perms)
                if current_perms.send_messages == False:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(send_messages=False)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))
        elif isinstance(channel, discord.VoiceChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.connect == False:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(connect=False)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))

        msg = ""
        if succeeded:
            msg += f"{channel.mention} has been locked for {humanize_list(succeeded)}.\n"
        if cancelled:
            msg += f"{channel.mention} was already locked for {humanize_list(cancelled)}.\n"
        if failed:
            msg += f"I failed to lock {channel.mention} for {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @commands.bot_has_permissions(manage_roles=True)
    @commands.command()
    @checks.has_permissions(PermissionLevel.MOD)
    async def bind(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]],
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]],
    ):
        """
        Bind a role to a channel.

        Provide a role or member if you would like to bind it for them.
        You can only bind a maximum of 10 things at once.

        **Examples:**
        `{prefix}bind #general @members`
        `{prefix}bind 123456789000000 @members`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:
            return

        roles_or_members = roles_or_members[:10]
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        if isinstance(channel, discord.TextChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                my_perms = channel.overwrites_for(ctx.me)
                if my_perms.send_messages != True:
                    my_perms.update(send_messages=True)
                    await channel.set_permissions(ctx.me, overwrite=my_perms)
                if current_perms.send_messages == True:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(view_channel= True, send_messages=True)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))
        elif isinstance(channel, discord.VoiceChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.connect == True:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(view_channel= True, connect=True)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))

        if len(succeeded) != 0 or len(cancelled) != 0:
            for r in channel.changed_roles:
                if r not in roles_or_members:
                    await channel.set_permissions(
                        r, view_channel=False, send_messages=False
                    )

        msg = ""
        if succeeded:
            msg += f"{channel.mention} is binded to {humanize_list(succeeded)}.\n"
        if cancelled:
            msg += f"{channel.mention} was already binded to {humanize_list(cancelled)}.\n"
        if failed:
            msg += f"I failed to bind {channel.mention} to {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @commands.bot_has_permissions(manage_roles=True)
    @checks.has_permissions(PermissionLevel.MOD)
    @commands.command()
    async def viewlock(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
    ):
        """
        Prevent users from viewing a channel.

        Provide a role or member if you would like to lock it for them.
        You can only lock a maximum of 10 things at once.

        **Example:**
        `{prefix}viewlock #secret-channel`
        `{prefix}viewlock 123456789000000 @nubs`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:  # when another bot is faster to lock
            return

        if not channel:
            channel = ctx.channel
        if not roles_or_members:
            roles_or_members = [ctx.guild.default_role]
        else:
            roles_or_members = roles_or_members[:10]
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        for role in roles_or_members:
            current_perms = channel.overwrites_for(role)
            if current_perms.read_messages == False:
                cancelled.append(inline(role.name))
            else:
                current_perms.update(read_messages=False)
                try:
                    await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                    succeeded.append(inline(role.name))
                except:
                    failed.append(inline(role.name))

        msg = ""
        if succeeded:
            msg += f"{channel.mention} has been viewlocked for {humanize_list(succeeded)}.\n"
        if cancelled:
            msg += f"{channel.mention} was already viewlocked for {humanize_list(cancelled)}.\n"
        if failed:
            msg += f"I failed to viewlock {channel.mention} for {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @lock.command("server")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def lock_server(self, ctx: commands.Context, *roles: LockableRole):
        """
        Lock the server.

        Provide a role if you would like to lock it for that role.

        **Example:**
        `{prefix}lock server @members`
        """
        if not roles:
            roles = [ctx.guild.default_role]
        succeeded = []
        cancelled = []
        failed = []

        for role in roles:
            current_perms = role.permissions
            if ctx.guild.me.top_role <= role:
                failed.append(inline(role.name))
            elif current_perms.send_messages == False:
                cancelled.append(inline(role.name))
            else:
                current_perms.update(send_messages=False)
                try:
                    await role.edit(permissions=current_perms)
                    succeeded.append(inline(role.name))
                except:
                    failed.append(inline(role.name))
        if succeeded:
            await ctx.send(f"The server has locked for {humanize_list(succeeded)}.")
        if cancelled:
            await ctx.send(f"The server was already locked for {humanize_list(cancelled)}.")
        if failed:
            await ctx.send(
                f"I failed to lock the server for {humanize_list(failed)}, probably because I was lower than the roles in heirarchy."
            )

    @checks.has_permissions(PermissionLevel.OWNER) # unstable, incomplete
    @lock.command("perms")
    async def lock_perms(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
        *permissions: str,
    ):
        """Set the given permissions for a role or member to True."""
        if not permissions:
            raise commands.BadArgument

        await ctx.trigger_typing()
        channel = channel or ctx.channel
        roles_or_members = roles_or_members or [ctx.guild.default_role]

        perms = {}
        for perm in permissions:
            perms.update({perm: False})
        for role in roles_or_members:
            overwrite = self.update_overwrite(ctx, channel.overwrites_for(role), perms)
            await channel.set_permissions(role, overwrite=overwrite[0])
        msg = ""
        if overwrite[1]:
            msg += (
                f"The following permissions have been denied for "
                f"{humanize_list([f'`{obj}`' for obj in roles_or_members])} in {channel.mention}:\n"
                f"{humanize_list([f'`{perm}`' for perm in overwrite[1]])}\n"
            )
        if overwrite[2]:
            msg += overwrite[2]
        if overwrite[3]:
            msg += overwrite[3]
        if msg:
            await ctx.send(msg)

    @commands.bot_has_permissions(manage_roles=True)
    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def unlock(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        state: Optional[ChannelToggle] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
    ):
        """
        Unlock a channel.

        Provide a role or member if you would like to unlock it for them.
        If you would like to override-unlock for something, you can do so by pass `true` as the state argument.
        You can only unlock a maximum of 10 things at once.

        **Examples:**
        `{prefix}unlock #general`
        `{prefix}unlock 123456789000000 true`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:  # when another bot is faster to lock
            return

        if not channel:
            channel = ctx.channel
        if roles_or_members:
            roles_or_members = roles_or_members[:10]
        else:
            roles_or_members = [ctx.guild.default_role]
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        if isinstance(channel, discord.TextChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.send_messages != False and current_perms.send_messages == state:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(send_messages=state)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))
        elif isinstance(channel, discord.VoiceChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.connect in [False, state]:
                    current_perms.update(connect=state)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))

                else:
                    cancelled.append(inline(role.name))
        msg = ""
        if succeeded:
            msg += f"{channel.mention} has unlocked for {humanize_list(succeeded)} with state `{'true' if state else 'default'}`.\n"
        if cancelled:
            msg += f"{channel.mention} was already unlocked for {humanize_list(cancelled)} with state `{'true' if state else 'default'}`.\n"
        if failed:
            msg += f"I failed to unlock {channel.mention} for {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @commands.bot_has_permissions(manage_roles=True)
    @checks.has_permissions(PermissionLevel.MOD)
    @commands.command()
    async def unbind(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]],
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
    ):
        """
        Unbind a role from a channel.

        Provide a role or member if you would like to unbind it for them.
        You can only unbind a maximum of 10 things at once.

        **Examples:**
        `{prefix}unbind #general @members`
        `{prefix}unbind 123456789000000 @members`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:
            return

        roles_or_members = roles_or_members[:10]
        members = []
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        if isinstance(channel, discord.TextChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.send_messages != True:
                    cancelled.append(inline(role.name))
                else:
                    current_perms.update(view_channel= None, send_messages=None)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))
        elif isinstance(channel, discord.VoiceChannel):
            for role in roles_or_members:
                current_perms = channel.overwrites_for(role)
                if current_perms.connect != True:
                    current_perms.update(view_channel= None, connect=None)
                    try:
                        await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                        succeeded.append(inline(role.name))
                    except:
                        failed.append(inline(role.name))

                else:
                    cancelled.append(inline(role.name))

        if len(succeeded) != 0 or len(cancelled) != 0:
            for r in channel.changed_roles:
                if r == ctx.guild.default_role:
                    state = True
                else:
                    state = None

                await channel.set_permissions(
                    r, view_channel=state, send_messages=state
                )

                #for m in channel.members:
                    #if r not in m.roles:
                    #await channel.set_permissions(
                        #m, read_messages=state, send_messages=state
                    #)

        msg = ""
        if succeeded:
            msg += f"{channel.mention} is unbinded from {humanize_list(succeeded)}.\n"
        if cancelled:
            msg += f"{channel.mention} was already unbinded from {humanize_list(cancelled)}.\n"
        if failed:
            msg += f"I failed to unbind {channel.mention} from {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @commands.bot_has_permissions(manage_roles=True)
    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def viewunlock(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        state: Optional[ChannelToggle] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
    ):
        """
        Allow users to view a channel.

        Provide a role or member if you would like to unlock it for them.
        If you would like to override-unlock for something, you can do so by pass `true` as the state argument.
        You can only unlock a maximum of 10 things at once.

        **Example:**
        `{prefix}viewunlock #hidden-channel true`
        `{prefix}viewunlock 123456789000000 @boosters`
        """
        try:
            await ctx.trigger_typing()
        except discord.Forbidden:  # when another bot is faster to lock
            return

        if not channel:
            channel = ctx.channel
        if not roles_or_members:
            roles_or_members = [ctx.guild.default_role]
        else:
            roles_or_members = roles_or_members[:10]
        succeeded = []
        cancelled = []
        failed = []
        reason = get_audit_reason(ctx.author)

        for role in roles_or_members:
            current_perms = channel.overwrites_for(role)
            if current_perms.read_messages != False and current_perms.read_messages == state:
                cancelled.append(inline(role.name))
            else:
                current_perms.update(read_messages=state)
                try:
                    await channel.set_permissions(role, overwrite=current_perms, reason=reason)
                    succeeded.append(inline(role.name))
                except:
                    failed.append(inline(role.name))

        msg = ""
        if succeeded:
            msg += f"{channel.mention} has unlocked viewing for {humanize_list(succeeded)} with state `{'true' if state else 'default'}`.\n"
        if cancelled:
            msg += f"{channel.mention} was already viewunlocked for {humanize_list(cancelled)} with state `{'true' if state else 'default'}`.\n"
        if failed:
            msg += f"I failed to unlock {channel.mention} for {humanize_list(failed)}.\n"
        if msg:
            await ctx.send(msg)

    @unlock.command("server")
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def unlock_server(self, ctx: commands.Context, *roles: LockableRole):
        """
        Unlock the server.

        Provide a role if you would like to unlock it for that role.

        **Examples:**
        `{prefix}unlock server @members`
        """
        if not roles:
            roles = [ctx.guild.default_role]
        succeeded = []
        cancelled = []
        failed = []

        for role in roles:
            current_perms = role.permissions
            if ctx.guild.me.top_role <= role:
                failed.append(inline(role.name))
            elif current_perms.send_messages == True:
                cancelled.append(inline(role.name))
            else:
                current_perms.update(send_messages=True)
                try:
                    await role.edit(permissions=current_perms)
                    succeeded.append(inline(role.name))
                except:
                    failed.append(inline(role.name))

        msg = []
        if succeeded:
            msg.append(f"The server has unlocked for {humanize_list(succeeded)}.")
        if cancelled:
            msg.append(f"The server was already unlocked for {humanize_list(cancelled)}.")
        if failed:
            msg.append(
                f"I failed to unlock the server for {humanize_list(failed)}, probably because I was lower than the roles in heirarchy."
            )
        if msg:
            await ctx.send("\n".join(msg))

    @checks.has_permissions(PermissionLevel.OWNER) # unstable, incomplete
    @unlock.command("perms")
    async def unlock_perms(
        self,
        ctx: commands.Context,
        channel: Optional[Union[LockableChannel, discord.VoiceChannel]] = None,
        state: Optional[ChannelToggle] = None,
        roles_or_members: commands.Greedy[Union[LockableRole, discord.Member]] = None,
        *permissions: str,
    ):
        """
        Set the given permissions for a role or member to `True` or `None`, depending on the given state
        """
        if not permissions:
            raise commands.BadArgument

        await ctx.trigger_typing()
        channel = channel or ctx.channel
        roles_or_members = roles_or_members or [ctx.guild.default_role]

        perms = {}
        for perm in permissions:
            perms.update({perm: state})
        for role in roles_or_members:
            overwrite = self.update_overwrite(ctx, channel.overwrites_for(role), perms)
            await channel.set_permissions(role, overwrite=overwrite[0])
        msg = ""
        if overwrite[1]:
            msg += (
                f"The following permissions have been set to `{state}` for "
                f"{humanize_list([f'`{obj}`' for obj in roles_or_members])} in {channel.mention}:\n"
                f"{humanize_list([f'`{perm}`' for perm in overwrite[1]])}"
            )
        if overwrite[2]:
            msg += overwrite[2]
        if overwrite[3]:
            msg += overwrite[3]
        if msg:
            await ctx.send(msg)

    @staticmethod
    def update_overwrite(
        ctx: commands.Context, overwrite: discord.PermissionOverwrite, permissions: dict
    ):
        base_perms = dict(iter(discord.PermissionOverwrite()))
        old_perms = copy(permissions)
        ctx.channel.permissions_for(ctx.author)
        invalid_perms = []
        valid_perms = []
        not_allowed: List[str] = []
        for perm in old_perms:
            if perm in base_perms:
                valid_perms.append(f"`{perm}`")
            else:
                invalid_perms.append(f"`{perm}`")
                del permissions[perm]
        overwrite.update(**permissions)
        if invalid_perms:
            invalid = (
                f"\nThe following permissions were invalid:\n{humanize_list(invalid_perms)}\n"
            )
            possible = humanize_list([f"`{perm}`" for perm in base_perms])
            invalid += f"Possible permissions are:\n{possible}"
        else:
            invalid = ""
        return overwrite, valid_perms, invalid, not_allowed

async def setup(bot):
    await bot.add_cog(Lock(bot))
