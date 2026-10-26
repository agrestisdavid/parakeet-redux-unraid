from pathlib import Path
import re
import xml.etree.ElementTree as ET
from redux import __version__


def test_debian_repositories_and_direct_packages_are_pinned():
    sources = Path('debian.sources').read_text()
    assert sources.count('20261026T000000Z') == 2
    assert sources.count('Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg') == 2
    assert 'trusted=yes' not in sources
    docker = Path('Dockerfile').read_text()
    assert docker.count('COPY debian.sources /etc/apt/sources.list.d/debian.sources') == 2
    for line in docker.splitlines():
        if 'apt-get install' in line:
            packages = line.split('--no-install-recommends ', 1)[1].split(' &&', 1)[0].split()
            assert packages and all('=' in item for item in packages)
    assert 'build-packages.txt' in docker and 'runtime-packages.txt' in docker
    assert '!debian.sources' in Path('.dockerignore').read_text()


def test_release_versions_agree():
    assert f'org.opencontainers.image.version="{__version__}"' in Path('Dockerfile').read_text()
    assert ET.parse('unraid/parakeet-redux.xml').getroot().findtext('Repository').endswith(':' + __version__)
