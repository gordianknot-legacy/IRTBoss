"""The Jinja environment and the render entry point.

Two settings here are load-bearing rather than conventional.

``autoescape=True``. Item ids are CSV column headers, project names and
descriptions are free text, and failure reasons can contain a raw exception
message. All of it is user-supplied and all of it reaches the page.

``undefined=StrictUndefined``. By default Jinja renders an unknown variable as
an empty string, so a renamed diagnostic field would turn into a blank table
cell — a number silently becoming nothing, which is the precise failure this
product exists to prevent. Strict mode turns that into an error at render time,
where it is visible, instead of a clean-looking hole in a report someone acts
on.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import formatting
from .context import ReportContext, build_context

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE = "report.html.j2"


def _timestamp(value: Any) -> str:
    if value is None:
        return formatting.ABSENT
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return str(value)


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "html.j2"], default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        num=formatting.num,
        integer=formatting.integer,
        percent=formatting.percent,
        pvalue=formatting.pvalue,
        estimate=formatting.estimate_with_se,
        yes_no=formatting.yes_no,
        duration=formatting.duration,
        timestamp=_timestamp,
    )
    # Also exposed as callables, because both read better applied to two
    # arguments than piped: `estimate(value, se)` rather than
    # `value | estimate(se)`.
    env.globals.update(
        ABSENT=formatting.ABSENT,
        interval=formatting.interval,
        estimate=formatting.estimate_with_se,
    )
    return env


def render(context: ReportContext, *, template: str = DEFAULT_TEMPLATE) -> str:
    """Render a report to a self-contained HTML string.

    Self-contained matters: the CSS is inlined, so a saved or emailed report
    still renders in five years. A report that depends on a stylesheet served
    from this application is a report that silently changes when the
    application does.
    """

    return _environment().get_template(template).render(ctx=context)


def render_run(
    *, run: Any, dataset: Any, project: Any, template: str = DEFAULT_TEMPLATE
) -> str:
    """Convenience path from ORM rows straight to HTML."""

    return render(
        build_context(run=run, dataset=dataset, project=project), template=template
    )
