from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
import uvicorn
import json
import uuid
import os

app = FastAPI()

# ---------------- TOOLS ----------------

def getUser(userId: str):
    users = {
        "1": {"name": "vign", "email": "john@example.com"},
        "2": {"name": "Alice", "email": "alice@example.com"},
    }
    return users.get(userId, {"error": "User not found"})


def getContacts():
    return [
        {"name": "David", "phone": "1234567890"},
        {"name": "Emma", "phone": "9876543210"},
    ]


# ---------------- TOOL REGISTRY ----------------

TOOLS = {
    "getUser": {
        "handler": getUser,
        "description": "Get user by id",
        "schema": {
            "type": "object",
            "properties": {
                "userId": {"type": "string"}
            },
            "required": ["userId"]
        }
    },
    "getContacts": {
        "handler": getContacts,
        "description": "List all contacts",
        "schema": {
            "type": "object",
            "properties": {}
        }
    }
}

# ---------------- STATIC OAUTH STORAGE ----------------

OAUTH_CLIENTS = {
    "copilot-client": {
        "client_secret": "secret123",
        "redirect_uri": "https://global.consent.azure-apim.net/redirect/new-5ftpi-5f4252ad2342950ee9"
    }
}

AUTH_CODES = {}
ACCESS_TOKENS = {}

# ---------------- HELPERS ----------------

def mcp_result(id, data):
    return {
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(data)
                }
            ],
            "isError": False
        }
    }


def mcp_error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message
        }
    }


def get_token(request: Request):
    auth = request.headers.get("Authorization", "")
    return auth.replace("Bearer ", "")


# ---------------- OAUTH ENDPOINTS ----------------

@app.get("/authorize")
def authorize(response_type: str, client_id: str, redirect_uri: str, state: str = None):

    if client_id not in OAUTH_CLIENTS:
        return {"error": "invalid_client"}

    code = str(uuid.uuid4())

    AUTH_CODES[code] = {"client_id": client_id}

    redirect_url = f"{redirect_uri}?code={code}"
    if state:
        redirect_url += f"&state={state}"

    return RedirectResponse(url=redirect_url)


@app.post("/token")
async def token(request: Request):
    form = await request.form()

    code = form.get("code")
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")

    if client_id not in OAUTH_CLIENTS:
        return {"error": "invalid_client"}

    if OAUTH_CLIENTS[client_id]["client_secret"] != client_secret:
        return {"error": "invalid_client_secret"}

    if code not in AUTH_CODES:
        return {"error": "invalid_code"}

    access_token = str(uuid.uuid4())

    ACCESS_TOKENS[access_token] = {"client_id": client_id}

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600
    }


@app.get("/.well-known/openid-configuration")
def openid_config():
    base_url = os.environ.get("BASE_URL", "https://copilotmcp.onrender.com")

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "scopes_supported": ["openid"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"]
    }


# ---------------- MCP ROUTER ----------------

@app.post("/mcp")
async def mcp(request: Request):

    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")

    token = get_token(request)

    if token not in ACCESS_TOKENS:
        return mcp_error(request_id, 403, "Invalid or missing token")

    # -------- initialize --------
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "Simple MCP Server",
                    "version": "1.0"
                }
            }
        }

    # -------- tools/list --------
    elif method == "tools/list":

        tools = []

        for name, tool in TOOLS.items():
            tools.append({
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["schema"]
            })

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools
            }
        }

    # -------- tools/call --------
    elif method == "tools/call":

        params = body.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        tool = TOOLS.get(tool_name)

        if not tool:
            return mcp_error(request_id, -32601, "Tool not found")

        try:
            handler = tool["handler"]

            if args:
                result = handler(**args)
            else:
                result = handler()

            return mcp_result(request_id, result)

        except Exception as e:
            return mcp_error(request_id, 500, str(e))

    return mcp_error(request_id, -32600, "Unknown method")


# ---------------- RUN SERVER ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
