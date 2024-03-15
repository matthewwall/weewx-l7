# installer for the weewx-sdr driver
# Copyright 2024 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

from weecfg.extension import ExtensionInstaller

def loader():
    return L7Installer()

class L7Installer(ExtensionInstaller):
    def __init__(self):
        super(L7Installer, self).__init__(
            version="0.1",
            name='l7',
            description='Capture data from Raddy L7 LoRa weather station',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            files=[('bin/user', ['bin/user/l7.py'])]
            )
