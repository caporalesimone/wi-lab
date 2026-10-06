"""Presentation tweaks for the interactive API documentation.

Shared by the live ``/docs`` page and the exported ``swagger.html`` so both look the same.
"""

# Swagger UI places a group's description to the right of its title. Wrapping the heading
# row puts the description on its own line below the title instead, which reads better for
# paragraphs of text. ReDoc already lays it out that way.
SWAGGER_UI_EXTRA_CSS = """
.swagger-ui .opblock-tag { flex-wrap: wrap; }
.swagger-ui .opblock-tag small {
  order: 3; flex: 1 0 100%; padding: 2px 0 10px 0; margin: 0;
  font-size: 14px; line-height: 1.5;
}
"""
