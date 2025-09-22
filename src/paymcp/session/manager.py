from typing import Optional

from .types import ISessionStorage, SessionStorageConfig
from .memory import InMemorySessionStorage


class SessionManager:
    _instance: Optional[ISessionStorage] = None

    @classmethod
    def get_storage(
        cls, config: Optional[SessionStorageConfig] = None
    ) -> ISessionStorage:
        if cls._instance is None:
            cls._instance = cls.create_storage(config)
        return cls._instance

    @classmethod
    def create_storage(
        cls, config: Optional[SessionStorageConfig] = None
    ) -> ISessionStorage:
        storage_config = config or SessionStorageConfig(type="memory")

        if storage_config.type == "memory":
            return InMemorySessionStorage()

        elif storage_config.type == "redis":
            raise NotImplementedError(
                "Redis storage not yet implemented. Use memory storage for now."
            )

        elif storage_config.type == "custom":
            if storage_config.options and "implementation" in storage_config.options:
                return storage_config.options["implementation"]
            raise ValueError(
                'Custom storage requires an implementation in options["implementation"]'
            )

        else:
            raise ValueError(f"Unknown storage type: {storage_config.type}")

    @classmethod
    def reset(cls) -> None:
        if cls._instance and hasattr(cls._instance, "destroy"):
            cls._instance.destroy()
        cls._instance = None
