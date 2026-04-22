from fastapi.templating import Jinja2Templates
from markupsafe import Markup
import re

# ✅ Global templates instance
templates = Jinja2Templates(directory="app/templates")


# ✅ Highlight filter
def highlight(text, query):
    if not text or not query:
        return text

    pattern = "|".join(re.escape(word) for word in query.split())

    highlighted = re.sub(
        f"({pattern})",
        r"<mark>\1</mark>",
        text,
        flags=re.IGNORECASE
    )
    return Markup(highlighted)


# ✅ Register filter
templates.env.filters["highlight"] = highlight