"""FastAPI surface for the private broker behind an Envoy mTLS listener."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .contracts import SecretRequest
from .policy import SecretPolicy
from .service import PostgresSecretAudit, SecretBrokerService, SecretForbidden, SecretUnavailable


def create_app(service: SecretBrokerService) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.post("/v1/secrets/resolve")
    async def resolve_secret(
        request: Request,
        payload: SecretRequest,
        verified_identity: Annotated[
            str | None, Header(alias="X-Verified-Service-Identity")
        ] = None,
        request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> JSONResponse:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > 4096
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from None
            if too_large:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if not verified_identity:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            bundle = service.resolve(
                identity_uri=verified_identity,
                request=payload,
                request_id=request_id or str(uuid.uuid4()),
            )
        except SecretForbidden as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        except SecretUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        return JSONResponse(
            content=bundle.to_delivery_dict(),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health/live")
    async def live() -> dict[str, bool]:
        return {"ok": True}

    return app


health_app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@health_app.get("/health/live")
async def health_live() -> dict[str, bool]:
    return {"ok": True}


def build_app_from_environment() -> FastAPI:
    policy_file = os.environ.get("SECRET_BROKER_POLICY_FILE")
    if not policy_file:
        raise RuntimeError("SECRET_BROKER_POLICY_FILE is required")
    policy = SecretPolicy.from_document(json.loads(Path(policy_file).read_text(encoding="utf-8")))
    vault_address = os.environ.get("VAULT_ADDR", "")
    vault_token = os.environ.get("VAULT_TOKEN", "")
    audit_database_url = os.environ.get("RECLAIM_SECRET_AUDIT_DATABASE_URL", "")
    if not vault_address.startswith("https://") or not vault_token or not audit_database_url:
        raise RuntimeError("broker Vault and audit configuration are required")
    import hvac
    import psycopg

    vault = hvac.Client(url=vault_address, token=vault_token)

    class HvacReader:
        def read(self, path: str) -> dict[str, object] | None:
            parts = path.split("/")
            if len(parts) < 4 or parts[0] != "secret" or parts[1] != "data":
                raise RuntimeError("invalid configured Vault path")
            response = vault.secrets.kv.v2.read_secret_version(
                mount_point=parts[0], path="/".join(parts[2:]), raise_on_deleted_version=True
            )
            data = response.get("data", {})
            values = data.get("data", {}) if isinstance(data, dict) else {}
            metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
            if not isinstance(values, dict):
                return None
            return {**values, "_version": metadata.get("version", 1)}

    return create_app(
        SecretBrokerService(
            policy,
            vault=HvacReader(),
            audit=PostgresSecretAudit(lambda: psycopg.connect(audit_database_url)),
        )
    )


def main(argv: list[str] | None = None) -> int:
    import sys

    import uvicorn

    mode = (argv or sys.argv[1:] or ["api"])[0]
    if mode == "health":
        uvicorn.run(health_app, host="127.0.0.1", port=8082, log_level="warning")
    elif mode == "api":
        uvicorn.run(build_app_from_environment(), host="127.0.0.1", port=9001, log_level="warning")
    else:
        raise SystemExit("mode must be api or health")
    return 0


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())
