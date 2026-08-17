import functools
import inspect
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, TypeVar, cast

import pydantic_core
from pydantic import BaseModel, RootModel, ValidationError
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route


class PydanticJSONResponse(Response):
    media_type = "application/json"

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)

    def render(self, content: Any) -> bytes:
        return pydantic_core.to_json(content)


def _ret_to_resp(ret: Any) -> Response:
    if isinstance(ret, Response):
        return ret
    status_code = 200
    headers = None
    background = None
    if isinstance(ret, tuple):
        ret = cast(tuple[Any, ...], ret)
        if len(ret) == 0:
            body = None
        else:
            body = ret[0]
            if len(ret) == 2:
                status_code = ret[1]
            elif len(ret) == 3:
                status_code = ret[1]
                headers = ret[2]
            elif len(ret) == 4:
                status_code = ret[1]
                headers = ret[2]
                background = ret[3]
    else:
        body = ret
    return PydanticJSONResponse(body, status_code, headers, None, background)


def to_pydantic_json_response[**P](func: Callable[P, Any]) -> Callable[P, Any]:
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapper_async(*args: P.args, **kwargs: P.kwargs) -> Response:
            ret = await func(*args, **kwargs)
            return _ret_to_resp(ret)

        return wrapper_async
    else:

        @functools.wraps(func)
        def wrapper_sync(*args: P.args, **kwargs: P.kwargs) -> Response:
            ret = func(*args, **kwargs)
            return _ret_to_resp(ret)

        return wrapper_sync


class PydanticRoute(Route):
    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: Collection[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
        middleware: Sequence[Middleware] | None = None,
    ):
        super().__init__(
            path,
            to_pydantic_json_response(endpoint),
            methods=methods,
            name=name,
            include_in_schema=include_in_schema,
            middleware=middleware,
        )


class InvalidRequest(Exception):
    def __init__(self, msg: str, data: Any | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.data = data

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.msg!r}, data={self.data!r})"


_PathParamT = TypeVar("_PathParamT")


def extract_path_param(request: Request[Any], name: str, type_: type[_PathParamT]) -> _PathParamT:
    if name not in request.path_params:
        raise InvalidRequest(f"{name!r} not in path param")
    val = request.path_params[name]
    try:
        return RootModel[type_].model_validate(val).root
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise InvalidRequest(f"invalid path parameter {name!r}: {errors}")


_ReqBodyT = TypeVar("_ReqBodyT", bound=BaseModel)


async def extract_req_body(request: Request[Any], model_type: type[_ReqBodyT]) -> _ReqBodyT:
    body = await request.body()
    try:
        return model_type.model_validate_json(body)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise InvalidRequest(f"invalid request body: {errors}")
