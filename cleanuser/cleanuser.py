from __future__ import annotations

import asyncio
from typing import Iterable, Optional, Union

import discord
from redbot.core import commands, checks
from redbot.core.bot import Red

ChannelLike = Union[
    discord.TextChannel,
    discord.Thread,
    discord.ForumChannel,
]

__all__ = ["setup"]


class CleanUser(commands.Cog):
    """
    Supprimer les messages d'un utilisateur par ID, dans un canal ou dans tout le serveur.
    - Marche même si l'utilisateur a QUITTÉ le serveur (on compare par author.id).
    - --all : parcourt tous les salons textuels + threads.
    - --dry-run : ne supprime rien, compte seulement.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    @commands.command(name="purgeuser", aliases=["cleanuser", "cleanupuser"])
    async def purge_user_command(
        self,
        ctx: commands.Context,
        user_id: int,
        *,
        flags: Optional[str] = None,
    ):
        """
        Supprime les messages d'un utilisateur par ID.

        Usage:
          [p]purgeuser <user_id>            -> purge dans le canal courant
          [p]purgeuser <user_id> --all      -> purge dans tout le serveur (tous les salons/threads)
          [p]purgeuser <user_id> --dry-run  -> ne supprime rien, compte seulement
          [p]purgeuser <user_id> --all --dry-run

        Notes:
        - Les messages de + de 14 jours sont supprimés individuellement (c’est plus lent, mais ça fonctionne).
        - Le bot a besoin de : Lire l'historique + Gérer les messages dans chaque canal ciblé.
        """
        flags = (flags or "").lower()

        scan_all = "--all" in flags
        dry_run = "--dry-run" in flags or "--dryrun" in flags

        guild: discord.Guild = ctx.guild  # type: ignore
        assert guild is not None

        # Déterminer la liste des canaux à traiter
        if scan_all:
            channels: list[ChannelLike] = []
            # Text channels + Forum channels
            for ch in guild.channels:
                if isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
                    channels.append(ch)
            # Threads "orphelins" (archivés/actifs) accessibles
            for ch in guild.text_channels:
                try:
                    threads = (
                        [*ch.threads]
                        + [*getattr(ch, "archived_threads", [])]  # compatibility
                    )
                    # La récupération des threads archivés complets n'est pas exposée publiquement,
                    # mais on traitera ceux visibles. Le channel.history() suit déjà les messages du salon principal.
                    for th in threads:
                        if isinstance(th, discord.Thread):
                            channels.append(th)
                except Exception:
                    pass
        else:
            if isinstance(ctx.channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
                channels = [ctx.channel]  # type: ignore
            else:
                await ctx.send("❌ Ce type de canal n’est pas supporté ici.")
                return

        # Confirmation (évite les erreurs humaines)
        scope_txt = "tout le serveur" if scan_all else f"#{getattr(ctx.channel, 'name', 'ce canal')}"
        if dry_run:
            confirm_note = "Mode **dry-run** (aucune suppression)."
        else:
            confirm_note = "Les messages seront **supprimés**."

        msg_confirm = await ctx.send(
            f"Tu t'apprêtes à traiter les messages de l’utilisateur **{user_id}** dans **{scope_txt}**.\n"
            f"{confirm_note}\n\n**Tape `oui` pour confirmer** (30s)…"
        )

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            resp = await ctx.bot.wait_for("message", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await msg_confirm.edit(content="⏱️ Annulé (pas de confirmation).")
            return

        if resp.content.strip().lower() not in {"oui", "o", "yes", "y"}:
            await ctx.send("❌ Annulé.")
            return

        # Traitement
        total_found = 0
        total_deleted = 0
        progress_msg = await ctx.send("🔎 Scan en cours… (cela peut prendre du temps)")

        # Petite fonction utilitaire : vérifie permissions minimales
        def can_manage(ch: ChannelLike) -> bool:
            perms = ch.permissions_for(guild.me)  # type: ignore
            # Lecture + gestion messages requis
            return perms.read_message_history and perms.manage_messages and perms.read_messages

        # Pour ne pas spammer l'API
        async def throttled_delete(message: discord.Message):
            nonlocal total_deleted
            try:
                await message.delete()
                total_deleted += 1
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException:
                # Rate-limit ou autre souci ponctuel
                await asyncio.sleep(1.5)

        # Parcours des canaux
        for ch in channels:
            if not can_manage(ch):
                # On ignore silencieusement, mais on pourrait logguer si besoin
                continue

            # ForumChannel : on doit itérer sur ses threads + les "starter messages" ne sont pas supprimables via history
            if isinstance(ch, discord.ForumChannel):
                # Les messages "root" d’un post forum ne sont pas parcourus par history() du ForumChannel.
                # On parcourt donc chaque thread du forum.
                thread_like: Iterable[discord.Thread] = ch.threads
                for th in thread_like:
                    if not can_manage(th):
                        continue
                    await self._scan_channel_history(
                        th, user_id, dry_run, throttled_delete, progress_msg, ctx
                    )
                continue

            # TextChannel / Thread
            await self._scan_channel_history(
                ch, user_id, dry_run, throttled_delete, progress_msg, ctx
            )

            # Petit break respiratoire entre canaux
            await asyncio.sleep(0.25)

        await progress_msg.edit(
            content=(
                f"✅ Terminé.\n"
                f"Utilisateur cible: **{user_id}**\n"
                f"Canaux scannés: **{len(channels)}**\n"
                f"{'Messages potentiellement ciblés (dry-run) : ' if dry_run else 'Messages supprimés : '}**{total_deleted}**"
            )
        )

    async def _scan_channel_history(
        self,
        channel: ChannelLike,
        user_id: int,
        dry_run: bool,
        deleter,  # callable(message)
        progress_msg: discord.Message,
        ctx: commands.Context,
    ):
        """
        Parcourt l'historique d'un canal et supprime (ou compte) les messages de user_id.
        On itère du plus ancien au plus récent pour limiter les surprises.
        """
        count_found = 0
        count_deleted = 0

        # On parcourt SANS limite (attention : long pour les gros salons)
        try:
            async for msg in channel.history(limit=None, oldest_first=True):
                if msg.author and msg.author.id == user_id:
                    count_found += 1
                    if not dry_run:
                        await deleter(msg)
                        count_deleted += 1

                    # Mise à jour périodique du statut
                    if count_found % 50 == 0:
                        await progress_msg.edit(
                            content=(
                                f"🔎 Canal **#{getattr(channel, 'name', 'thread')}** — "
                                f"trouvés: **{count_found}** | "
                                f"{'supprimés' if not dry_run else 'simulés'}: **{count_deleted}**"
                            )
                        )
                        # Petite pause pour respirer entre batchs
                        await asyncio.sleep(0.4)
        except discord.Forbidden:
            # Pas les perms dans ce canal
            pass
        except discord.HTTPException:
            # On ralentit si l'API râle
            await asyncio.sleep(1.0)

        # Final par canal
        await progress_msg.edit(
            content=(
                f"✅ Canal **#{getattr(channel, 'name', 'thread')}** terminé — "
                f"trouvés: **{count_found}** | "
                f"{'supprimés' if not dry_run else 'simulés'}: **{count_deleted}**"
            )
        )
        # Petite pause avant le prochain canal
        await asyncio.sleep(0.2)
        
async def setup(bot: Red):
    await bot.add_cog(CleanUser(bot))