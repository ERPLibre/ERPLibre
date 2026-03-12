#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from types import SimpleNamespace

from script.docker.docker_update_version import edit_text, edit_docker_prod


class TestEditText(unittest.TestCase):
    """Test docker-compose.yml image version update."""

    def _write_compose(self, content):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        )
        f.write(content)
        f.close()
        return f.name

    def test_updates_image_after_erplibre(self):
        path = self._write_compose(
            "services:\n"
            "  ERPLibre:\n"
            "    image: old:1.0\n"
            "    ports:\n"
        )
        config = SimpleNamespace(
            docker_compose_file=path,
            prod_version="myrepo:2.0",
        )
        edit_text(config)
        with open(path) as f:
            content = f.read()
        self.assertIn("image: myrepo:2.0", content)
        self.assertNotIn("old:1.0", content)
        os.unlink(path)

    def test_preserves_other_lines(self):
        path = self._write_compose(
            "version: '3'\n"
            "services:\n"
            "  ERPLibre:\n"
            "    image: old:1.0\n"
            "  postgres:\n"
            "    image: postgres:14\n"
        )
        config = SimpleNamespace(
            docker_compose_file=path,
            prod_version="new:3.0",
        )
        edit_text(config)
        with open(path) as f:
            content = f.read()
        self.assertIn("version: '3'", content)
        self.assertIn("postgres:14", content)
        os.unlink(path)


class TestEditDockerProd(unittest.TestCase):
    """Test Dockerfile.prod FROM line update."""

    def _write_dockerfile(self, content):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".pkg", delete=False
        )
        f.write(content)
        f.close()
        return f.name

    def test_updates_from_line(self):
        path = self._write_dockerfile(
            "FROM base:old\nRUN apt-get update\n"
        )
        config = SimpleNamespace(
            docker_compose_file="unused",
            docker_prod=path,
            base_version="base:new",
        )
        edit_docker_prod(config)
        with open(path) as f:
            content = f.read()
        self.assertIn("FROM base:new", content)
        self.assertNotIn("FROM base:old", content)
        os.unlink(path)

    def test_preserves_run_lines(self):
        path = self._write_dockerfile(
            "FROM base:old\nRUN echo hello\nCOPY . /app\n"
        )
        config = SimpleNamespace(
            docker_compose_file="unused",
            docker_prod=path,
            base_version="base:v2",
        )
        edit_docker_prod(config)
        with open(path) as f:
            content = f.read()
        self.assertIn("RUN echo hello", content)
        self.assertIn("COPY . /app", content)
        os.unlink(path)

    def test_multiple_from_lines(self):
        path = self._write_dockerfile(
            "FROM base:old\nRUN build\nFROM base:old\nRUN run\n"
        )
        config = SimpleNamespace(
            docker_compose_file="unused",
            docker_prod=path,
            base_version="base:v3",
        )
        edit_docker_prod(config)
        with open(path) as f:
            lines = f.readlines()
        from_lines = [l for l in lines if l.startswith("FROM")]
        for line in from_lines:
            self.assertIn("base:v3", line)
        os.unlink(path)
