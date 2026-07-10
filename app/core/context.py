from contextvars import ContextVar

app_code_ctx: ContextVar[str] = ContextVar('app_code_ctx', default="XIAOBANG")



