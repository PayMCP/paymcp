import base64
import json
from ..payment.payment_flow import Mode

def build_x402_middleware(
    providers,
    state_store,
    paidtools,
    mode,
    logger,
):
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse
    except Exception as e:
        raise RuntimeError(
            "Starlette is required for build_x402_middleware. "
            "Install 'starlette' (or FastAPI) or use the MCP-native x402 flow instead."
        ) from e

    class X402Middleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            try:
                if request.method.upper() != "POST":
                    return await call_next(request)

                provider = providers.get("x402")
                if provider is None:
                    logger.debug("[PayMCP] passing middleware for non-x402 provider")
                    return await call_next(request)

                try:
                    body = await request.json()
                except Exception:
                    return await call_next(request)

                if body.get("method") != "tools/call":
                    return await call_next(request)

                session_id = request.headers.get("mcp-session-id") or ""

                #client_info = await get_client_info(session_id)

                #capabilities = (client_info or {}).get("capabilities") or {}
                #logger.debug("[PayMCP] client capabilities %s",capabilities)
                client_x402 = False #bool(capabilities.get("x402")) #TODO check if client supports x402 for mode.AUTO

                if not (
                    mode == Mode.X402
                    or (mode == Mode.AUTO and client_x402)
                ):
                    return await call_next(request)

                tool_name = (body.get("params") or {}).get("name") or "unknown"
                price_info = paidtools.get(tool_name)
                if not price_info:
                    return await call_next(request)

                payment_sig = (
                    request.headers.get("payment-signature")
                    or request.headers.get("x-payment")
                )

                if payment_sig:
                    return await call_next(request)

                newpayment = provider.create_payment(
                    price_info["amount"],
                    price_info["currency"],
                    price_info.get("description", ""),
                )

                payment_id, _, payment_data = (
                    newpayment[0],
                    newpayment[1],
                    newpayment[2] if len(newpayment) > 2 else None,
                )
                x402_version = payment_data.get("x402Version")


                if x402_version == 1:
                    await state_store.set(f"{session_id}-{tool_name}", {"paymentData": payment_data})
                else:
                    await state_store.set(str(payment_id), {"paymentData": payment_data})

                header_value = base64.b64encode(
                    json.dumps(payment_data).encode()
                ).decode()

                if logger:
                    logger.debug("[PayMCP] sending x402 payment-required")

                resp = JSONResponse(payment_data, status_code=402)
                resp.headers["PAYMENT-REQUIRED"] = header_value
                resp.headers["Content-Type"] = "application/json"
                return resp

            except Exception as e:
                if logger:
                    logger.exception("[PayMCP] x402 middleware error")
                return await call_next(request)

    return X402Middleware