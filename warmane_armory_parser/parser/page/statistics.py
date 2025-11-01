from bs4 import BeautifulSoup
from typing import Sequence, Optional
from ...models.statistics import Statistic, StatisticsGroup, StatisticsChunkResponse


class StatisticsPageParser():
    def __init__(self, chunks: Sequence[StatisticsChunkResponse], category: Optional[str] = "Dungeons & Raids", subcategory: Optional[str] = "Fall of the Lich King"):
        if category is None and subcategory is None:
            self.chunks = list(chunks)
        else:
            filtered = []
            for c in chunks:
                # keep only dict-like/objects with category/subcategory attributes
                c_cat = getattr(c, "category", None) if not isinstance(c, dict) else c.get("category")
                c_sub = getattr(c, "subcategory", None) if not isinstance(c, dict) else c.get("subcategory")
                if category is not None and c_cat != category:
                    continue
                if subcategory is not None and c_sub != subcategory:
                    continue
                filtered.append(c)
            self.chunks = filtered

    def parse_chunk_content(self, content: BeautifulSoup) -> Sequence[Statistic]:
        # [<td>Name</td>, <td>Value</td>, <td>Name</td>, <td>Value</td>, ...]
        tds = content.find_all("td")

        # [Name, Value, Name, Value, ...]
        tds = [td.text for td in tds]

        # {Name: Value, Name: Value, ...}
        pairs = dict(zip(tds[::2], tds[1::2]))

        return [Statistic(name, value) for name, value in pairs.items()]

    def parse_chunk(self, chunk: StatisticsChunkResponse) -> StatisticsGroup:
        return StatisticsGroup(
            category=chunk.category,
            subcategory=chunk.subcategory,
            statistics=self.parse_chunk_content(chunk.content)
        )

    def parse(self) -> Sequence[StatisticsGroup]:
        return [self.parse_chunk(chunk) for chunk in self.chunks]
