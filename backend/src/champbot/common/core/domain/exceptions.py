class ChampBotError(Exception):
    pass


class MissingSettingError(ChampBotError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Missing required setting: {name}")
        self.name = name
