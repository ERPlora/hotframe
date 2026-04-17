"""
Pydantic-based form rendering and validation.

Replaces Django forms / crispy-forms.  Uses Pydantic models as the schema
source and produces HTML that follows UX library conventions.

Usage::

    from hotframe.forms.rendering import FormRenderer
    from pydantic import BaseModel

    class ProductForm(BaseModel):
        name: str
        price: float
        sku: str | None = None

    # In a view:
    obj, errors = FormRenderer.validate(ProductForm, form_data)
    if errors:
        return {"form_data": form_data, "errors": errors}
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup, escape
from pydantic import BaseModel, ValidationError


class FormRenderer:
    """Render Pydantic models as HTML forms with error display.

    This is a stateless utility class — all methods are static.
    """

    @staticmethod
    def validate(
        schema_class: type[BaseModel],
        form_data: dict[str, Any],
    ) -> tuple[BaseModel | None, dict[str, str]]:
        """Validate form data against a Pydantic schema.

        Args:
            schema_class: The Pydantic model class.
            form_data: Raw form data (e.g. from ``request.form()``).

        Returns:
            A ``(validated_object, errors)`` tuple.  If validation succeeds,
            ``errors`` is empty.  If it fails, ``validated_object`` is ``None``
            and ``errors`` maps field names to human-readable messages.
        """
        try:
            obj = schema_class(**form_data)
            return obj, {}
        except ValidationError as exc:
            errors: dict[str, str] = {}
            for err in exc.errors():
                field = str(err["loc"][0]) if err["loc"] else "__root__"
                errors[field] = err["msg"]
            return None, errors

    @staticmethod
    def render_field(
        name: str,
        *,
        value: Any = None,
        field_type: str = "text",
        label: str | None = None,
        error: str | None = None,
        required: bool = False,
        placeholder: str = "",
        css_class: str = "input",
    ) -> Markup:
        """Render a single form field as HTML.

        Produces a ``<div class="form-group">`` containing a label, input,
        and optional error message styled with UX library classes.

        Args:
            name: The field name (used for ``id`` and ``name`` attributes).
            value: Pre-filled value.
            field_type: HTML input type (``text``, ``email``, ``number``, etc.).
            label: Human-readable label (defaults to title-cased ``name``).
            error: Validation error message to display.
            required: Whether to add the ``required`` attribute.
            placeholder: Placeholder text.
            css_class: CSS class for the ``<input>`` element.

        Returns:
            Safe HTML markup for the form field.
        """
        display_label = escape(label or name.replace("_", " ").title())
        escaped_name = escape(name)
        escaped_value = escape(str(value)) if value is not None else ""
        escaped_placeholder = escape(placeholder)
        error_class = " input-error" if error else ""
        req_attr = " required" if required else ""

        label_html = (
            f'<label for="id_{escaped_name}" class="label">'
            f"{display_label}</label>"
        )
        input_html = (
            f'<input type="{escape(field_type)}" '
            f'id="id_{escaped_name}" '
            f'name="{escaped_name}" '
            f'value="{escaped_value}" '
            f'placeholder="{escaped_placeholder}" '
            f'class="{escape(css_class)}{error_class}"'
            f"{req_attr}>"
        )
        error_html = ""
        if error:
            error_html = (
                f'<p class="text-error text-sm mt-1">{escape(error)}</p>'
            )

        return Markup(
            f'<div class="form-group mb-4">'
            f"{label_html}{input_html}{error_html}"
            f"</div>"
        )

    @staticmethod
    def render_textarea(
        name: str,
        *,
        value: str = "",
        label: str | None = None,
        error: str | None = None,
        required: bool = False,
        placeholder: str = "",
        rows: int = 4,
        css_class: str = "textarea",
    ) -> Markup:
        """Render a textarea form field.

        Same conventions as ``render_field`` but for multi-line input.
        """
        display_label = escape(label or name.replace("_", " ").title())
        escaped_name = escape(name)
        escaped_value = escape(str(value)) if value else ""
        escaped_placeholder = escape(placeholder)
        error_class = " textarea-error" if error else ""
        req_attr = " required" if required else ""

        label_html = (
            f'<label for="id_{escaped_name}" class="label">'
            f"{display_label}</label>"
        )
        textarea_html = (
            f'<textarea '
            f'id="id_{escaped_name}" '
            f'name="{escaped_name}" '
            f'placeholder="{escaped_placeholder}" '
            f'rows="{rows}" '
            f'class="{escape(css_class)}{error_class}"'
            f"{req_attr}>"
            f"{escaped_value}</textarea>"
        )
        error_html = ""
        if error:
            error_html = (
                f'<p class="text-error text-sm mt-1">{escape(error)}</p>'
            )

        return Markup(
            f'<div class="form-group mb-4">'
            f"{label_html}{textarea_html}{error_html}"
            f"</div>"
        )

    @staticmethod
    def render_select(
        name: str,
        options: list[tuple[str, str]],
        *,
        value: str | None = None,
        label: str | None = None,
        error: str | None = None,
        required: bool = False,
        css_class: str = "select",
    ) -> Markup:
        """Render a ``<select>`` form field.

        Args:
            name: Field name.
            options: List of ``(value, display_text)`` tuples.
            value: Currently selected value.
            label: Human-readable label.
            error: Validation error message.
            required: Whether the field is required.
            css_class: CSS class for the ``<select>`` element.
        """
        display_label = escape(label or name.replace("_", " ").title())
        escaped_name = escape(name)
        error_class = " select-error" if error else ""
        req_attr = " required" if required else ""

        label_html = (
            f'<label for="id_{escaped_name}" class="label">'
            f"{display_label}</label>"
        )

        opts = []
        for opt_val, opt_text in options:
            selected = " selected" if opt_val == value else ""
            opts.append(
                f'<option value="{escape(opt_val)}"{selected}>'
                f"{escape(opt_text)}</option>"
            )

        select_html = (
            f'<select id="id_{escaped_name}" name="{escaped_name}" '
            f'class="{escape(css_class)}{error_class}"{req_attr}>'
            f'{"".join(opts)}</select>'
        )
        error_html = ""
        if error:
            error_html = (
                f'<p class="text-error text-sm mt-1">{escape(error)}</p>'
            )

        return Markup(
            f'<div class="form-group mb-4">'
            f"{label_html}{select_html}{error_html}"
            f"</div>"
        )
