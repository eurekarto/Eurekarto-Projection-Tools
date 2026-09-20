# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later


def classFactory(iface):
    from .plugin import EurekartoProjectionTools
    return EurekartoProjectionTools(iface)
