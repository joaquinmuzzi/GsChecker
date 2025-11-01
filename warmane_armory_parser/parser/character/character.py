from ...models.character import Character
from ...lib.armory_interface import ArmoryInterface
from ...parser.page.statistics import StatisticsPageParser


class CharacterParser:
    def __init__(self, name: str, realm: str = "Icecrown"):
        self.character_name: str = name
        self.realm: str = realm

    def build_character(self):
        character_armory = ArmoryInterface(self.character_name, self.realm)

        statistics_content = character_armory.get_statistics_content()
        statistics_data = StatisticsPageParser(statistics_content).parse()



        return Character(
            statistics=statistics_data
        )
