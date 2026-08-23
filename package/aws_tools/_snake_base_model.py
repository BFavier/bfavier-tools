from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_pascal


class _SnakeBaseModel(BaseModel):
    """
    Handle converting camel case to snake case
    """
    model_config = ConfigDict(
        alias_generator=to_pascal,
        populate_by_name=True,
    )
