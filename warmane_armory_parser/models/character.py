from typing import Sequence
from ..models.jsonifiable import JSONifiable
from ..models.statistics import StatisticsGroup


class Character(JSONifiable):
    def __init__(self, statistics: Sequence[StatisticsGroup]):

        self.statistics = statistics
