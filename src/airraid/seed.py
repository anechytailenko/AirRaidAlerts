"""Seed canonical reference tables (oblasts + symmetric adjacency). Idempotent UPSERT."""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from .db import SessionLocal
from .models import Oblast, OblastAdjacency
from .reference import ADJACENCY_PAIRS, OBLASTS, _NAME_TO_ID


def main() -> None:
    with SessionLocal() as s:
        for i, en, uk, lat, lon in OBLASTS:
            stmt = insert(Oblast).values(
                id=i, name_en=en, name_uk=uk, centroid_lat=lat, centroid_lon=lon
            ).on_conflict_do_update(
                index_elements=[Oblast.id],
                set_={"name_en": en, "name_uk": uk, "centroid_lat": lat, "centroid_lon": lon},
            )
            s.execute(stmt)

        pairs: set[tuple[int, int]] = set()
        for a, b in ADJACENCY_PAIRS:
            ia, ib = _NAME_TO_ID[a], _NAME_TO_ID[b]
            pairs.add((ia, ib))
            pairs.add((ib, ia))
        for ia, ib in pairs:
            s.execute(
                insert(OblastAdjacency)
                .values(oblast_id=ia, neighbor_oblast_id=ib)
                .on_conflict_do_nothing()
            )
        s.commit()
    print(f"OK — seeded {len(OBLASTS)} oblasts and {len(pairs)} adjacency rows (symmetric).")


if __name__ == "__main__":
    main()
