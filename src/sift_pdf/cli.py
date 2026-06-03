"""SiftPDF CLI — thin wrapper for local dev and batch use."""

from __future__ import annotations

import click


@click.group()
def main() -> None:
    """SiftPDF — stateless imposition planning solver."""


@main.command()
def version() -> None:
    """Print the package version."""
    from sift_pdf.version import VERSION

    click.echo(VERSION)


@main.command()
def health() -> None:
    """Print health info (codex version, enabled tiers)."""
    import json

    try:
        from codex_pdf import __version__ as cv
        from codex_pdf.geom import GEOM_SCHEMA_VERSION

        codex_info = {"version": cv, "geom_schema": GEOM_SCHEMA_VERSION}
    except ImportError:
        codex_info = {"version": "unavailable"}
    from sift_pdf.version import VERSION

    click.echo(json.dumps({"sift_version": VERSION, "codex": codex_info}, indent=2))


@main.command()
def contract() -> None:
    """Print the /v1/contract surface."""
    import json

    from sift_pdf.version import SOLVER_SCHEMA_VERSIONS, VERSION

    try:
        from codex_pdf.geom import GEOM_SCHEMA_VERSION

        section_versions = {"geom": GEOM_SCHEMA_VERSION}
    except ImportError:
        section_versions = {}
    click.echo(
        json.dumps(
            {
                "contract_name": "sift-pdf",
                "package_version": VERSION,
                "solver_schema_versions": SOLVER_SCHEMA_VERSIONS,
                "codex_section_versions": section_versions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
