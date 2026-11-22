from aiofiles.os import remove, path as aiopath

from .. import (
    user_data,
    LOGGER,
)
from ..core.config_manager import Config
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import get_task_by_gid
from ..helper.telegram_helper.message_utils import (
    send_status_message,
    delete_message,
)


@new_task
async def confirm_selection(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    message = query.message

    # Handle MEGA selection callbacks (gid starting with 'mega_')
    if data[2].startswith("mega_"):
        from ..helper.mirror_leech_utils.download_utils.mega_download import (
            _mega_selections,
            resume_mega_with_selection,
            cancel_mega_selection,
        )

        real_gid = data[2].replace("mega_", "", 1)
        state = _mega_selections.get(real_gid)
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
        if data[1] == "pin":
            await query.answer(data[3], show_alert=True)
        elif data[1] == "done":
            await query.answer()
            from ..helper.ext_utils.selection_pin_store import delete_pin

            delete_pin(data[2])
            await resume_mega_with_selection(real_gid)
            await delete_message(message)
        else:
            from ..helper.ext_utils.selection_pin_store import delete_pin

            delete_pin(data[2])
            await delete_message(message)
            await cancel_mega_selection(real_gid)
        return

    task = await get_task_by_gid(data[2])
    if task is None:
        await query.answer("This task has been cancelled!", show_alert=True)
        await delete_message(message)
        return
    if (
        Config.OWNER_ID != user_id
        and user_id != task.listener.user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await query.answer("This task is not for you!", show_alert=True)
    elif data[1] == "pin":
        await query.answer(data[3], show_alert=True)
    elif data[1] == "done":
        await query.answer()
        id_ = data[3]
        from ..helper.ext_utils.selection_pin_store import delete_pin

        delete_pin(id_)
        if hasattr(task, "seeding"):
            if task.listener.is_qbit:
                tor_info = (
                    await TorrentManager.qbittorrent.torrents.info(hashes=[id_])
                )[0]
                path = tor_info.content_path.rsplit("/", 1)[0]
                res = await TorrentManager.qbittorrent.torrents.files(id_)
                for f in res:
                    if f.priority == 0:
                        f_paths = [f"{path}/{f.name}", f"{path}/{f.name}.!qB"]
                        for f_path in f_paths:
                            if await aiopath.exists(f_path):
                                try:
                                    await remove(f_path)
                                except Exception:
                                    pass
                if not task.queued:
                    await TorrentManager.qbittorrent.torrents.start([id_])
            else:
                res = await TorrentManager.aria2.getFiles(id_)
                for f in res:
                    if f["selected"] == "false" and await aiopath.exists(f["path"]):
                        try:
                            await remove(f["path"])
                        except Exception:
                            pass
                if not task.queued:
                    try:
                        await TorrentManager.aria2.unpause(id_)
                    except Exception as e:
                        LOGGER.error(
                            f"{e} Error in resume, this mostly happens after abuse aria2. Try to use select cmd again!"
                        )
        await send_status_message(message)
        await delete_message(message)
    else:
        from ..helper.ext_utils.selection_pin_store import delete_pin

        id_ = task.gid()
        if task.listener.is_qbit:
            id_ = task.hash()
        delete_pin(id_)
        await delete_message(message)
        await task.cancel_task()