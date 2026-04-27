"""Gemini model registry. Build IDs rotate periodically; keep this file
in sync with what gemini.google.com sends in its `x-goog-ext-525001261-jspb`
header for each model. ModelHeaderInvalid errors mean these are stale."""

from __future__ import annotations

from dataclasses import dataclass, field

HEADER_MODEL_KEY = "x-goog-ext-525001261-jspb"


def _model_header(model_id: str, capacity_tail: int) -> dict[str, str]:
    return {
        HEADER_MODEL_KEY: f'[1,null,null,null,"{model_id}",null,null,0,[4],null,null,{capacity_tail}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


@dataclass(frozen=True)
class Model:
    """One Gemini model. Empty `headers` lets the web UI's default kick in."""

    name: str
    headers: dict[str, str] = field(default_factory=dict)
    advanced_only: bool = False

    def __str__(self) -> str:
        return self.name


# UNSPECIFIED: defer model choice to whatever Gemini's web UI is currently
# defaulting to. Most flexible — avoids needing to update build IDs manually.
MODEL_UNSPECIFIED = Model(name="unspecified")

MODEL_PRO = Model(
    name="gemini-3-pro",
    headers=_model_header("9d8ca3786ebdfbea", 1),
)
MODEL_FLASH = Model(
    name="gemini-3-flash",
    headers=_model_header("fbb127bbb056c959", 1),
)
MODEL_THINKING = Model(
    name="gemini-3-flash-thinking",
    headers=_model_header("5bf011840784117a", 1),
)

# Advanced (paid) tier. Requires an active Gemini Advanced subscription on
# the account whose cookies are in use.
MODEL_PRO_ADVANCED = Model(
    name="gemini-3-pro-advanced",
    headers=_model_header("e6fa609c3fa255c0", 2),
    advanced_only=True,
)
MODEL_FLASH_ADVANCED = Model(
    name="gemini-3-flash-advanced",
    headers=_model_header("56fdd199312815e2", 2),
    advanced_only=True,
)
