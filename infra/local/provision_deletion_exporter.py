"""Provision the separate exporter LOGIN with the protected SCRAM/session helper."""

import os
import sys
from pathlib import Path

from provision_deletion_operator import ProvisionError, configuration, provision


def main():
    try:
        if len(sys.argv) != 1:
            raise ProvisionError("invalid_arguments")
        environment = os.environ | {
            "DELETION_OPERATOR_LOGIN": os.environ.get("DELETION_EXPORTER_LOGIN", ""),
            "DELETION_OPERATOR_PASSWORD": os.environ.get("DELETION_EXPORTER_PASSWORD", ""),
        }
        provision(
            *configuration(environment),
            sql_path=Path(__file__).with_name("provision-deletion-exporter.sql"),
        )
    except ProvisionError as error:
        print(str(error), file=sys.stderr)
        return 3 if str(error) in {"invalid_arguments", "invalid_configuration"} else 1
    except Exception:
        print("provisioning_failed", file=sys.stderr)
        return 1
    print("Deletion exporter provisioning and effective ACL verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
