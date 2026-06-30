"""Starlette 1.2+ changed TemplateResponse to (request, name, context).

Existing routes use the older (name, context) form where context includes
request. This shim keeps those call sites working without a mass edit.
"""
from __future__ import annotations

from typing import Any


def patch_template_response(templates: Any) -> Any:
    original = templates.TemplateResponse

    def TemplateResponse(*args: Any, **kwargs: Any):
        if (
            len(args) >= 2
            and isinstance(args[0], str)
            and isinstance(args[1], dict)
            and args[1].get("request") is not None
        ):
            name, context = args[0], args[1]
            return original(context["request"], name, context, *args[2:], **kwargs)
        return original(*args, **kwargs)

    templates.TemplateResponse = TemplateResponse
    return templates
