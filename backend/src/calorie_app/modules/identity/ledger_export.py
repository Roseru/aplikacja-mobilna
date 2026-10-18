"""One bounded export run; scheduling and production sink deployment belong to O3."""

import json
import os
import ssl

from sqlalchemy import create_engine

from calorie_app.modules.identity.ledger_transport import HTTPSLedgerTransport, export_once


def main():
    engine = None
    transport = None
    try:
        context = ssl.create_default_context(cafile=os.environ["LEDGER_RECEIVER_CA"])
        transport = HTTPSLedgerTransport(
            os.environ["LEDGER_RECEIVER_URL"],
            bearer=os.environ["LEDGER_RECEIVER_TOKEN"],
            ssl_context=context,
        )
        engine = create_engine(os.environ["LEDGER_EXPORT_DATABASE_URL"], hide_parameters=True)
        print(json.dumps({"version": 1, "delivered_batches": export_once(engine, transport)}))
        return 0
    except Exception:
        print("Ledger delivery failed; completion remains blocked")
        return 2
    finally:
        if transport:
            transport.close()
        if engine:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
