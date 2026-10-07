"""Build the synthetic databases.   Owner: M3

    python data/db/seed.py

Creates data/db/telecare.db from schema.sql with 40 Faker subscribers, two
months of bills each, about a third with a deliberate change between months.
One fixed demo subscriber has the exact demo-story numbers (Rs. 1,200 data
add-on on the 12th) and a known password documented in the README.

Also creates an empty data/db/auth.db (OTP store) and data/db/tickets.db.
All data is synthetic. Never add real customer data.
"""


def main() -> None:
    raise NotImplementedError("M3: see docstring and schema.sql")


if __name__ == "__main__":
    main()
