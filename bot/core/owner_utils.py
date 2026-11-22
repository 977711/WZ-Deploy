from .config_manager import Config


def is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID
