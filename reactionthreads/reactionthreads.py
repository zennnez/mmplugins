# part of this cog is from the orignal menu plugin: https://github.com/fourjr/modmail-plugins/blob/master/menu/menu.py, all credits goes to the orignal author. I suggest you to use the original plugin, as this one may cause your bot to nuke the world
# created for LukeG#0001 (discord)


import asyncio
import copy

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

from core import checks
from core.models import DummyMessage, PermissionLevel
from core.utils import normalize_alias

from typing import Optional, Literal

class ReactionThreads(commands.Cog):
    """Reaction Menu Tree for Threads"""
    default_global = {
        "enabled": False,
        "mode": "reaction",
        "color": "grey",
        "placeholder": "Choose an option...",
    }
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.task = self.bot.loop.create_task(self.cog_load())
        self.global_config = None
        self.color = None

    async def cog_load(self):
        self.global_config = await self.db.find_one({"_id": "reactionthreads"})
        if self.global_config is None:
            self.global_config = self.default_global
            await self.config_update()
            self.global_config = await self.db.find_one({"_id": "reactionthreads"})

        up = False
        if 'mode' not in self.global_config:
            self.global_config['mode'] = 'reaction'
            up = True

        if 'color' not in self.global_config:
            self.global_config['color'] = 'grey'
            up = True

        if 'placeholder' not in self.global_config:
            self.global_config['placeholder'] = 'Choose an option...'
            up = True

        if up:
            await self.config_update()

        if 'color' in self.global_config:
            if self.global_config['color'] == 'green':
                self.color = discord.ButtonStyle.green
            elif self.global_config['color'] == 'grey':
                self.color = discord.ButtonStyle.grey
            elif self.global_config['color'] == 'red':
                self.color = discord.ButtonStyle.red
            elif self.global_config['color'] == 'blue':
                self.color = discord.ButtonStyle.blurple

    async def config_update(self):
        await self.db.find_one_and_update(
            {"_id": "reactionthreads"},
            {"$set": self.global_config},
            upsert=True,
        )

    def cog_unload(self):
        self.task.cancel()

    async def send_menus(self, thread, creator, category, initial_message, config):
        if initial_message:
            message = DummyMessage(copy.copy(initial_message))
        else:
            message = [m async for m in thread.channel.history(limit=1)][0]

        message.author = self.bot.modmail_guild.me
        message.content = config['content']
        msgs, _ = await thread.reply(message)
        main_recipient_msg = None

        for m in msgs:
            if m.channel.recipient == thread.recipient:
                main_recipient_msg = m
                break

        view = discord.ui.View()
        options = []
        for e in config.keys():

            if e in ['enabled', 'mode', 'placeholder', 'label', 'color', 'content', 'command', '_id']:
                    continue

            if 'label' in config[e] and config[e]['label'].lower() != 'none':
                label = config[e]['label']
            else:
                label = "\u200b"

            if self.global_config['mode'] == 'button':
                view.add_item(discord.ui.Button(style=self.color, label=label, custom_id=e, emoji=e))

            elif self.global_config['mode'] == 'dropdown':
                options.append(discord.SelectOption(label=label, emoji=e, value=e))

            elif self.global_config['mode'] == 'reaction':
                await main_recipient_msg.add_reaction(e)
                await asyncio.sleep(0.3)

        if self.global_config['mode'] == 'dropdown':
            view.add_item(
                discord.ui.Select(
                    custom_id="reactionthreaddrop",
                    placeholder=self.global_config['placeholder'] if 'placeholder' in self.global_config else "Choose an option...", min_values=1, max_values=1,
                        options = options
                    )
                )

        if len(view.children) != 0:
            await main_recipient_msg.edit(view=view)

        try:
            if self.global_config['mode'] == 'button':
                inter = await self.bot.wait_for('interaction', check=lambda i: i.message.id == main_recipient_msg.id and i.user == thread.recipient and str(i.data['custom_id']) in config.keys(), timeout=120)
                config = config[str(inter.data['custom_id'])]

            elif self.global_config['mode'] == 'dropdown':
                inter = await self.bot.wait_for('interaction', check=lambda i: i.message.id == main_recipient_msg.id and i.user == thread.recipient and str(i.data['values'][0]) in config.keys(), timeout=120)
                config = config[str(inter.data['values'][0])]
            
            elif self.global_config['mode'] == 'reaction':
                reaction, _ = await self.bot.wait_for('reaction_add', check=lambda r, u: r.message == main_recipient_msg and u == thread.recipient and str(r.emoji) in config.keys(), timeout=120)
                config = config[str(reaction.emoji)]

        except asyncio.TimeoutError:
            message.content = 'No option selected... timing out'
            await main_recipient_msg.edit(view=None)
            await thread.reply(message)

        else:
            await main_recipient_msg.delete()
            if 'command' in config and config['command'].lower() != 'none':
                alias = config['command']
                ctxs = []
                if alias is not None:
                    ctxs = []
                    aliases = normalize_alias(alias)
                    for alias in aliases:
                        view = StringView(self.bot.prefix + alias)
                        ctx_ = commands.Context(prefix=self.bot.prefix, view=view, bot=self.bot, message=message)
                        ctx_.thread = thread
                        discord.utils.find(view.skip_string, await self.bot.get_prefix())
                        ctx_.invoked_with = view.get_word().lower()
                        ctx_.command = self.bot.all_commands.get(ctx_.invoked_with)
                        ctxs += [ctx_]

                for ctx in ctxs:
                    if ctx.command:
                        old_checks = copy.copy(ctx.command.checks)
                        ctx.command.checks = [checks.has_permissions(PermissionLevel.INVALID)]

                        await self.bot.invoke(ctx)

                        ctx.command.checks = old_checks
                        continue

            if 'content' in config and config['content'].lower() != 'none':
                await self.send_menus(thread, creator, category, initial_message, config)

    async def generate_menus(self, ctx, config, main):
        if main:
            await ctx.send(
                embed=await self.generate_embed(
                    'Top Menu Message', 'This is the first message a member will see.\nFirst set of emojis will be added to it.'
                )
            )
            m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
            config['content'] = m.content
        
            await ctx.send(
                embed=await self.generate_embed(
                    'Menu Options', 'How many options are available?'
                )
            )
            m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author and x.content.isdigit(), timeout=300)
            menu = int(m.content)

            for _ in range(menu):
                await ctx.send(
                    embed=await self.generate_embed(
                        f'Option #{_+1}', f"**Send an emoji for this option.**"
                    )
                )
                while True:
                    m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
                    try:
                        await m.add_reaction(m.content)
                    except discord.HTTPException:
                        await ctx.send(
                            embed=await self.generate_embed(
                                'Try again!', 'Invalid emoji.'
                            )
                        )
                    else:
                        emoji = m.content
                        break

                await ctx.send(
                    embed=await self.generate_embed(
                        f'Option #{_+1} Label', (
                        f'Emoji: {emoji}\n\n'
                        'Send the **label** for this option.\n'
                        'This will be shown on dropdown option / button label.\n'
                        )
                    )
                )
                l = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)

                await ctx.send(
                    embed=await self.generate_embed(
                        f'Option #{_+1} Message', (
                        f'Emoji: {emoji}\n\n'
                        'Send the **message** for this option.\n'
                        'Send __None__ if this is an end command, and there is no sub-menu for this emoji.\n'
                        )
                    )
                )
                m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
                await ctx.send(
                    embed=await self.generate_embed(
                        f'Option #{_+1} Command', (
                        f'Emoji: {emoji}\n\n'
                        'Send the **command** for this option.\n'
                        'Send __None__ if this emoji is for another sub-menu, and no command is needed.\n'
                        )
                    )
                )
                c = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)

                config[emoji] = {'content':m.content, 'label':l.content, 'command':c.content}

            await ctx.send(
                embed=await self.generate_embed(
                    'Done', 'Top menu set!\nSetting up sub-menus now...'
                )
            )
            await self.config_update()
            await self.generate_menus(ctx, config, False)
        else:
            i = 0
            for k, v in config.items():
                if k in ['enabled', 'mode', 'placeholder', 'label', 'color', 'content', 'command', '_id']:
                    continue
                i += 1

                await ctx.send(
                    embed=await self.generate_embed(
                        f'Menu #{i}', (
                        'How many options are available for this menu?\n'
                        '**Main Menu details:**\n'
                        f'Emoji: {k}\n'
                        f"Message: {v['content']}\n"
                        f"Command: {v['command']}\n\n"
                        "**Note:** __Send '0' to end this menu tree__, if no further options/menus are required.\nBot will send the **Message** and trigger the **Command** on reaction/button tap/etc."
                        )
                    )
                )
                m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author and x.content.isdigit(), timeout=300)
                menu = int(m.content)

                for _ in range(menu):
                    await ctx.send(
                        embed=await self.generate_embed(
                            f'Option #{_+1} Label', (
                            f'**Main Menu - {i}:**\n'
                            f'Emoji: {k}\n'
                            f"Message: {v['content']}\n\n"
                            'Send the **label** for this option.\n'
                            'This will be shown on dropdown option / button label.\n'
                            )
                        )
                    )
                    l = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)

                    await ctx.send(
                        embed=await self.generate_embed(
                            f'Option #{_+1} Emoji', (
                            f'**Main Menu - {i}:**\n'
                            f'Emoji: {k}\n'
                            f"Message: {v['content']}\n\n"
                            'Send the **emoji** for this sub-menu option.'
                            )
                        )
                    )
                    while True:
                        m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
                        try:
                            await m.add_reaction(m.content)
                        except discord.HTTPException:
                            await ctx.send(
                                embed=await self.generate_embed(
                                    'Try again!', 'Invalid emoji.'
                                )
                            )
                        else:
                            emoji = m.content
                            break

                    await ctx.send(
                        embed=await self.generate_embed(
                            f'Option #{_+1} Message', (
                            f'Option Emoji: {emoji}\n\n'
                            f'**Main Menu - {i}:**\n'
                            f'Emoji: {k}\n'
                            f"Message: {v['content']}\n\n"
                            'Send the **message** for this option.\n'
                            'Send __None__ if this is an end command, and there is no message.\n'
                            )
                        )
                    )
                    m = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
                    await ctx.send(
                        embed=await self.generate_embed(
                            f'Option #{_+1} Command', (
                            f'Option Emoji: {emoji}\n\n'
                            f'**Main Menu - {i}:**\n'
                            f'Emoji: {k}\n'
                            f"Message: {v['content']}\n\n"
                            'Send the **command** for this option.\n'
                            'Send __None__ if no command is needed.\n'
                            )
                        )
                    )
                    c = await self.bot.wait_for('message', check=lambda x: ctx.message.channel == x.channel and ctx.message.author == x.author, timeout=300)
                    v[emoji] = {'content':m.content, 'label':l.content, 'command':c.content}

                    await self.config_update()
                await self.generate_menus(ctx, v, False)

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, creator, category, initial_message):
        if self.global_config['enabled']:
            await self.send_menus(thread, creator, category, initial_message, self.global_config)

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(aliases=['rthread', 'threadmenu'], invoke_without_command=True)
    async def reactionthreads(self, ctx):
        """Create a Threaded Menu for members"""
        if not ctx.invoked_subcommand:
            if 'mode' not in self.global_config:
                await ctx.send(f"Choose a menu mode first...")
                return await ctx.send_help(self.reactionthreads_mode)

            if not self.global_config['enabled']:
                await ctx.send(f"Warning!\nPlugin is disabled\n`{ctx.prefix}rthread toggle`", delete_after=20)

            try:
                await self.generate_menus(ctx, self.global_config, True)
            except asyncio.TimeoutError:
                await ctx.send(
                    embed=await self.generate_embed(
                        'Timeout', 'Re-run the command to create a menu.'
                    )
                )
            else:
                await self.config_update()
                await ctx.send(
                    embed=await self.generate_embed(
                        'Done', 'New Menu created successfully'
                    )
                )

    @checks.has_permissions(PermissionLevel.MOD)
    @reactionthreads.command(name='clear')
    async def reactionthreads_clear(self, ctx):
        """Removes an existing menu"""
        await self.db.find_one_and_delete(self.global_config)

        enabled = self.global_config['enabled']
        mode = self.global_config['mode']
        self.global_config.clear()
        self.global_config['enabled'] = enabled
        self.global_config['mode'] = mode
        await self.config_update()
        self.global_config = await self.db.find_one({"_id": "reactionthreads"})
        await ctx.send(
            embed=await self.generate_embed(
                'Done', 'Menu is cleared'
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @reactionthreads.command(name='toggle')
    async def reactionthreads_toggle(self, ctx):
        """Toggle menu no/off"""
        self.global_config['enabled'] = not self.global_config['enabled']
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Done', f"**Status:** {'Enabled' if self.global_config['enabled'] else 'Disabled'}"
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @reactionthreads.command(name='mode')
    async def reactionthreads_mode(self, ctx, mode: Optional[Literal["reaction", "dropdown", "button"]]):
        """
        Toggle menu modes:
        `reaction` / `dropdown` / `buttons`
        """
        if not mode:
            return await ctx.send_help(ctx.command)

        self.global_config['mode'] = mode
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                'Mode', mode
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @reactionthreads.command(name='color')
    async def reactionthreads_color(self, ctx, color: Optional[Literal["red", "blue", "grey", "green"]]):
        """
        Button colors of menu:
        `red` / `blue` / `green` / `grey`
        """
        if not color:
            return await ctx.send_help(ctx.command)

        self.global_config['color'] = color
        await self.config_update()
        if color == 'green':
            self.color = discord.ButtonStyle.green
        elif color == 'grey':
            self.color = discord.ButtonStyle.grey
        elif color == 'red':
            self.color = discord.ButtonStyle.red
        elif color == 'blue':
            self.color = discord.ButtonStyle.blurple
        await ctx.send(
            embed=await self.generate_embed(
                'Color', color
            )
        )

    @checks.has_permissions(PermissionLevel.MOD)
    @reactionthreads.command(name='placeholder')
    async def reactionthreads_placeholder(self, ctx, *, placeholder: str):
        """
        The text which you see in dropdown menu
        """
        self.global_config['placeholder'] = placeholder
        await self.config_update()

        await ctx.send(
            embed=await self.generate_embed(
                'Placeholder', placeholder
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
    await bot.add_cog(ReactionThreads(bot))