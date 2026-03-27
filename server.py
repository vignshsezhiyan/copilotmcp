from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
import uvicorn
import json
import os

app = FastAPI()

# ---------------- STATIC TOKEN ----------------

STATIC_ACCESS_TOKEN = "dsfdsfsdfsdfdsfdsfdsfdsf"

# ---------------- TOOLS ----------------

def getUser(userId: str):
    print(f"[TOOLS] getUser called with userId={userId}")
    users = {
        "1": {"name": "vign", "email": "john@example.com"},
        "2": {"name": "Alice", "email": "alice@example.com"},
    }
    return users.get(userId, {"error": "User not found"})


def getContacts():
    print("[TOOLS] getContacts called")
    return [
        {"name": "David", "phone": "1234567890"},
        {"name": "Emma", "phone": "9876543210"},
    ]


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

# ---------------- OAUTH STATIC CONFIG ----------------

OAUTH_CLIENTS = {
    "copilot-client": {
        "client_secret": "secret123",
        "redirect_uri": "https://global.consent.azure-apim.net/redirect/new-5fnewlocal-5f4252ad2342950ee9"
    }
}

AUTH_CODES = {}

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


# ---------------- OAUTH ENDPOINTS ----------------

@app.get("/authorize")
def authorize(response_type: str, client_id: str, redirect_uri: str, state: str = None):
    print("\n========== AUTHORIZE ==========")
    print(f"client_id: {client_id}")

    if client_id not in OAUTH_CLIENTS:
        return {"error": "invalid_client"}

    code = "static-auth-code"
    AUTH_CODES[code] = {"client_id": client_id}

    redirect_url = f"{redirect_uri}?code={code}"
    if state:
        redirect_url += f"&state={state}"

    print(f"Redirecting to: {redirect_url}")
    return RedirectResponse(url=redirect_url)


@app.post("/token")
async def token(request: Request):
    print("\n========== TOKEN ==========")

    form = await request.form()
    print("Form Data:", dict(form))

    code = form.get("code")
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")

    if client_id not in OAUTH_CLIENTS:
        return {"error": "invalid_client"}

    if OAUTH_CLIENTS[client_id]["client_secret"] != client_secret:
        return {"error": "invalid_client_secret"}

    if code not in AUTH_CODES:
        return {"error": "invalid_code"}

    print(f"Returning STATIC TOKEN: {STATIC_ACCESS_TOKEN}")

    return {
        "access_token": STATIC_ACCESS_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600
    }


@app.get("/.well-known/openid-configuration")
def openid_config():
    base_url = os.environ.get("BASE_URL", "https://copilotmcp.onrender.com")

    print("\n========== WELL-KNOWN ==========")

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

    print("\n========== MCP REQUEST START ==========")

    # 🔹 HEADERS
    headers = dict(request.headers)
    print("\n[HEADERS]")
    for k, v in headers.items():
        print(f"{k}: {v}")

    # 🔹 BODY
    try:
        body = await request.json()
        print("\n[BODY]")
        print(json.dumps(body, indent=2))
    except Exception as e:
        print("[BODY ERROR]", str(e))
        body = {}

    method = body.get("method")
    request_id = body.get("id")

    # 🔹 TOKEN
    auth_header = request.headers.get("Authorization", "")
    print("\n[AUTH HEADER RAW]")
    print(auth_header)

    token = auth_header.replace("Bearer ", "")
    print("[EXTRACTED TOKEN]")
    print(token)

    # 🔹 VALIDATE TOKEN
    if token != STATIC_ACCESS_TOKEN:
        print("[AUTH FAILED]")
        print("========== MCP REQUEST END ==========\n")
        return mcp_error(request_id, 403, "Invalid or missing token")

    print("[AUTH SUCCESS]")

    # -------- initialize --------
    if method == "initialize":
        response = {
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

        print("[RESPONSE]", json.dumps(response, indent=2))
        print("========== MCP REQUEST END ==========\n")
        return response

    # -------- tools/list --------
    elif method == "tools/list":
        tools = []
        for name, tool in TOOLS.items():
            tools.append({
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["schema"]
            })

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools}
        }

        print("[RESPONSE]", json.dumps(response, indent=2))
        print("========== MCP REQUEST END ==========\n")
        return response

    # -------- tools/call --------
    elif method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        print(f"[TOOL CALL] {tool_name}")
        print(f"[ARGS] {args}")

        tool = TOOLS.get(tool_name)
        if not tool:
            return mcp_error(request_id, -32601, "Tool not found")

        try:
            result = tool["handler"](**args) if args else tool["handler"]()
            response = mcp_result(request_id, result)

            print("[RESPONSE]", json.dumps(response, indent=2))
            print("========== MCP REQUEST END ==========\n")
            return response

        except Exception as e:
            print("[ERROR]", str(e))
            return mcp_error(request_id, 500, str(e))

    print("[UNKNOWN METHOD]")
    print("========== MCP REQUEST END ==========\n")

    return mcp_error(request_id, -32600, "Unknown method")


# ---------------- RUN SERVER ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[SERVER START] Running on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
