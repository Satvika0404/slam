"""Plain-text evidence parser.

Two shapes are handled. Pipe-delimited lookup rows
(``time | system | resource | category | state | value``) become the same kind
of lookup record the JSON and log parsers produce. Anything else is treated as
document text and goes through entity-anchor extraction. A row that does not
fit either shape is reported, never skipped silently.
"""

from __future__ import annotations

import re

from ..issues import Issue
from ..timeutil import parse_utc
from .base import ParseOutput, ParseState, RawFact, SourceContext, line_span, quote_of
from .doctext import TextLine, extract_facts, quote_for, split_blocks

PARSER_NAME = "text"
PARSER_VERSION = "1.0.0"

_ROW = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+\|")
# A table row may be written as a list item ("- 2026-... | system | ...").
_BULLET = re.compile(r"^[-*•]\s+")
_SNAPSHOT = re.compile(r"^snapshot\s*[:=]\s*(\S+)\s*$", re.IGNORECASE)


def parse_text(ctx: SourceContext, data: bytes) -> ParseOutput:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        issue = Issue("TEXT_NOT_UTF8", "error", "file is not valid UTF-8", ctx.source_id)
        return ParseOutput(PARSER_NAME, PARSER_VERSION, (), (issue,), "failed")

    lines = text.lstrip("﻿").split("\n")
    issues: list[Issue] = []
    facts: list[RawFact] = []
    prose: list[TextLine] = []
    rows = 0
    bad_rows: list[int] = []

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r")
        unbulleted = _BULLET.sub("", line.strip())
        if _ROW.match(unbulleted):
            line = unbulleted  # a list-item row is still a table row
        if not line.strip():
            continue
        if _ROW.match(line):
            columns = [c.strip() for c in line.split("|")]
            if len(columns) < 6:
                bad_rows.append(number)
                continue
            try:
                when = parse_utc(columns[0])
            except ValueError:
                bad_rows.append(number)
                continue
            rows += 1
            system, resource, category, state = columns[1], columns[2], columns[3], columns[4]
            value = "|".join(columns[5:]).strip()
            facts.append(
                RawFact(
                    layout="text.pipe_row",
                    effective_time=when,
                    span=line_span(ctx.source_id, number, quote=quote_of(line)),
                    data={
                        "system": system,
                        "resource_id": resource,
                        "record_type": category,
                        "result": state,
                        "subject_reference": value,
                    },
                    system_id=system or None,
                    resource_id=resource or None,
                    collection=category or None,
                    state=state or None,
                    subject_keys=(value,) if value else (),
                )
            )
        elif _SNAPSHOT.match(line.strip()):
            continue  # header metadata; the manifest capture time already covers it
        else:
            prose.append(TextLine(page=1, text=line.strip(), line_no=number))

    if rows:
        # Prose around a table (titles, notes) carries no anchors worth extracting.
        extracted: list[RawFact] = []
    else:
        extracted = extract_facts(
            ctx,
            split_blocks(prose),
            layout="text",
            span_for=lambda ln: line_span(ctx.source_id, ln.line_no or 1, quote=quote_for(ln)),
        )
    facts.extend(extracted)

    if bad_rows:
        shown = ", ".join(str(n) for n in bad_rows[:5])
        issues.append(
            Issue(
                "TEXT_ROWS_UNPARSED",
                "warning",
                f"{len(bad_rows)} timestamped row(s) did not match the 6-column layout: {shown}",
                ctx.source_id,
                f"line {bad_rows[0]}",
            )
        )
    if not facts:
        issues.append(
            Issue(
                "TEXT_NO_FACTS",
                "warning",
                "no records or identifiers recognised; this is not evidence of absence",
                ctx.source_id,
            )
        )
    status: ParseState = "parsed" if facts and not bad_rows else "partial"
    stats = {"rows": rows, "facts": len(facts), "unparsed_rows": len(bad_rows)}
    return ParseOutput(PARSER_NAME, PARSER_VERSION, tuple(facts), tuple(issues), status, stats)
