# -*- coding: utf-8 -*-
"""Launch XiaomiPCManager dropfile trigger."""
from __future__ import annotations

import os
import subprocess


def trigger_dropfile(launch_path: str) -> None:
    """Start Launch.exe with --contextmenu_dropfile=1 to open the transfer picker."""
    if not os.path.isfile(launch_path):
        raise FileNotFoundError(launch_path)
    subprocess.Popen([launch_path, "--contextmenu_dropfile=1"])
