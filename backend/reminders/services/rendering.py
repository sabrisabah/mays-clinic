"""Renders a ReminderTemplate.body_text (literal Meta-approved copy, with
{{1}}..{{n}} placeholders) into the human-readable preview shown to the
secretary before sending. This is presentation only — the actual Meta API
call in services/whatsapp.py sends the template by `name` + ordered
component values, never this rendered string.
"""
import re

PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")


def render_preview(template, variables):
    """`variables` is a {"<position>": "<value>"} dict, e.g. from
    services.whatsapp.prepare_variables()."""
    def _sub(match):
        pos = match.group(1)
        return variables.get(pos, match.group(0))
    return PLACEHOLDER_RE.sub(_sub, template.body_text)
