from ... import user_data
from ...core.config_manager import Config
from ..telegram_helper.message_utils import delete_message
from .bot_utils import new_task


@new_task
async def confirm_terabox_selection(_, query):
    from ..mirror_leech_utils.download_utils.terabox_download import (
        _terabox_selections,
        resume_terabox_with_selection,
        cancel_terabox_selection,
    )

    user_id = query.from_user.id
    data = query.data.split()
    message = query.message

    action = data[1] if len(data) > 1 else ""
    gid = data[2] if len(data) > 2 else ""

    if not gid:
        await query.answer("Invalid selection data!", show_alert=True)
        await delete_message(message)
        return

    _raw_gid = gid[8:] if gid.startswith("terabox_") else gid

    state = _terabox_selections.get(_raw_gid)
    if state is None:
        await query.answer("This task has been cancelled!", show_alert=True)
        await delete_message(message)
        return
    listener = state["listener"]
    if (
        Config.OWNER_ID != user_id
        and listener.user_id != user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await query.answer("This task is not for you!", show_alert=True)
        return

    if action == "cancel":
        await query.answer()
        from .selection_pin_store import delete_pin

        delete_pin(gid)
        await cancel_terabox_selection(_raw_gid)
        await delete_message(message)
        return

    if action == "pin":
        if len(data) > 3:
            await query.answer(data[3], show_alert=True)
        else:
            await query.answer("No PIN available", show_alert=True)
        return

    if action != "done":
        await query.answer()
        return

    await query.answer()
    from .selection_pin_store import delete_pin

    delete_pin(gid)
    await resume_terabox_with_selection(_raw_gid)
    await delete_message(message)
