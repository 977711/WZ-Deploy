from asyncio import sleep
from time import time
from secrets import token_hex

from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked

from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)

bc_cache = {}


async def delete_broadcast(bc_id, message):
    """Delete broadcasted messages based on the broadcast ID."""
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    temp_wait = await send_message(
        message, "<i>Deleting the Broadcasted Message! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    msgs = bc_cache.get(bc_id, [])
    for uid, msg_id in msgs:
        try:
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except Exception as e:
            print(f"Error deleting message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>Broadcast Deleted Stats :</i></b>
╭ <b>Total Users:</b> <code>{total}</code>
┊ <b>Success:</b> <code>{success}</code>
╰ <b>Failed Attempts:</b> <code>{failed}</code>

<b>Broadcast ID:</b> <code>{bc_id}</code>""",
    )


async def edit_broadcast(bc_id, message, rply):
    """Edit broadcasted messages based on the broadcast ID."""
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    temp_wait = await send_message(
        message, "<i>Editing the Broadcasted Message! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    for uid, msg_id in bc_cache[bc_id]:
        msg = await TgClient.bot.get_messages(uid, msg_id)
        if hasattr(msg, "forward_from"):
            return await edit_message(
                temp_wait,
                "<i>Forwarded Messages can't be Edited, Only can be Deleted!</i>",
            )
        try:
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            await sleep(0.3)
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            success += 1
        except Exception as e:
            print(f"Error editing message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>Broadcast Edited Stats :</i></b>
╭ <b>Total Users:</b> <code>{total}</code>
┊ <b>Success:</b> <code>{success}</code>
╰ <b>Failed Attempts:</b> <code>{failed}</code>

<b>Broadcast ID:</b> <code>{bc_id}</code>""",
    )


async def pin_broadcast(bc_id, message, with_notification=False):
    """Pin broadcasted messages based on the broadcast ID."""
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    pin_type = "with Notifications" if with_notification else "Silently"
    temp_wait = await send_message(
        message, f"<i>Pinning the Broadcasted Messages {pin_type}! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    msgs = bc_cache.get(bc_id, [])
    for uid, msg_id in msgs:
        try:
            # Use both_sides=True for private chats to enable two-sided pinning
            await TgClient.bot.pin_chat_message(
                uid, msg_id, disable_notification=not with_notification, both_sides=True
            )
            success += 1
            await sleep(0.5)  # Small delay to avoid rate limits
        except FloodWait as e:
            await sleep(e.value)
            await TgClient.bot.pin_chat_message(
                uid, msg_id, disable_notification=not with_notification, both_sides=True
            )
            success += 1
        except Exception as e:
            print(f"Error pinning message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>Broadcast Pin Stats :</i></b>
╭ <b>Total Users:</b> <code>{total}</code>
┊ <b>Success:</b> <code>{success}</code>
╰ <b>Failed Attempts:</b> <code>{failed}</code>

<b>Broadcast ID:</b> <code>{bc_id}</code>
<b>Pin Type:</b> <code>{pin_type}</code>""",
    )


async def unpin_broadcast(bc_id, message):
    """Unpin broadcasted messages based on the broadcast ID."""
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    temp_wait = await send_message(
        message, "<i>Unpinning the Broadcasted Messages! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    msgs = bc_cache.get(bc_id, [])
    for uid, msg_id in msgs:
        try:
            # No both_sides parameter for unpin_chat_message
            await TgClient.bot.unpin_chat_message(uid, msg_id)
            success += 1
            await sleep(0.5)  # Small delay to avoid rate limits
        except FloodWait as e:
            await sleep(e.value)
            await TgClient.bot.unpin_chat_message(uid, msg_id)
            success += 1
        except Exception as e:
            print(f"Error unpinning message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>Broadcast Unpin Stats :</i></b>
╭ <b>Total Users:</b> <code>{total}</code>
┊ <b>Success:</b> <code>{success}</code>
╰ <b>Failed Attempts:</b> <code>{failed}</code>

<b>Broadcast ID:</b> <code>{bc_id}</code>""",
    )


@new_task
async def broadcast(_, message):
    """Handle different broadcast actions: send, edit, delete, pin, unpin, or forward."""
    bc_id, forwarded, quietly, deleted, edited = "", False, False, False, False
    pinned, unpinned, pin_after_broadcast = False, False, False
    pin_with_notification, pin_after_with_notification = False, False

    if not Config.DATABASE_URL:
        return await send_message(
            message, "DATABASE_URL not provided to fetch PM Users!"
        )
    rply = message.reply_to_message
    if len(message.command) > 1:
        if not message.command[1].startswith("-"):
            bc_id = (
                message.command[1] if bc_cache.get(message.command[1], False) else ""
            )
            if not bc_id:
                return await send_message(
                    message,
                    "<i>Broadcast ID not found! After Restart, you can't edit, delete, pin or unpin broadcasted messages...</i>",
                )
        for arg in message.command:
            if arg in ["-f", "-forward"] and rply:
                forwarded = True
            elif arg in ["-q", "-quiet"] and rply:
                quietly = True
            elif arg in ["-d", "-delete"] and bc_id:
                deleted = True
            elif arg in ["-e", "-edit"] and bc_id and rply:
                edited = True
            elif arg in ["-ps", "-pinsilent"] and bc_id:
                pinned = True
                pin_with_notification = False
            elif arg in ["-pn", "-pinnotify"] and bc_id:
                pinned = True
                pin_with_notification = True
            elif (
                arg in ["-p", "-pin"] and bc_id
            ):  # Default silent pin for backward compatibility
                pinned = True
                pin_with_notification = False
            elif arg in ["-up", "-unpin"] and bc_id:
                unpinned = True
            elif arg in ["-pas", "-pinaftersilent"] and rply:
                pin_after_broadcast = True
                pin_after_with_notification = False
            elif arg in ["-pan", "-pinafternotify"] and rply:
                pin_after_broadcast = True
                pin_after_with_notification = True
            elif (
                arg in ["-pa", "-pinafter"] and rply
            ):  # Default silent pin after for backward compatibility
                pin_after_broadcast = True
                pin_after_with_notification = False

    if not bc_id and not rply:
        return await send_message(
            message,
            """<b>By replying to msg to Broadcast:</b>
/broadcast bc_id -d -e -f -q -p -ps -pn -up -pa -pas -pan

<b>Forward Broadcast with Tag:</b> -f or -forward
/cmd [reply_msg] -f

<b>Quietly Broadcast msg:</b> -q or -quiet
/cmd [reply_msg] -q -f

<b>Pin After Broadcast Options:</b>
• <b>Silent Pin:</b> -pa or -pinafter or -pas or -pinaftersilent
• <b>Pin with Notification:</b> -pan or -pinafternotify
/cmd [reply_msg] -pa

<b>Edit Broadcast msg:</b> -e or -edit
/cmd [reply_edited_msg] broadcast_id -e

<b>Delete Broadcast msg:</b> -d or -delete
/bc broadcast_id -d

<b>Pin Broadcast msg Options:</b>
• <b>Silent Pin:</b> -p or -pin or -ps or -pinsilent
• <b>Pin with Notification:</b> -pn or -pinnotify
/bc broadcast_id -p

<b>Unpin Broadcast msg:</b> -up or -unpin
/bc broadcast_id -up

<b>Examples:</b>
• Broadcast + Silent Pin: /bc -pa [reply_msg]
• Broadcast + Loud Pin: /bc -pan [reply_msg]
• Silent Pin Existing: /bc abc123 -ps
• Loud Pin Existing: /bc abc123 -pn

<b>Notes:</b>
1. Broadcast msgs can be only edited, deleted, pinned or unpinned until restart.
2. Forwarded msgs can't be Edited
3. Pin/Unpin works in private chats, groups, and channels
4. Default pinning is silent for user comfort""",
        )
    if deleted:
        return await delete_broadcast(bc_id, message)
    elif edited:
        return await edit_broadcast(bc_id, message, rply)
    elif pinned:
        return await pin_broadcast(bc_id, message, pin_with_notification)
    elif unpinned:
        return await unpin_broadcast(bc_id, message)

    # Broadcasting logic
    start_time = time()
    status = """⌬  <b><i>Broadcast Stats :</i></b>
╭ <b>Total Users:</b> <code>{t}</code>
┊ <b>Success:</b> <code>{s}</code>
┊ <b>Blocked Users:</b> <code>{b}</code>
┊ <b>Deleted Accounts:</b> <code>{d}</code>
╰ <b>Unsuccess Attempt:</b> <code>{u}</code>"""
    updater = time()
    bc_hash, bc_msgs = token_hex(5), []
    pls_wait = await send_message(message, status.format(t=0, s=0, b=0, d=0, u=0))
    t, s, b, d, u = 0, 0, 0, 0, 0
    for uid in await database.get_pm_uids():
        bc_msg = None
        try:
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1

            # Pin the message if pin_after_broadcast is True
            if bc_msg and pin_after_broadcast:
                try:
                    # Use both_sides=True for private chats to enable two-sided pinning
                    await TgClient.bot.pin_chat_message(
                        uid,
                        bc_msg.id,
                        disable_notification=not pin_after_with_notification,
                        both_sides=True,
                    )
                    await sleep(0.3)
                except Exception as e:
                    print(f"Error pinning message for user {uid}: {e}")

        except FloodWait as e:
            await sleep(e.value * 1.1)
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1

            # Pin the message if pin_after_broadcast is True (after FloodWait retry)
            if bc_msg and pin_after_broadcast:
                try:
                    # Use both_sides=True for private chats to enable two-sided pinning
                    await TgClient.bot.pin_chat_message(
                        uid,
                        bc_msg.id,
                        disable_notification=not pin_after_with_notification,
                        both_sides=True,
                    )
                    await sleep(0.3)
                except Exception as e:
                    print(f"Error pinning message for user {uid}: {e}")

        except UserIsBlocked:
            await database.rm_pm_user(uid)
            b += 1
        except InputUserDeactivated:
            await database.rm_pm_user(uid)
            d += 1
        except Exception as e:
            print(f"Error broadcasting message to user {uid}: {e}")
            u += 1
        if bc_msg:
            bc_msgs.append((uid, bc_msg.id))
        t += 1
        if (time() - updater) > 10:
            await edit_message(pls_wait, status.format(t=t, s=s, b=b, d=d, u=u))
            updater = time()
    bc_cache[bc_hash] = bc_msgs
    final_status = f"{status.format(t=t, s=s, b=b, d=d, u=u)}\n\n<b>Elapsed Time:</b> <code>{get_readable_time(time() - start_time)}</code>\n<b>Broadcast ID:</b> <code>{bc_hash}</code>"
    if pin_after_broadcast:
        pin_type = "with Notifications" if pin_after_with_notification else "Silently"
        final_status += f"\n<b>Auto-Pinned:</b> <code>{pin_type}</code>"
    await edit_message(pls_wait, final_status)
