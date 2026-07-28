import argparse

from app.db.session import SessionLocal, init_db
from app.models.tables import RawDataset
from app.processing.synthetic_data import generate_demo
from app.services.dataset_cleanup import delete_raw_dataset
from app.storage.s3 import store


DEMO_RAW_NAMES = {"Reef Survey A", "Reef Survey B"}


def seed_demo(*, force: bool = False) -> dict:
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(RawDataset).filter(RawDataset.name.in_(DEMO_RAW_NAMES)).all()
        if existing and not force:
            return {
                "created": [],
                "skipped": [dataset.id for dataset in existing],
                "message": "Demo seed already exists. Pass --force to recreate it.",
            }

        object_store = store()
        for dataset in existing:
            delete_raw_dataset(db, dataset.id, object_store)

        return generate_demo(db, pair=True)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed repeatable ReefFusion demo datasets.")
    parser.add_argument("--force", action="store_true", help="Delete existing demo datasets and recreate them.")
    args = parser.parse_args()
    print(seed_demo(force=args.force))


if __name__ == "__main__":
    main()
