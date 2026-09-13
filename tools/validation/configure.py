"""Set a private archive endpoint in this container's Brownie configuration."""

import os
from pathlib import Path


def main() -> None:
    if not (url := os.environ.get("VALIDATION_RPC_URL")):
        return
    import brownie  # Creates this container's private network configuration.
    import yaml

    path = Path.home() / ".brownie/network-config.yaml"
    config = yaml.safe_load(path.read_text())
    for group in config["live"]:
        for network in group["networks"]:
            if network["id"] == "mainnet":
                network["host"] = url
    path.write_text(yaml.safe_dump(config))


if __name__ == "__main__":
    main()
