import base64
import json

def build_x402_middleware(
    providers,
    state_store,
    paidtools,
    mode,
    get_client_info,
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
                client_info = await get_client_info(session_id)

                capabilities = (client_info or {}).get("capabilities") or {}
                client_x402 = bool(capabilities.get("x402"))

                mode_str = str(mode).lower()
                if not (
                    mode_str.endswith("x402")
                    or (mode_str.endswith("auto") and client_x402)
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

                create_res = await provider.create_payment(
                    price_info["amount"],
                    price_info["currency"],
                    price_info.get("description", ""),
                )

                payment_id = create_res["paymentId"]
                payment_data = create_res["paymentData"]
                x402_version = payment_data.get("x402Version")

                if x402_version == 1:
                    sid = client_info.get("sessionId") or session_id
                    if not sid:
                        return JSONResponse(
                            {"error": "No session id provided by MCP client"},
                            status_code=400,
                        )
                    await state_store.set(f"{sid}-{tool_name}", {"paymentData": payment_data})
                else:
                    await state_store.set(str(payment_id), {"paymentData": payment_data})

                header_value = base64.b64encode(
                    json.dumps(payment_data).encode()
                ).decode()

                if logger:
                    logger.info("[PayMCP] sending x402 payment-required")

                resp = JSONResponse(payment_data, status_code=402)
                resp.headers["PAYMENT-REQUIRED"] = header_value
                resp.headers["Content-Type"] = "application/json"
                return resp

            except Exception as e:
                if logger:
                    logger.exception("[PayMCP] x402 middleware error")
                return await call_next(request)

    return X402Middleware