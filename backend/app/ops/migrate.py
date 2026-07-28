from app.db.session import init_db


def main() -> None:
    init_db()
    print("Database migrations applied.")


if __name__ == "__main__":
    main()
